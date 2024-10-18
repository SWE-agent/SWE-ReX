from abc import ABC, abstractmethod

from swerex.runtime.abstract import AbstractRuntime

__all__ = ["AbstractDeployment"]


class AbstractDeployment(ABC):
    @abstractmethod
    async def is_alive(self) -> bool: ...

    @abstractmethod
    async def start(self, *args, **kwargs): ...

    @abstractmethod
    async def stop(self, *args, **kwargs): ...

    @property
    @abstractmethod
    def runtime(self) -> AbstractRuntime: ...
