import asyncio

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


async def test_docker_deployment_parallel():
    """Deployments started concurrently must not deadlock or time out each other."""
    deployments = [DockerDeployment(image="swe-rex-test:latest") for _ in range(3)]
    try:
        await asyncio.gather(*(d.start() for d in deployments))
        for d in deployments:
            assert await d.is_alive()
    finally:
        await asyncio.gather(*(d.stop() for d in deployments), return_exceptions=True)


async def test_docker_deployment_startup_timeout():
    """A startup timeout must raise while the container is still running.

    Reading the container's output from a pipe blocks until the container exits, so the
    timeout handler used to hang instead of reporting the timeout.
    """
    # delay swerex past the startup timeout, then hand over to the start command in $0
    slow_shell = ["/bin/sh", "-c", 'sleep 60; exec /bin/sh -c "$0"']
    d = DockerDeployment(image="swe-rex-test:latest", exec_shell=slow_shell, startup_timeout=5)
    with pytest.raises(TimeoutError):
        await d.start()


@pytest.mark.slow
async def test_docker_deployment_with_python_standalone():
    port = find_free_port()
    print(f"Using port {port} for the docker deployment")
    d = DockerDeployment(image="ubuntu:latest", port=port, python_standalone_dir="/root")
    with pytest.raises(RuntimeError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    await d.stop()


@pytest.mark.slow
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


def test_docker_deployment_config_container_runtime():
    # Test default container runtime is docker
    config = DockerDeploymentConfig(image="test")
    assert config.container_runtime == "docker"

    # Test setting container runtime to podman
    config = DockerDeploymentConfig(image="test", container_runtime="podman")
    assert config.container_runtime == "podman"


async def test_podman_deployment():
    """Test deployment with Podman container runtime"""
    port = find_free_port()
    print(f"Using port {port} for the podman deployment")
    d = DockerDeployment(image="swe-rex-test:latest", port=port, container_runtime="podman")
    assert d._config.container_runtime == "podman"
    # Note: This test will only pass if podman is installed and the test image exists
    # In CI/CD environments without podman, this test may be skipped


def test_podman_deployment_config():
    """Test that DockerDeployment works with podman configuration"""
    config = DockerDeploymentConfig(image="test:latest", container_runtime="podman", port=8080, pull="never")
    deployment = DockerDeployment.from_config(config)
    assert deployment._config.container_runtime == "podman"
    assert deployment._config.image == "test:latest"
    assert deployment._config.port == 8080


def test_docker_deployment_config_container_runtime():
    # Test default container runtime is docker
    config = DockerDeploymentConfig(image="test")
    assert config.container_runtime == "docker"

    # Test setting container runtime to podman
    config = DockerDeploymentConfig(image="test", container_runtime="podman")
    assert config.container_runtime == "podman"


async def test_podman_deployment():
    """Test deployment with Podman container runtime"""
    port = find_free_port()
    print(f"Using port {port} for the podman deployment")
    d = DockerDeployment(image="swe-rex-test:latest", port=port, container_runtime="podman")
    assert d._config.container_runtime == "podman"
    # Note: This test will only pass if podman is installed and the test image exists
    # In CI/CD environments without podman, this test may be skipped


def test_podman_deployment_config():
    """Test that DockerDeployment works with podman configuration"""
    config = DockerDeploymentConfig(image="test:latest", container_runtime="podman", port=8080, pull="never")
    deployment = DockerDeployment.from_config(config)
    assert deployment._config.container_runtime == "podman"
    assert deployment._config.image == "test:latest"
    assert deployment._config.port == 8080
