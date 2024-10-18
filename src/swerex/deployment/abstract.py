from abc import ABC, abstractmethod

from swerex.runtime.abstract import AbstractRuntime

__all__ = ["AbstractDeployment"]


class AbstractDeployment(ABC):
    @abstractmethod
    def is_alive(self) -> bool: ...

    @abstractmethod
    def start(self, *args, **kwargs): ...

    @abstractmethod
    def stop(self, *args, **kwargs): ...

    @property
    @abstractmethod
    def runtime(self) -> AbstractRuntime: ...
