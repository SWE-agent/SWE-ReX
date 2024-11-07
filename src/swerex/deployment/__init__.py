from typing import Literal

from swerex.deployment.abstract import AbstractDeployment


def get_deployment(
    deployment_type: Literal["local", "docker", "modal", "fargate", "remote"], **kwargs
) -> AbstractDeployment:
    if deployment_type == "dummy":
        from swerex.deployment.dummy import DummyDeployment

        return DummyDeployment(**kwargs)
    if deployment_type == "local":
        from swerex.deployment.local import LocalDeployment

        return LocalDeployment(**kwargs)
    if deployment_type == "docker":
        from swerex.deployment.docker import DockerDeployment

        return DockerDeployment(**kwargs)
    if deployment_type == "modal":
        from swerex.deployment.modal import ModalDeployment

        return ModalDeployment(**kwargs)
    if deployment_type == "fargate":
        from swerex.deployment.fargate import FargateDeployment

        return FargateDeployment(**kwargs)
    if deployment_type == "remote":
        from swerex.deployment.remote import RemoteDeployment

        return RemoteDeployment(**kwargs)
    msg = f"Unknown deployment type: {deployment_type}"
    raise ValueError(msg)
