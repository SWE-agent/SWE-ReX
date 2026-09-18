import json
import subprocess

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


def test_docker_deployment_config_defaults_to_loopback():
    assert DockerDeploymentConfig().port_bind_host == "127.0.0.1"


@pytest.mark.slow
def test_private_networks_block_peer_container_access():
    deployments = [DockerDeployment(image="python:3.12-slim", pull="never") for _ in range(2)]
    containers = []
    try:
        for deployment in deployments:
            network_args = deployment._get_network_args()
            container = subprocess.run(
                ["docker", "run", "-d", "--rm", *network_args, "python:3.12-slim", "sleep", "60"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            containers.append(container)
        info = json.loads(
            subprocess.run(["docker", "inspect", *containers], capture_output=True, text=True, check=True).stdout
        )
        assert {deployment._network_name for deployment in deployments} == {
            next(iter(item["NetworkSettings"]["Networks"])) for item in info
        }
        networks = json.loads(
            subprocess.run(
                ["docker", "network", "inspect", *(deployment._network_name for deployment in deployments)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        assert all(not network["Internal"] for network in networks)
        first_ip = next(iter(info[0]["NetworkSettings"]["Networks"].values()))["IPAddress"]
        subprocess.run(
            [
                "docker",
                "exec",
                containers[0],
                "sh",
                "-c",
                "echo private >/tmp/marker; python -m http.server 18080 --directory /tmp >/tmp/http.log 2>&1 &",
            ],
            check=True,
        )
        probe = subprocess.run(
            [
                "docker",
                "exec",
                containers[1],
                "python",
                "-c",
                f"import socket; socket.create_connection(('{first_ip}',18080),timeout=2)",
            ]
        )
        assert probe.returncode != 0
    finally:
        for container in containers:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        for deployment in deployments:
            if deployment._network_name:
                subprocess.run(["docker", "network", "rm", deployment._network_name], capture_output=True)
                deployment._network_name = None


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
