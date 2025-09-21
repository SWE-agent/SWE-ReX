import pytest

from swerex.deployment.vefaas import VeFaasDeployment


async def test_faas_deployment():
    f = VeFaasDeployment(
        image="enterprise-public-cn-beijing.cr.volces.com/swe-bench/sweb.eval.x86_64.django_1776_django-15414:latest",
        ak="",
        sk="",
        region="cn-beijing",
        function_id="awokjltn",
        apigateway_service_id="sd2on64i5ni4n75n9unpg",
    )
    with pytest.raises(RuntimeError):
        await f.is_alive()
    await f.start()
    assert await f.is_alive()
    await f.stop()
