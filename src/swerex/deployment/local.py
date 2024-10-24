from swerex.deployment.abstract import AbstractDeployment
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.local import Runtime
from swerex.utils.log import get_logger

__all__ = ["LocalDeployment"]


class LocalDeployment(AbstractDeployment):
    def __init__(
        self,
    ):
        """The most boring of the deployment classes.
        This class does nothing but wrap around `Runtime` so you can switch out
        your deployment method.
        """
        self._runtime = None
        self.logger = get_logger("deploy")  # type: ignore

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
            msg = "Runtime not started"
            raise RuntimeError(msg)
        return self._runtime
