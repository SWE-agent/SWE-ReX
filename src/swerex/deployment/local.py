import asyncio

from swerex.deployment.abstract import AbstractDeployment
from swerex.runtime.local import Runtime


class LocalDeployment(AbstractDeployment):
    def __init__(
        self,
    ):
        self._runtime = None

    def is_alive(self) -> bool:
        return self._runtime is not None

    def start(self):
        self._runtime = Runtime()

    def stop(self):
        if self._runtime is not None:
            asyncio.run(self._runtime.close())
            self._runtime = None

    @property
    def runtime(self) -> Runtime:
        if self._runtime is None:
            msg = "Runtime not started"
            raise RuntimeError(msg)
        return self._runtime
