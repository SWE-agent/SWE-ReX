from pathlib import Path
from unittest.mock import patch

import modal
import pytest

from swerex.deployment import get_deployment
from swerex.deployment.config import ModalDeploymentConfig
from swerex.deployment.modal import ModalDeployment, _ImageBuilder


@pytest.mark.parametrize("app_kwargs", [{}, {"app_name": "my-agent"}])
@pytest.mark.parametrize("from_config", [False, True])
def test_modal_app_name(app_kwargs: dict[str, str], from_config: bool):
    app = modal.App("test")
    with patch.object(modal.App, "lookup", return_value=app) as lookup:
        if from_config:
            config = ModalDeploymentConfig(image="python:3.11-slim", **app_kwargs)
            config = ModalDeploymentConfig.model_validate_json(config.model_dump_json())
            deployment = get_deployment(config)
        else:
            deployment = ModalDeployment(image="python:3.11-slim", **app_kwargs)

    lookup.assert_called_once_with(app_kwargs.get("app_name", "swe-rex"), create_if_missing=True)
    assert deployment.app is app


@pytest.mark.cloud
@pytest.mark.slow
async def test_modal_deployment_from_docker_with_swerex_installed():
    dockerfile = Path(__file__).parent / "swe_rex_test.Dockerfile"
    image = _ImageBuilder().from_file(dockerfile, build_context=Path(__file__).resolve().parent.parent)
    d = ModalDeployment(image=image, startup_timeout=60 * 5)
    with pytest.raises(RuntimeError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    await d.stop()


@pytest.mark.cloud
@pytest.mark.slow
async def test_modal_deployment_from_docker_string():
    d = ModalDeployment(image="python:3.11-slim", startup_timeout=60)
    await d.start()
    assert await d.is_alive()
    await d.stop()
