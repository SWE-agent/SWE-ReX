import logging
import uuid
from typing import Any

import aiohttp

from swerex.deployment.abstract import AbstractDeployment
from swerex.deployment.config import CloudflareDeploymentConfig
from swerex.deployment.hooks.abstract import CombinedDeploymentHook, DeploymentHook
from swerex.exceptions import DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive

__all__ = ["CloudflareDeployment"]


class CloudflareDeployment(AbstractDeployment):
    """Cloudflare deployment using Cloudflare Containers
    Requires a Cloudflare Worker to be deployed first.
    The worker manages container lifecycle via Durable Objects.
    """

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ):
        self._config = CloudflareDeploymentConfig(**kwargs)
        self._runtime: RemoteRuntime | None = None
        self._instance_id: str | None = None
        self.logger = logger or get_logger("rex-deploy")
        self._hooks = CombinedDeploymentHook()

    @classmethod
    def from_config(cls, config: CloudflareDeploymentConfig):
        return cls(**config.model_dump())

    def add_hook(self, hook: DeploymentHook):
        pass

    async def start(self):
        """Start a new container instance via the CF Worker and connect RemoteRuntime to it."""
        auth_token = str(uuid.uuid4())
        self._hooks.on_custom_step("Starting CF container")
        self.logger.info(f"Starting CF container via {self._config.worker_url}")
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._config.worker_url}/start",
                json={"auth_token": auth_token},
                headers=self._management_headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise RuntimeError(f"CF Worker /start returned {resp.status}: {body}")
                data = await resp.json()
                self._instance_id = data["instance_id"]

        self.logger.info(f"Container instance created: {self._instance_id}")

        # RemoteRuntime connects to the Worker URL prefixed with the instance ID.
        # The Worker proxies /{instance_id}/... to the container via the DO.
        proxy_url = f"{self._config.worker_url}/{self._instance_id}"
        self._runtime = RemoteRuntime(
            host=proxy_url,
            port=None,
            auth_token=auth_token,
            timeout=self._config.runtime_timeout,
        )

        self._hooks.on_custom_step("Waiting for runtime")
        self.logger.info(f"Waiting for runtime at {proxy_url}")
        await _wait_until_alive(
            self._runtime.is_alive,
            timeout=self._config.startup_timeout,
            function_timeout=self._config.runtime_timeout,
        )
        self.logger.info("CF container runtime is ready")

    async def stop(self):
        """Close the runtime and stop the container instance."""
        if self._runtime is not None:
            try:
                await self._runtime.close()
            except Exception:
                self.logger.warning("Failed to close runtime gracefully", exc_info=True)
            self._runtime = None

        if self._instance_id is not None:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.delete(
                        f"{self._config.worker_url}/stop/{self._instance_id}",
                        headers=self._management_headers,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        resp.raise_for_status()
            except Exception:
                self.logger.warning(
                    f"Failed to stop container {self._instance_id}",
                    exc_info=True,
                )
            self._instance_id = None

    @property
    def runtime(self) -> RemoteRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime

    @property
    def _management_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._config.worker_api_token:
            headers["Authorization"] = f"Bearer {self._config.worker_api_token}"
        return headers

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return await self._runtime.is_alive(timeout=timeout)
