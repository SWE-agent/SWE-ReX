import socket

import pytest

from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.wait import _wait_until_alive


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (IsAliveResponse(is_alive=False, message="Runtime connection refused"), "Runtime connection refused"),
        (False, "None"),
    ],
)
async def test_wait_until_alive_preserves_failure_message(response, message):
    async def health_check(*, timeout):
        return response

    with pytest.raises(TimeoutError, match=message):
        await _wait_until_alive(health_check, timeout=0.02, sleep=0.001)


async def test_wait_until_alive_returns_when_runtime_becomes_ready():
    responses = iter([IsAliveResponse(is_alive=False, message="Starting"), IsAliveResponse(is_alive=True)])

    async def health_check(*, timeout):
        return next(responses)

    await _wait_until_alive(health_check, timeout=1, sleep=0)


async def test_remote_runtime_wait_reports_connection_failure():
    with socket.socket() as unused_port:
        unused_port.bind(("127.0.0.1", 0))
        runtime = RemoteRuntime(host="http://127.0.0.1", port=unused_port.getsockname()[1], auth_token="")
        with pytest.raises(TimeoutError, match="Failed to connect to http://127.0.0.1"):
            await runtime.wait_until_alive(timeout=0.02)
