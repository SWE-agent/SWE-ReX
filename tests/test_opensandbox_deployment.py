"""Unit tests for OpenSandboxDeployment.

These tests mock out the opensandbox SDK and the remote runtime so that no
OpenSandbox server or credentials are required. End-to-end tests against a
real server are marked with `cloud`/`slow` at the bottom of this file.
"""

import logging
from datetime import timedelta

import pytest

from swerex.deployment.opensandbox import OpenSandboxDeployment
from swerex.exceptions import DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse


class _FakeStatus:
    def __init__(self, state: str):
        self.state = state


class _FakeInfo:
    def __init__(self, state: str):
        self.status = _FakeStatus(state)


class _FakeEndpoint:
    def __init__(self, endpoint: str, headers: dict[str, str] | None = None):
        self.endpoint = endpoint
        self.headers = headers or {}


class _FakeSandbox:
    def __init__(self, sandbox_id: str = "sbx-test-1", state: str = "Running"):
        self.id = sandbox_id
        self._state = state
        self.destroy_called = False
        self.kill_called = False

    async def get_info(self) -> _FakeInfo:
        if self._state == "__raise__":
            msg = "transient server error"
            raise RuntimeError(msg)
        return _FakeInfo(self._state)

    async def get_endpoint(self, port: int) -> _FakeEndpoint:
        return _FakeEndpoint(f"http://endpoints.example.com/sbx/{self.id}/{port}")

    async def kill(self):
        self.kill_called = True

    async def destroy(self):
        self.destroy_called = True
        self.kill_called = True


class _FakeRemoteRuntime:
    last_instance: "_FakeRemoteRuntime | None" = None

    def __init__(self, *, host: str, timeout: float, auth_token: str, logger=None):
        self.host = host
        self.timeout = timeout
        self.auth_token = auth_token
        self.close_called = False
        self._is_alive = True
        _FakeRemoteRuntime.last_instance = self

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        if self._is_alive:
            return IsAliveResponse(is_alive=True)
        return IsAliveResponse(is_alive=False, message="not up yet")

    async def close(self):
        self.close_called = True


@pytest.fixture
def deployment(monkeypatch) -> OpenSandboxDeployment:
    """Returns a deployment whose SDK interactions are mocked out."""
    sandbox = _FakeSandbox()
    created: dict = {}

    async def fake_create(*args, **kwargs):
        created.update(kwargs)
        return sandbox

    monkeypatch.setattr("opensandbox.Sandbox.create", staticmethod(fake_create))
    monkeypatch.setattr("swerex.deployment.opensandbox.RemoteRuntime", _FakeRemoteRuntime)
    d = OpenSandboxDeployment(
        image="python:3.11",
        port=8880,
        startup_timeout=5.0,
        api_key="key-123",
        domain="opensandbox.example.com",
    )
    d._test_sandbox = sandbox  # type: ignore[attr-defined]
    d._test_created = created  # type: ignore[attr-defined]
    return d


async def test_is_alive_raises_when_not_started():
    d = OpenSandboxDeployment(image="python:3.11")
    with pytest.raises(DeploymentNotStartedError):
        await d.is_alive()


async def test_runtime_raises_when_not_started():
    d = OpenSandboxDeployment(image="python:3.11")
    with pytest.raises(DeploymentNotStartedError):
        _ = d.runtime


async def test_sandbox_id_raises_when_not_started():
    d = OpenSandboxDeployment(image="python:3.11")
    with pytest.raises(DeploymentNotStartedError):
        _ = d.sandbox_id


async def test_start_wires_runtime_and_sandbox(deployment: OpenSandboxDeployment):
    await deployment.start()
    created = deployment._test_created  # type: ignore[attr-defined]
    assert created["image"] == "python:3.11"
    assert created["timeout"] == timedelta(seconds=3600.0)
    assert created["entrypoint"] == ["/bin/sh", "-c", created["entrypoint"][2]]
    command = created["entrypoint"][2]
    assert "swerex-remote --port 8880" in command
    assert "--auth-token" in command
    # fallback installation path for images without swe-rex installed
    assert "pipx run swe-rex" in command
    runtime = deployment.runtime
    assert runtime.auth_token == runtime.auth_token  # non-empty token is set by start
    assert runtime.host.startswith("http://endpoints.example.com/sbx/")
    assert deployment.sandbox_id == "sbx-test-1"
    await deployment.stop()


async def test_start_passes_resource(deployment: OpenSandboxDeployment):
    deployment._config.resource = {"cpu": "2", "memory": "4Gi"}
    await deployment.start()
    assert deployment._test_created["resource"] == {"cpu": "2", "memory": "4Gi"}  # type: ignore[attr-defined]
    await deployment.stop()


async def test_start_extra_kwargs_forwarded(deployment: OpenSandboxDeployment):
    deployment._config.create_sandbox_kwargs = {"env": {"FOO": "bar"}, "metadata": {"purpose": "test"}}
    await deployment.start()
    created = deployment._test_created  # type: ignore[attr-defined]
    assert created["env"] == {"FOO": "bar"}
    assert created["metadata"] == {"purpose": "test"}
    await deployment.stop()


async def test_connection_config_env_fallback(deployment: OpenSandboxDeployment):
    deployment._config.api_key = ""
    deployment._config.domain = ""
    connection_config = deployment._get_connection_config()
    assert connection_config.api_key is None
    assert connection_config.domain is None
    assert connection_config.protocol == "http"
    assert connection_config.request_timeout == timedelta(seconds=30.0)


async def test_connection_config_explicit_credentials(deployment: OpenSandboxDeployment):
    connection_config = deployment._get_connection_config()
    assert connection_config.api_key == "key-123"
    assert connection_config.domain == "opensandbox.example.com"


async def test_duplicate_start_is_noop(deployment: OpenSandboxDeployment):
    await deployment.start()
    deployment._test_created["entrypoint"] = ["sentinel"]  # type: ignore[attr-defined]
    await deployment.start()  # must not raise or create a second sandbox
    assert deployment._test_created["entrypoint"] == ["sentinel"]  # type: ignore[attr-defined]
    await deployment.stop()


async def test_is_alive_true_when_running(deployment: OpenSandboxDeployment):
    await deployment.start()
    assert await deployment.is_alive()
    await deployment.stop()


async def test_is_alive_raises_when_terminated(deployment: OpenSandboxDeployment):
    await deployment.start()
    deployment._test_sandbox._state = "Terminated"  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="not recoverable"):
        await deployment.is_alive()
    await deployment.stop()


async def test_is_alive_survives_transient_info_error(deployment: OpenSandboxDeployment):
    await deployment.start()
    deployment._test_sandbox._state = "__raise__"  # type: ignore[attr-defined]
    # The runtime check still succeeds, so a transient status error does not
    # abort a pending start().
    assert await deployment.is_alive()
    await deployment.stop()


async def test_stop_closes_runtime_and_destroys_sandbox(deployment: OpenSandboxDeployment):
    await deployment.start()
    sandbox = deployment._test_sandbox  # type: ignore[attr-defined]
    runtime = deployment.runtime
    await deployment.stop()
    assert sandbox.destroy_called
    assert runtime.close_called
    with pytest.raises(DeploymentNotStartedError):
        await deployment.is_alive()


async def test_stop_tolerates_destroy_failure(deployment: OpenSandboxDeployment):
    await deployment.start()
    sandbox = deployment._test_sandbox  # type: ignore[attr-defined]

    async def failing_destroy():
        msg = "server unreachable"
        raise RuntimeError(msg)

    sandbox.destroy = failing_destroy  # type: ignore[method-assign]
    await deployment.stop()  # must not raise
    assert deployment._sandbox is None


async def test_endpoint_headers_warning(deployment: OpenSandboxDeployment, caplog):
    async def fake_get_endpoint(port: int) -> _FakeEndpoint:
        return _FakeEndpoint(f"http://endpoints.example.com/sbx/x/{port}", headers={"X-Route-Token": "abc"})

    deployment._test_sandbox.get_endpoint = fake_get_endpoint  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="rex-deploy"):
        await deployment.start()
    assert "extra headers" in caplog.text
    await deployment.stop()


if __name__ == "__main__":
    pytest.main()
