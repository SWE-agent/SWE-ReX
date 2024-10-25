import os

import pytest

from swerex.deployment.fargate import FargateDeployment


@pytest.mark.slow
@pytest.mark.skipif(os.getenv("GITHUB_ACTIONS") == "true", reason="Skipping modal tests in github actions")
async def test_fargate_deployment():
    d = FargateDeployment(
        image="public.ecr.aws/v0o5q4h6/test-namespace/test-repo-1:latest",
        port=8880,
        container_timeout=60 * 15,
    )
    with pytest.raises(RuntimeError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    await d.stop()


@pytest.mark.slow
@pytest.mark.skipif(os.getenv("GITHUB_ACTIONS") == "true", reason="Skipping modal tests in github actions")
async def test_fargate_deployment_ubuntu_base():
    d = FargateDeployment(
        image="ubuntu:24.04",
        port=8880,
        container_timeout=60 * 15,
    )
    with pytest.raises(RuntimeError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    await d.stop()
