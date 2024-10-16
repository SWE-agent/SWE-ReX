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

    time.sleep(0.1)

    return RemoteServer(port)


@pytest.fixture
def remote_runtime(remote_server: RemoteServer) -> RemoteRuntime:
    return RemoteRuntime(f"http://127.0.0.1:{remote_server.port}")
