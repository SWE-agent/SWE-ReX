import concurrent.futures
import uuid

import requests

from tests.conftest import RemoteServer

headers = {"X-API-Key": "your_secret_api_key_here"}


def test_is_alive(remote_server: RemoteServer):
    response = requests.get(f"http://127.0.0.1:{remote_server.port}/is_alive", headers=remote_server.headers)
    print(response.json())
    assert response.json()["is_alive"]


def test_hello_world(remote_server: RemoteServer):
    assert (
        requests.get(f"http://127.0.0.1:{remote_server.port}/", headers=remote_server.headers).json()["message"]
        == "hello world"
    )


def test_unauthenticated_request(remote_server: RemoteServer):
    for endpoint in [
        "/is_alive",
        "/",
        "/create_session",
        "/run_in_session",
        "/close_session",
        "/execute",
        "/read_file",
        "/write_file",
        "/upload",
        "/close",
    ]:
        response = requests.get(f"http://127.0.0.1:{remote_server.port}/{endpoint}")
        assert response.status_code == 403


def _execute_marker_command(remote_server: RemoteServer, marker_file, request_id: str, sleep: float = 0.0):
    """POST /execute a command that appends a line to `marker_file`."""
    command = f"sleep {sleep}; echo executed >> {marker_file}"
    return requests.post(
        f"http://127.0.0.1:{remote_server.port}/execute",
        json={"command": command, "shell": True},
        headers={**remote_server.headers, "X-Request-ID": request_id},
    )


def _marker_count(marker_file) -> int:
    if not marker_file.exists():
        return 0
    return len(marker_file.read_text().splitlines())


def test_request_id_replay_executes_once(remote_server: RemoteServer, tmp_path):
    """A retried (sequential) request with the same X-Request-ID is served from cache."""
    marker_file = tmp_path / "marker.txt"
    request_id = str(uuid.uuid4())
    first = _execute_marker_command(remote_server, marker_file, request_id)
    second = _execute_marker_command(remote_server, marker_file, request_id)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert _marker_count(marker_file) == 1


def test_request_id_concurrent_duplicates_execute_once(remote_server: RemoteServer, tmp_path):
    """A duplicate arriving while the original is still executing waits for it
    instead of executing the request a second time."""
    marker_file = tmp_path / "marker.txt"
    request_id = str(uuid.uuid4())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_execute_marker_command, remote_server, marker_file, request_id, 1.0) for _ in range(2)]
        responses = [f.result() for f in futures]
    assert all(r.status_code == 200 for r in responses)
    assert responses[0].json() == responses[1].json()
    assert _marker_count(marker_file) == 1


def test_request_id_survives_interleaved_requests(remote_server: RemoteServer, tmp_path):
    """Requests with other IDs must not evict a cached response (no single-slot cache)."""
    marker_file = tmp_path / "marker.txt"
    request_id = str(uuid.uuid4())
    _execute_marker_command(remote_server, marker_file, request_id)
    for _ in range(5):
        other_file = tmp_path / "other.txt"
        _execute_marker_command(remote_server, other_file, str(uuid.uuid4()))
    replay = _execute_marker_command(remote_server, marker_file, request_id)
    assert replay.status_code == 200
    assert _marker_count(marker_file) == 1
