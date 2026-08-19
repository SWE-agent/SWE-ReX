import logging
from typing import Any

from typing_extensions import Self

from swerex.deployment.abstract import AbstractDeployment
from swerex.deployment.config import RemoteDeploymentConfig
from swerex.deployment.hooks.abstract import CombinedDeploymentHook, DeploymentHook
from swerex.exceptions import DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.log import get_logger


class RemoteDeployment(AbstractDeployment):
    def __init__(self, *, logger: logging.Logger | None = None, **kwargs: Any):
        """This deployment is only a thin wrapper around the `RemoteRuntime`.
        Use this if you have deployed a runtime somewhere else but want to interact with it
        through the `AbstractDeployment` interface.
        For example, if you have an agent that you usually use with a `DocerkDeployment` interface,
        you sometimes might want to manually start a docker container for debugging purposes.
        Then you can use this deployment to explicitly connect to your manually started runtime.

        Args:
            **kwargs: Keyword arguments (see `RemoteDeploymentConfig` for details).
        """
        self._config = RemoteDeploymentConfig(**kwargs)
        self._runtime: RemoteRuntime | None = None
        self.logger = logger or get_logger("rex-deploy")
        self._hooks = CombinedDeploymentHook()

    def add_hook(self, hook: DeploymentHook):
        self._hooks.add_hook(hook)

    @classmethod
    def from_config(cls, config: RemoteDeploymentConfig) -> Self:
        return cls(**config.model_dump())

    @property
    def runtime(self) -> RemoteRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive. The return value can be
        tested with bool().

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        return await self.runtime.is_alive(timeout=timeout)

    async def start(self):
        """Starts the runtime."""
        self.logger.info("Starting remote runtime")
        self._runtime = RemoteRuntime(
            auth_token=self._config.auth_token,
            host=self._config.host,
            port=self._config.port,
            timeout=self._config.timeout,
            logger=self.logger,
        )

    async def stop(self):
        """Stops the runtime."""
        await self.runtime.close()
        self._runtime = None
