"""Lifecycle and authentication behavior for the optional Smol deployment."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from swerex.deployment import get_deployment
from swerex.deployment.config import SmolDeploymentConfig
from swerex.deployment.smol import SmolDeployment, _SmolRemoteRuntime
from swerex.exceptions import DeploymentNotStartedError


class FakeMachine:
    def __init__(self):
        self.deleted = False

    def endpoint(self, port):
        assert port == 8000
        return SimpleNamespace(
            http_url="https://cloud.example.test/connect",
            headers={"Authorization": "Bearer bridge-token"},
        )

    def delete(self):
        self.deleted = True


class FakeRuntime:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def is_alive(self, *, timeout=None):
        return True

    async def close(self):
        pass


def test_config_creates_smol_deployment_without_exposing_api_key():
    deployment = get_deployment(SmolDeploymentConfig(target="cloud", api_key="example-key"))
    assert isinstance(deployment, SmolDeployment)
    assert "example-key" not in repr(deployment._config)


async def test_cloud_runtime_sends_bridge_and_guest_credentials():
    runtime = _SmolRemoteRuntime(
        host="https://cloud.example.test/connect",
        port=None,
        bridge_headers={"Authorization": "Bearer bridge-token"},
        auth_token="guest-token",
    )
    assert runtime._headers == {
        "Authorization": "Bearer bridge-token",
        "X-API-Key": "guest-token",
    }


async def test_start_cleans_up_when_guest_never_becomes_ready(monkeypatch):
    from swerex.deployment import smol

    machine = FakeMachine()
    deployment = SmolDeployment(runtime_timeout=12)
    monkeypatch.setattr(deployment, "_create_machine", lambda token: machine)
    monkeypatch.setattr(smol, "_SmolRemoteRuntime", FakeRuntime)

    async def not_ready(function, *, timeout, function_timeout):
        assert timeout == 12
        assert function_timeout > 0.1  # Cloud connect bridges need more than the default 100 ms.
        msg = "guest did not start"
        raise TimeoutError(msg)

    monkeypatch.setattr(smol, "_wait_until_alive", not_ready)
    with pytest.raises(TimeoutError, match="guest did not start"):
        await deployment.start()
    assert machine.deleted
    with pytest.raises(DeploymentNotStartedError):
        _ = deployment.runtime


async def test_cancelled_start_still_deletes_created_vm(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    machine = FakeMachine()
    deployment = SmolDeployment()

    def slow_create(token):
        started.set()
        assert release.wait(timeout=5)
        return machine

    monkeypatch.setattr(deployment, "_create_machine", slow_create)
    task = asyncio.create_task(deployment.start())
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert machine.deleted


async def test_cancelled_stop_still_deletes_vm(monkeypatch):
    from swerex.deployment import smol

    machine = FakeMachine()
    deployment = SmolDeployment()
    monkeypatch.setattr(deployment, "_create_machine", lambda token: machine)
    monkeypatch.setattr(smol, "_SmolRemoteRuntime", FakeRuntime)

    async def ready(*args, **kwargs):
        return None

    monkeypatch.setattr(smol, "_wait_until_alive", ready)
    await deployment.start()
    started = asyncio.Event()

    async def slow_close():
        started.set()
        await asyncio.Event().wait()

    deployment.runtime.close = slow_close
    task = asyncio.create_task(deployment.stop())
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert machine.deleted
    with pytest.raises(DeploymentNotStartedError):
        _ = deployment.runtime
