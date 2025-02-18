import pytest

from swerex.deployment.docker import DockerDeployment
from swerex.utils.free_port import find_free_port


async def test_docker_deployment():
    port = find_free_port()
    print(f"Using port {port} for the docker deployment")
    d = DockerDeployment(image="swe-rex-test:latest", port=port)
    with pytest.raises(RuntimeError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    await d.stop()


async def test_docker_deployment_with_python_standalone():
    port = find_free_port()
    print(f"Using port {port} for the docker deployment")
    d = DockerDeployment(image="ubuntu:latest", port=port, python_standalone_dir="/root")
    with pytest.raises(RuntimeError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    await d.stop()
