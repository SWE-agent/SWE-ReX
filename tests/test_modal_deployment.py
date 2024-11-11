from pathlib import Path

import pytest

from swerex.deployment.modal import ModalDeployment, _ImageBuilder


@pytest.mark.slow
async def test_modal_deployment_from_docker_with_swerex_installed():
    dockerfile = Path(__file__).parent / "swe_rex_test.Dockerfile"
    image = _ImageBuilder().from_file(dockerfile, build_context=Path(__file__).resolve().parent.parent)
    d = ModalDeployment(image=image, startup_timeout=60)
    with pytest.raises(RuntimeError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    await d.stop()


@pytest.mark.slow
async def test_modal_deployment_from_docker_string():
    d = ModalDeployment(image="python:3.11-slim", startup_timeout=60)
    await d.start()
    assert await d.is_alive()
    await d.stop()
