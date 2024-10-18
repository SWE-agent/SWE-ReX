import time

from swerex.deployment.docker import DockerDeployment


async def test_docker_deployment():
    d = DockerDeployment("swe-rex-test:latest", port=8000)
    assert not await d.is_alive()
    await d.start()
    time.sleep(2)
    assert await d.is_alive()
    await d.stop()
    assert not await d.is_alive()
