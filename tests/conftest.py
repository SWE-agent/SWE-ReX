import socket
import threading
import time
from dataclasses import dataclass, field

import pytest
import uvicorn

import swerex.server
from swerex.runtime.abstract import (
    BashAction,
    Command,
    CreateBashSessionRequest,
)
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.free_port import find_free_port

TEST_API_KEY = "testkey"


@dataclass
class RemoteServer:
    port: int
    headers: dict[str, str] = field(default_factory=lambda: {"X-API-Key": TEST_API_KEY})


@pytest.fixture(scope="session")
def remote_server() -> RemoteServer:
    port = find_free_port()
    print(f"Using port {port} for the remote server")

    def run_server():
        swerex.server.AUTH_TOKEN = TEST_API_KEY
        uvicorn.run(swerex.server.app, host="127.0.0.1", port=port, log_level="error")

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
async def remote_runtime(remote_server: RemoteServer):
    """Async fixture for RemoteRuntime that properly handles cleanup."""
    r = RemoteRuntime(port=remote_server.port, auth_token=TEST_API_KEY)
    try:
        yield r
    finally:
        await r.close()


@pytest.fixture
async def runtime_with_default_session(remote_runtime: RemoteRuntime):
    """Async fixture that creates a default session and cleans it up properly."""
    await remote_runtime.create_session(CreateBashSessionRequest())
    try:
        yield remote_runtime
    finally:
        await remote_runtime.close()


class _Action(BashAction):
    timeout: float | None = 5


class _Command(Command):
    timeout: float | None = 5
