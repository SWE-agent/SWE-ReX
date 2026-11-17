import logging
import time
import uuid
from datetime import timedelta
from typing import Any

from typing_extensions import Self

from swerex import PACKAGE_NAME, REMOTE_EXECUTABLE_NAME
from swerex.deployment.abstract import AbstractDeployment
from swerex.deployment.config import OpenSandboxDeploymentConfig
from swerex.deployment.hooks.abstract import CombinedDeploymentHook, DeploymentHook
from swerex.exceptions import DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive

__all__ = ["OpenSandboxDeployment"]

# Sandbox states from which the swerex server can still become reachable.
_RECOVERABLE_STATES = frozenset({"Pending", "Running"})


class OpenSandboxDeployment(AbstractDeployment):
    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ):
        """Deployment for OpenSandbox (https://github.com/opensandbox-group/OpenSandbox).
        The deployment will only start when the `start` method is being called.

        Args:
            logger: The logger to use for the deployment.
            **kwargs: Keyword arguments to pass to the `OpenSandboxDeploymentConfig` constructor.
        """
        self._config = OpenSandboxDeploymentConfig(**kwargs)
        self._runtime: RemoteRuntime | None = None
        self._sandbox = None
        self._sandbox_id: str | None = None
        self.logger = logger or get_logger("rex-deploy")
        self._hooks = CombinedDeploymentHook()
        self._auth_token: str | None = None

    def add_hook(self, hook: DeploymentHook):
        self._hooks.add_hook(hook)

    @classmethod
    def from_config(cls, config: OpenSandboxDeploymentConfig) -> Self:
        return cls(**config.model_dump())

    def _get_token(self) -> str:
        """Generate a unique authentication token."""
        return str(uuid.uuid4())

    def _get_start_command(self, *, token: str) -> str:
        """Generate the command to start the SWE-ReX server inside the sandbox.

        If swerex is not installed in the image, fall back to installing pipx
        and running the server via `pipx run` (same strategy as DockerDeployment).
        """
        rex_args = f"--port {self._config.port} --auth-token {token}"
        pipx_install = "python3 -m pip install pipx && python3 -m pipx ensurepath"
        return f"{REMOTE_EXECUTABLE_NAME} {rex_args} || ({pipx_install} && pipx run {PACKAGE_NAME} {rex_args})"

    def _get_entrypoint(self, *, token: str) -> list[str]:
        return ["/bin/sh", "-c", self._get_start_command(token=token)]

    def _get_connection_config(self) -> Any:
        from opensandbox.config import ConnectionConfig

        return ConnectionConfig(
            api_key=self._config.api_key or None,
            domain=self._config.domain or None,
            protocol=self._config.protocol,
            request_timeout=timedelta(seconds=self._config.request_timeout),
        )

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None or self._sandbox is None:
            raise DeploymentNotStartedError()

        try:
            info = await self._sandbox.get_info()
        except Exception:
            # Transient errors (e.g. the sandbox record not being visible yet)
            # should not abort a pending start(); the runtime check below keeps
            # the wait loop retrying.
            self.logger.debug("Failed to query OpenSandbox sandbox status", exc_info=True)
        else:
            state = getattr(getattr(info, "status", None), "state", None)
            state_value = str(getattr(state, "value", state))
            if state_value not in _RECOVERABLE_STATES:
                msg = f"OpenSandbox sandbox is not recoverable (state={state_value})"
                raise RuntimeError(msg)

        return await self._runtime.is_alive(timeout=timeout)

    async def _wait_until_alive(self, timeout: float):
        """Wait until the runtime is alive."""
        return await _wait_until_alive(self.is_alive, timeout=timeout, function_timeout=self._config.request_timeout)

    async def start(self):
        """Starts the runtime in an OpenSandbox sandbox."""
        if self._runtime is not None and self._sandbox is not None:
            self.logger.warning("Deployment is already started. Ignoring duplicate start() call.")
            return

        from opensandbox import Sandbox

        self._hooks.on_custom_step("Starting OpenSandbox sandbox")
        t0 = time.time()
        self._auth_token = self._get_token()

        create_kwargs: dict[str, Any] = dict(self._config.create_sandbox_kwargs)
        self._sandbox = await Sandbox.create(
            image=self._config.image,
            entrypoint=self._get_entrypoint(token=self._auth_token),
            timeout=timedelta(seconds=self._config.sandbox_timeout),
            resource=self._config.resource,
            connection_config=self._get_connection_config(),
            **create_kwargs,
        )
        self._sandbox_id = self._sandbox.id
        self.logger.info(f"Created OpenSandbox sandbox with ID: {self._sandbox_id}")

        endpoint = await self._sandbox.get_endpoint(self._config.port)
        if endpoint.headers:
            self.logger.warning(
                "The sandbox endpoint requires extra headers for routing (%s). "
                "Requests made by the runtime will not include them; if the runtime "
                "fails to connect, use a setup where the endpoint is directly routable.",
                sorted(endpoint.headers),
            )
        self.logger.info(f"Starting runtime at {endpoint.endpoint}")

        self._runtime = RemoteRuntime(
            host=endpoint.endpoint,
            timeout=self._config.runtime_timeout,
            auth_token=self._auth_token,
            logger=self.logger,
        )

        remaining_startup_timeout = max(0.0, self._config.startup_timeout - (time.time() - t0))
        await self._wait_until_alive(timeout=remaining_startup_timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    async def stop(self):
        """Stops the runtime and removes the OpenSandbox sandbox."""
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

        if self._sandbox is not None:
            try:
                self.logger.info(f"Destroying OpenSandbox sandbox with ID: {self._sandbox_id}")
                await self._sandbox.destroy()
                self.logger.info("OpenSandbox sandbox destroyed successfully")
            except Exception as e:
                self.logger.error(f"Failed to destroy OpenSandbox sandbox: {str(e)}")

        self._sandbox = None
        self._sandbox_id = None
        self._auth_token = None

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
    def sandbox_id(self) -> str:
        """Returns the ID of the OpenSandbox sandbox if started.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._sandbox_id is None:
            raise DeploymentNotStartedError()
        return self._sandbox_id
