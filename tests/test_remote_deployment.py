import pytest

from swerex.deployment.remote import RemoteDeployment
from swerex.exceptions import DeploymentNotStartedError
from tests.conftest import TEST_API_KEY


async def test_remote_deployment(remote_server):
    port = remote_server.port
    print(f"Using port {port} for the remote deployment")
    d = RemoteDeployment(port=port, auth_token=TEST_API_KEY)
    with pytest.raises(DeploymentNotStartedError):
        await d.is_alive()
    await d.start()
    assert await d.is_alive()
    # `timeout` is part of the AbstractDeployment interface and every other
    # deployment accepts it; RemoteDeployment used to omit it, so callers
    # written against the interface hit a TypeError here.
    assert await d.is_alive(timeout=10)
    await d.stop()
