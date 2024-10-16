import socket
import threading
import time
from dataclasses import dataclass

import pytest

from swebridge.local import RemoteRuntime
from swebridge.remote import app


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
def remote_runtime(remote_server: RemoteServer) -> RemoteRuntime:
    return RemoteRuntime(f"http://127.0.0.1:{remote_server.port}")
