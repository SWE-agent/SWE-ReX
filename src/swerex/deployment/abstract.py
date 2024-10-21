from abc import ABC, abstractmethod

from swerex.runtime.abstract import AbstractRuntime, IsAliveResponse

__all__ = ["AbstractDeployment"]


class AbstractDeployment(ABC):
    @abstractmethod
    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive. The return value can be
        tested with bool().
        """

    @abstractmethod
    async def start(self, *args, **kwargs): ...

    @abstractmethod
    async def stop(self, *args, **kwargs): ...

    @property
    @abstractmethod
    def runtime(self) -> AbstractRuntime: ...
