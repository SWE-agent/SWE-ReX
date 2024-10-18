import socket
import threading
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest

from swerex.runtime.abstract import Action, CloseSessionRequest, Command, CreateSessionRequest
from swerex.runtime.remote import RemoteRuntime
from swerex.server import app


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@dataclass
class RemoteServer:
    port: int


@pytest.fixture(scope="session")
def remote_server() -> RemoteServer:
    port = find_free_port()

    def run_server():
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    # Wait for the server to start
    max_retries = 10
    retry_delay = 0.1
    for _ in range(max_retries):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except (ConnectionRefusedError, socket.timeout):
            time.sleep(retry_delay)
    else:
        pytest.fail("Server did not start within the expected time")

    return RemoteServer(port)


@pytest.fixture
async def remote_runtime(remote_server: RemoteServer) -> AsyncGenerator[RemoteRuntime, None]:
    r = RemoteRuntime(f"http://127.0.0.1:{remote_server.port}")
    yield r
    await r.close_session(CloseSessionRequest())


@pytest.fixture
async def runtime_with_default_session(remote_runtime: RemoteRuntime) -> AsyncGenerator[RemoteRuntime, None]:
    r = await remote_runtime.create_session(CreateSessionRequest())
    assert r.success
    yield remote_runtime
    r = await remote_runtime.close_session(CloseSessionRequest())
    assert r.success


class _Action(Action):
    timeout: float | None = 5


class _Command(Command):
    timeout: float | None = 5
