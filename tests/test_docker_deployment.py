import shlex
import subprocess
import sys
from pathlib import Path

import pytest

import swerex
from swerex.deployment.config import DockerDeploymentConfig
from swerex.deployment.docker import DockerDeployment
from swerex.utils.free_port import find_free_port


def test_swerex_start_cmd_fallback_order():
    d = DockerDeployment(image="test", exec_shell=["/bin/sh", "-c"])
    assert d._get_swerex_start_cmd("TOKEN") == [
        "/bin/sh",
        "-c",
        "swerex-remote --auth-token TOKEN"
        " || (python3 -m pip install pipx && python3 -m pipx ensurepath"
        " && python3 -m pipx run --spec swe-rex swerex-remote --auth-token TOKEN)"
        " || (python3 -m pip install --target /tmp/swerex-pip swe-rex"
        " && python3 -c \"import sys; sys.path[:1] = ['/tmp/swerex-pip']; from swerex.server import main; main()\""
        " --auth-token TOKEN)",
    ]


@pytest.mark.parametrize(
    ("failing", "last_step"),
    [
        pytest.param("", "-m pipx run", id="pipx-works"),
        pytest.param("install pipx", "-c", id="pipx-cannot-be-installed"),
        pytest.param("ensurepath", "-c", id="ensurepath-fails"),
        pytest.param("pipx run", "-c", id="pipx-run-fails"),
    ],
)
def test_swerex_start_cmd_falls_through(tmp_path: Path, failing: str, last_step: str):
    """Runs the generated command with a stub `python3`, as there's no `swerex-remote` on the PATH."""
    log = tmp_path / "log"
    stub = tmp_path / "python3"
    stub.write_text(f"""#!/bin/sh
echo "$*" >> "{log}"
case "$*" in
*"{failing or "NOTHING FAILS"}"*) exit 1 ;;
esac
exit 0
""")
    stub.chmod(0o755)
    d = DockerDeployment(image="test", exec_shell=["/bin/sh", "-c"])
    result = subprocess.run(d._get_swerex_start_cmd("TOKEN"), env={"PATH": str(tmp_path)}, capture_output=True)
    assert result.returncode == 0
    steps = log.read_text().splitlines()
    assert steps[-1].startswith(last_step)
    assert steps[-1].endswith("--auth-token TOKEN")


def test_swerex_start_cmd_last_fallback_ignores_packages_in_working_directory(tmp_path: Path):
    """The working directory might hold a project with packages named like the server's dependencies."""
    (tmp_path / "pydantic").mkdir()
    (tmp_path / "pydantic" / "__init__.py").write_text("raise RuntimeError('shadowed')")
    d = DockerDeployment(image="test", exec_shell=["/bin/sh", "-c"])
    cmd = d._get_swerex_start_cmd("TOKEN")[-1]
    code = shlex.split(cmd.rsplit("||", 1)[1].partition("python3 -c ")[2])[0]
    code = code.replace("/tmp/swerex-pip", str(Path(swerex.__file__).parent.parent))
    result = subprocess.run([sys.executable, "-c", code, "--version"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert swerex.__version__ in result.stdout


def test_swerex_start_cmd_python_standalone_has_no_fallback():
    d = DockerDeployment(image="test", exec_shell=["/bin/sh", "-c"], python_standalone_dir="/root")
    assert d._get_swerex_start_cmd("TOKEN") == [
        "/bin/sh",
        "-c",
        "/root/python3.11/bin/swerex-remote --auth-token TOKEN",
    ]


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
