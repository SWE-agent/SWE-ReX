import pytest

from swerex.deployment.abstract import DeploymentNotStartedError
from swerex.deployment.remote import RemoteDeployment
from tests.conftest import TEST_API_KEY


async def test_remote_deployment(remote_server):
    port = remote_server.port
    print(f"Using port {port} for the remote deployment")
    d = RemoteDeployment(port=port, auth_token=TEST_API_KEY)
    with pytest.raises(DeploymentNotStartedError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    await d.stop()
