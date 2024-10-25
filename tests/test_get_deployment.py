import pytest

from swerex.deployment import get_deployment
from swerex.deployment.docker import DockerDeployment
from swerex.deployment.fargate import FargateDeployment
from swerex.deployment.local import LocalDeployment
from swerex.deployment.modal import ModalDeployment
from swerex.deployment.remote import RemoteDeployment


def test_get_local_deployment():
    deployment = get_deployment("local")
    assert isinstance(deployment, LocalDeployment)


def test_get_docker_deployment():
    deployment = get_deployment("docker", image="test")
    assert isinstance(deployment, DockerDeployment)


def test_get_modal_deployment():
    deployment = get_deployment("modal", image="test")
    assert isinstance(deployment, ModalDeployment)


def test_get_deployment_invalid_type():
    with pytest.raises(ValueError, match="Unknown deployment type: invalid"):
        get_deployment("invalid")


def test_get_remote_deployment():
    deployment = get_deployment("remote")
    assert isinstance(deployment, RemoteDeployment)


def test_get_fargate_deployment():
    deployment = get_deployment("fargate", image="test")
    assert isinstance(deployment, FargateDeployment)


if __name__ == "__main__":
    pytest.main()
