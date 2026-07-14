import os

import pytest

from swerex.deployment.tenki import TenkiDeployment
from swerex.runtime.abstract import Command


@pytest.mark.cloud
@pytest.mark.slow
@pytest.mark.skipif(
    not (os.getenv("TENKI_AUTH_TOKEN") or os.getenv("TENKI_API_KEY")),
    reason="Tenki credentials not set (TENKI_AUTH_TOKEN or TENKI_API_KEY)",
)
async def test_tenki_deployment():
    d = TenkiDeployment(startup_timeout=60 * 10)
    with pytest.raises(RuntimeError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    response = await d.runtime.execute(Command(command="echo 'hello world'", shell=True))
    assert response.exit_code == 0
    assert "hello world" in response.stdout
    await d.stop()
