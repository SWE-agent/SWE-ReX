from pathlib import Path

import pytest

from swerex.deployment.modal import ModalDeployment


@pytest.mark.slow
async def test_modal_deployment():
    dockerfile = Path(__file__).parent / "swe_rex_test.Dockerfile"
    d = ModalDeployment(dockerfile=str(dockerfile), container_timeout=60)
    with pytest.raises(RuntimeError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    await d.stop()
