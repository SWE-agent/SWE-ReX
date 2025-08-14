import pytest

from swerex.deployment import get_deployment
from swerex.deployment.config import (
    DaytonaDeploymentConfig,
    DockerDeploymentConfig,
    FargateDeploymentConfig,
    LocalDeploymentConfig,
    ModalDeploymentConfig,
    RemoteDeploymentConfig,
)
from swerex.deployment.daytona import DaytonaDeployment
from swerex.deployment.docker import DockerDeployment
from swerex.deployment.fargate import FargateDeployment
from swerex.deployment.local import LocalDeployment
from swerex.deployment.modal import ModalDeployment
from swerex.deployment.remote import RemoteDeployment


def test_get_local_deployment():
    deployment = get_deployment(LocalDeploymentConfig())
    assert isinstance(deployment, LocalDeployment)


def test_get_docker_deployment():
    deployment = get_deployment(DockerDeploymentConfig(image="test"))
    assert isinstance(deployment, DockerDeployment)


def test_get_modal_deployment():
    deployment = get_deployment(ModalDeploymentConfig(image="test"))
    assert isinstance(deployment, ModalDeployment)


def test_get_remote_deployment():
    deployment = get_deployment(RemoteDeploymentConfig(auth_token="test"))
    assert isinstance(deployment, RemoteDeployment)


def test_get_fargate_deployment():
    deployment = get_deployment(FargateDeploymentConfig(image="test"))
    assert isinstance(deployment, FargateDeployment)


def test_get_daytona_deployment():
    deployment = get_deployment(DaytonaDeploymentConfig(image="test"))
    assert isinstance(deployment, DaytonaDeployment)


if __name__ == "__main__":
    pytest.main()
