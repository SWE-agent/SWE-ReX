from swerex.deployment.abstract import AbstractDeployment, DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.local import Runtime

__all__ = ["LocalDeployment"]


class LocalDeployment(AbstractDeployment):
    def __init__(
        self,
    ):
        self._runtime = None
        self._runtime_timeout = 0.15

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        if self._runtime is None:
            return IsAliveResponse(is_alive=False, message="Runtime is None.")
        return await self._runtime.is_alive(timeout=timeout)

    async def start(self):
        self._runtime = Runtime()

    async def stop(self):
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

    @property
    def runtime(self) -> Runtime:
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime
