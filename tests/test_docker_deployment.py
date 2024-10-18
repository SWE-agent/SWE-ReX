import time

from swerex.deployment.docker import DockerDeployment


def test_docker_deployment():
    d = DockerDeployment("swe-rex-test:latest", port=8000)
    assert not d.is_alive()
    d.start()
    time.sleep(2)
    assert d.is_alive()
    d.stop()
    assert not d.is_alive()
