from swerex.deployment.local import LocalDeployment


async def test_local_deployment():
    d = LocalDeployment()
    assert not await d.is_alive()
    await d.start()
    assert await d.is_alive()
    await d.stop()
    assert not await d.is_alive()
