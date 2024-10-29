import asyncio
from abc import ABC, abstractmethod

from swerex.runtime.abstract import AbstractRuntime, IsAliveResponse

__all__ = ["AbstractDeployment", "DeploymentNotStartedError"]


class AbstractDeployment(ABC):
    @abstractmethod
    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive. The return value can be
        tested with bool().

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """

    @abstractmethod
    async def start(self, *args, **kwargs):
        """Starts the runtime."""

    @abstractmethod
    async def stop(self, *args, **kwargs):
        """Stops the runtime."""

    @property
    @abstractmethod
    def runtime(self) -> AbstractRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """

    def __del__(self):
        """Stops the runtime when the object is deleted."""
        print("Stopping runtime because Deployment object is deleted")
        asyncio.run(self.stop())


class DeploymentNotStartedError(RuntimeError):
    def __init__(self, message="Deployment not started"):
        super().__init__(message)
