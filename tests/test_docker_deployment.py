import pytest

from swerex.deployment.config import DockerDeploymentConfig
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


def test_docker_deployment_config_platform():
    config = DockerDeploymentConfig(docker_args=["--platform", "linux/amd64", "--other-arg"])
    assert config.platform == "linux/amd64"

    config = DockerDeploymentConfig(docker_args=["--platform=linux/amd64", "--other-arg"])
    assert config.platform == "linux/amd64"

    config = DockerDeploymentConfig(docker_args=["--other-arg"])
    assert config.platform is None

    with pytest.raises(ValueError):
        config = DockerDeploymentConfig(platform="linux/amd64", docker_args=["--platform", "linux/amd64"])
    with pytest.raises(ValueError):
        config = DockerDeploymentConfig(platform="linux/amd64", docker_args=["--platform=linux/amd64"])
