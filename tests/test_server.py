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
