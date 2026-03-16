import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swerex.deployment.cloudflare import CloudflareDeployment
from swerex.exceptions import DeploymentNotStartedError


def _make_async_cm(obj):
    """Wrap obj so it works as an async context manager returning itself."""
    obj.__aenter__ = AsyncMock(return_value=obj)
    obj.__aexit__ = AsyncMock(return_value=False)
    return obj


def _make_mock_session(post_status=200, post_json=None, delete_status=200):
    """Build a mock aiohttp.ClientSession context manager."""
    post_resp = AsyncMock()
    post_resp.status = post_status
    post_resp.json = AsyncMock(return_value=post_json or {"instance_id": "abc123"})
    post_resp.text = AsyncMock(return_value="error body")
    _make_async_cm(post_resp)

    delete_resp = AsyncMock()
    delete_resp.status = delete_status
    delete_resp.raise_for_status = MagicMock()
    _make_async_cm(delete_resp)

    # post/delete must be MagicMock (not AsyncMock) — they're used as `async with session.post(...)`
    # which means they must return an async context manager, not a coroutine.
    session = MagicMock()
    session.post.return_value = post_resp
    session.delete.return_value = delete_resp
    _make_async_cm(session)

    return session


async def test_not_started_raises():
    d = CloudflareDeployment(worker_url="https://fake.workers.dev")
    with pytest.raises(DeploymentNotStartedError):
        await d.is_alive()


async def test_runtime_property_raises_when_not_started():
    d = CloudflareDeployment(worker_url="https://fake.workers.dev")
    with pytest.raises(DeploymentNotStartedError):
        _ = d.runtime


async def test_management_headers_with_token():
    d = CloudflareDeployment(worker_url="https://fake.workers.dev", worker_api_token="mytoken")
    assert d._management_headers == {"Authorization": "Bearer mytoken"}


async def test_management_headers_without_token():
    d = CloudflareDeployment(worker_url="https://fake.workers.dev")
    assert d._management_headers == {}


async def test_start_sets_instance_id_and_runtime():
    d = CloudflareDeployment(worker_url="https://fake.workers.dev")
    session = _make_mock_session(post_json={"instance_id": "abc123"})

    with (
        patch("aiohttp.ClientSession", return_value=session),
        patch("swerex.deployment.cloudflare._wait_until_alive", new_callable=AsyncMock),
    ):
        await d.start()

    assert d._instance_id == "abc123"
    assert d._runtime is not None


async def test_start_uses_correct_worker_url():
    d = CloudflareDeployment(worker_url="https://fake.workers.dev", worker_api_token="tok")
    session = _make_mock_session()

    with (
        patch("aiohttp.ClientSession", return_value=session),
        patch("swerex.deployment.cloudflare._wait_until_alive", new_callable=AsyncMock),
    ):
        await d.start()

    call_args = session.post.call_args
    assert call_args[0][0] == "https://fake.workers.dev/start"
    assert call_args[1]["headers"] == {"Authorization": "Bearer tok"}


async def test_start_raises_on_worker_error():
    d = CloudflareDeployment(worker_url="https://fake.workers.dev")
    session = _make_mock_session(post_status=500)

    with patch("aiohttp.ClientSession", return_value=session):
        with pytest.raises(RuntimeError, match="CF Worker /start returned 500"):
            await d.start()


async def test_stop_calls_delete_endpoint():
    d = CloudflareDeployment(worker_url="https://fake.workers.dev")
    d._instance_id = "abc123"
    d._runtime = AsyncMock()
    d._runtime.close = AsyncMock()

    session = _make_mock_session()
    with patch("aiohttp.ClientSession", return_value=session):
        await d.stop()

    call_args = session.delete.call_args
    assert call_args[0][0] == "https://fake.workers.dev/stop/abc123"
    assert d._instance_id is None
    assert d._runtime is None


async def test_stop_is_idempotent():
    d = CloudflareDeployment(worker_url="https://fake.workers.dev")
    # stop before start should not raise
    await d.stop()
    await d.stop()


async def test_stop_continues_if_runtime_close_fails():
    d = CloudflareDeployment(worker_url="https://fake.workers.dev")
    d._instance_id = "abc123"
    d._runtime = AsyncMock()
    d._runtime.close = AsyncMock(side_effect=Exception("close failed"))

    session = _make_mock_session()
    with patch("aiohttp.ClientSession", return_value=session):
        await d.stop()  # should not raise

    assert d._instance_id is None


# --- Integration tests (require a live CF worker) ---


@pytest.mark.cloud
@pytest.mark.slow
@pytest.mark.skipif(not os.getenv("CF_WORKER_URL"), reason="CF_WORKER_URL not set")
async def test_cloudflare_deployment_full():
    d = CloudflareDeployment(
        worker_url=os.environ["CF_WORKER_URL"],
        worker_api_token=os.getenv("CF_WORKER_API_TOKEN", ""),
        startup_timeout=120,
    )
    with pytest.raises(DeploymentNotStartedError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    await d.stop()
