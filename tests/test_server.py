import requests

from tests.conftest import RemoteServer


def test_is_alive(remote_server: RemoteServer):
    assert requests.get(f"http://127.0.0.1:{remote_server.port}/is_alive").json()["is_alive"]


def test_hello_world(remote_server: RemoteServer):
    assert requests.get(f"http://127.0.0.1:{remote_server.port}/").json()["message"] == "hello world"
