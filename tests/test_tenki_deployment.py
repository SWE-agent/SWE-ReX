import asyncio
import os
from types import SimpleNamespace

import pytest

from swerex.deployment.tenki import TenkiDeployment
from swerex.runtime.abstract import Command


class _FakeExecResult:
    def __init__(self, exit_code: int = 0, stdout_text: str = "", stderr_text: str = ""):
        self.exit_code = exit_code
        self.stdout_text = stdout_text
        self.stderr_text = stderr_text


def _make_fake_sandbox_class():
    """A fresh fake `tenki_sandbox.Sandbox` class (with its own creation log) per test."""

    class FakeSandbox:
        created: list = []

        def __init__(self):
            self.id = f"fake-sandbox-{len(type(self).created)}"
            self.state = "RUNNING"
            self.closed = False
            self.fail_next_close = False
            type(self).created.append(self)

        @classmethod
        def create(cls, **kwargs):
            return cls()

        def exec(self, *argv, **kwargs):
            if argv and "tail" in argv[-1]:
                return _FakeExecResult(stdout_text="FAKE SERVER LOG")
            return _FakeExecResult()

        def expose_port(self, port, ttl=None):
            # Nothing listens on port 9 ("discard"), so connections fail fast.
            return SimpleNamespace(url="http://127.0.0.1:9")

        def refresh(self):
            pass

        def close_if_open(self):
            if self.fail_next_close:
                self.fail_next_close = False
                msg = "simulated termination failure"
                raise RuntimeError(msg)
            self.closed = True

    return FakeSandbox


@pytest.fixture
def fake_sandbox_class(monkeypatch):
    cls = _make_fake_sandbox_class()
    monkeypatch.setattr("swerex.deployment.tenki.Sandbox", cls)
    return cls


@pytest.fixture
def patched_wait(monkeypatch):
    """Skip the readiness probe (there is no real server to connect to)."""

    async def _noop(self, timeout):
        return None

    monkeypatch.setattr(TenkiDeployment, "_wait_until_alive", _noop)


def _make_deployment(**kwargs) -> TenkiDeployment:
    config = dict(project_id="proj-test", api_key="tk_test", runtime_retries=0, runtime_timeout=0.2)
    config.update(kwargs)
    return TenkiDeployment(**config)


async def test_tenki_start_twice_raises_and_does_not_leak(fake_sandbox_class, patched_wait):
    d = _make_deployment()
    await d.start()
    with pytest.raises(RuntimeError, match="already started"):
        await d.start()
    assert len(fake_sandbox_class.created) == 1
    await d.stop()
    assert fake_sandbox_class.created[0].closed


async def test_tenki_startup_failure_terminates_sandbox_and_surfaces_log(fake_sandbox_class):
    d = _make_deployment(startup_timeout=0.3)
    with pytest.raises(RuntimeError, match="FAKE SERVER LOG"):
        await d.start()
    assert fake_sandbox_class.created[0].closed
    with pytest.raises(RuntimeError):
        await d.is_alive()


async def test_tenki_stop_termination_failure_is_retryable(fake_sandbox_class, patched_wait):
    d = _make_deployment()
    await d.start()
    sandbox = fake_sandbox_class.created[0]
    sandbox.fail_next_close = True
    with pytest.raises(RuntimeError, match="simulated termination failure"):
        await d.stop()
    assert not sandbox.closed
    # The handle is kept, so stop() can be retried
    await d.stop()
    assert sandbox.closed


async def test_tenki_stop_terminates_sandbox_when_runtime_close_cancelled(fake_sandbox_class, patched_wait):
    d = _make_deployment()
    await d.start()

    class CancellingRuntime:
        async def close(self):
            raise asyncio.CancelledError

    d._runtime = CancellingRuntime()
    with pytest.raises(asyncio.CancelledError):
        await d.stop()
    assert fake_sandbox_class.created[0].closed


@pytest.mark.cloud
@pytest.mark.slow
@pytest.mark.skipif(
    not (os.getenv("TENKI_AUTH_TOKEN") or os.getenv("TENKI_API_KEY")),
    reason="Tenki credentials not set (TENKI_AUTH_TOKEN or TENKI_API_KEY)",
)
async def test_tenki_deployment():
    d = TenkiDeployment(startup_timeout=60 * 10)
    with pytest.raises(RuntimeError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    response = await d.runtime.execute(Command(command="echo 'hello world'", shell=True))
    assert response.exit_code == 0
    assert "hello world" in response.stdout
    await d.stop()
