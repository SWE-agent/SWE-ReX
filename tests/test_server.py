import time

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


def test_duplicate_request_id_while_in_flight_is_not_executed_twice(remote_server: RemoteServer):
    """A retry that arrives before the original finishes must wait for it.

    The client retries transport-level failures reusing the same X-Request-ID.
    The response cache alone only covers requests that already *finished*; a
    retry sent while the original is still running used to slip past it and
    execute the action a second time. `$RANDOM` makes that observable without
    depending on timing: one execution means both callers see the same value.
    """
    import concurrent.futures
    import uuid

    request_id = str(uuid.uuid4())
    payload = {"command": "sleep 2; echo $RANDOM", "shell": True}
    headers = {**remote_server.headers, "X-Request-ID": request_id}
    url = f"http://127.0.0.1:{remote_server.port}/execute"

    def post():
        return requests.post(url, json=payload, headers=headers, timeout=30)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post)
        time.sleep(0.5)  # ensure the second lands while the first is still running
        second = pool.submit(post)
        r1, r2 = first.result(), second.result()

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["stdout"] == r2.json()["stdout"]


def test_duplicate_request_id_after_completion_is_served_from_cache(remote_server: RemoteServer):
    import uuid

    request_id = str(uuid.uuid4())
    payload = {"command": "echo $RANDOM", "shell": True}
    headers = {**remote_server.headers, "X-Request-ID": request_id}
    url = f"http://127.0.0.1:{remote_server.port}/execute"

    r1 = requests.post(url, json=payload, headers=headers, timeout=30)
    r2 = requests.post(url, json=payload, headers=headers, timeout=30)
    assert r1.json()["stdout"] == r2.json()["stdout"]


def test_concurrent_distinct_request_ids_do_not_clobber_each_other(remote_server: RemoteServer):
    """Two different requests in flight at once must each be tracked.

    A single in-flight slot would let the second overwrite the first, so the
    first's waiter is never woken and blocks until its own client timeout.
    """
    import concurrent.futures
    import uuid

    url = f"http://127.0.0.1:{remote_server.port}/execute"

    def post(rid, cmd):
        return requests.post(url, json={"command": cmd, "shell": True},
                             headers={**remote_server.headers, "X-Request-ID": rid},
                             timeout=30)

    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        fa = pool.submit(post, a, "sleep 2; echo $RANDOM")
        time.sleep(0.3)
        fb = pool.submit(post, b, "echo other")
        time.sleep(0.3)
        fa_retry = pool.submit(post, a, "sleep 2; echo $RANDOM")   # retry of A
        ra, rb, ra2 = fa.result(), fb.result(), fa_retry.result()

    assert rb.json()["stdout"].strip() == "other"
    # The retry of A must still be matched to A, not lost because B arrived.
    assert ra.json()["stdout"] == ra2.json()["stdout"]
