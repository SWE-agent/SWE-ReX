from swerex.deployment.local import LocalDeployment


def test_local_deployment():
    d = LocalDeployment()
    assert not d.is_alive()
    d.start()
    assert d.is_alive()
    d.stop()
    assert not d.is_alive()
