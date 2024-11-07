from swerex.deployment.abstract import AbstractDeployment
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.dummy import DummyRuntime


class DummyDeployment(AbstractDeployment):
    """This deployment does nothing.
    Useful for testing.
    """

    def __init__(self):
        self._runtime = DummyRuntime()  # type: ignore

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        return IsAliveResponse(is_alive=True)

    async def start(self):
        pass

    async def stop(self):
        pass

    @property
    def runtime(self) -> DummyRuntime:
        return self._runtime

    @runtime.setter
    def runtime(self, runtime: DummyRuntime):
        self._runtime = runtime
