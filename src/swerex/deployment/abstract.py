import asyncio
import logging
from abc import ABC, abstractmethod

from swerex.deployment.hooks.abstract import DeploymentHook
from swerex.runtime.abstract import AbstractRuntime, IsAliveResponse

__all__ = ["AbstractDeployment"]


class AbstractDeployment(ABC):
    def __init__(self, *args, **kwargs):
        self.logger: logging.Logger

    @abstractmethod
    def add_hook(self, hook: DeploymentHook): ...

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
        # Need to be check whether we are in an async event loop or not
        # https://stackoverflow.com/questions/54770360/
        msg = "Ensuring deployment is stopped because object is deleted"
        try:
            self.logger.debug(msg)
        except Exception:
            print(msg)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.stop())
            else:
                loop.run_until_complete(self.stop())
        except Exception:
            pass
