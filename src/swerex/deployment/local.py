from swerex.deployment.abstract import AbstractDeployment
from swerex.runtime.local import Runtime

__all__ = ["LocalDeployment"]


class LocalDeployment(AbstractDeployment):
    def __init__(
        self,
    ):
        self._runtime = None

    async def is_alive(self) -> bool:
        return self._runtime is not None

    async def start(self):
        self._runtime = Runtime()

    async def stop(self):
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

    @property
    def runtime(self) -> Runtime:
        if self._runtime is None:
            msg = "Runtime not started"
            raise RuntimeError(msg)
        return self._runtime
