import logging
import time
import uuid
from typing import Any

from daytona_sdk import (
    CreateSandboxFromImageParams,
    Daytona,
    DaytonaConfig,
    SessionExecuteRequest,
)
from typing_extensions import Self

from swerex import PACKAGE_NAME, REMOTE_EXECUTABLE_NAME
from swerex.deployment.abstract import AbstractDeployment
from swerex.deployment.config import DaytonaDeploymentConfig
from swerex.deployment.hooks.abstract import CombinedDeploymentHook, DeploymentHook
from swerex.exceptions import DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive


class DaytonaDeployment(AbstractDeployment):
    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ):
        self._config = DaytonaDeploymentConfig(**kwargs)
        self._runtime: RemoteRuntime | None = None
        self._sandbox = None
        self._sandbox_id = None
        self.logger = logger or get_logger("rex-deploy")
        self._hooks = CombinedDeploymentHook()
        self._daytona = None
        self._auth_token = None

    def add_hook(self, hook: DeploymentHook):
        self._hooks.add_hook(hook)

    @classmethod
    def from_config(cls, config: DaytonaDeploymentConfig) -> Self:
        return cls(**config.model_dump())

    def _init_daytona(self):
        """Initialize the Daytona client with configuration."""
        daytona_config = DaytonaConfig(api_key=self._config.api_key, target=self._config.target)
        self._daytona = Daytona(daytona_config)

    def _get_token(self) -> str:
        """Generate a unique authentication token."""
        return str(uuid.uuid4())

    def _get_command(self, *, token: str) -> str:
        """Generate the command to run the SWE Rex server."""
        main_command = f"{REMOTE_EXECUTABLE_NAME} --port {self._config.port} --auth-token {token}"
        fallback_commands = [
            "apt-get update -y",
            "apt-get install pipx -y",
            "pipx ensurepath",
            f"pipx run {PACKAGE_NAME} --port {self._config.port} --auth-token {token}",
        ]
        fallback_script = " && ".join(fallback_commands)
        # Wrap the entire command in bash -c to ensure timeout applies to everything
        inner_command = f"{main_command} || ( {fallback_script} )"
        return f"timeout {self._config.container_timeout}s bash -c '{inner_command}'"

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None or self._sandbox is None:
            raise DeploymentNotStartedError()

        # Check if the workspace is still running
        try:
            # Get session status to verify the workspace is still active
            sessions = self._sandbox.process.list_sessions()
            if not sessions:
                msg = "Daytona workspace has no active sessions"
                raise RuntimeError(msg)
        except Exception as e:
            msg = f"Error checking Daytona workspace status: {str(e)}"
            raise RuntimeError(msg)

        return await self._runtime.is_alive(timeout=timeout)

    async def _wait_until_alive(self, timeout: float):
        """Wait until the runtime is alive."""
        return await _wait_until_alive(self.is_alive, timeout=timeout, function_timeout=self._config.container_timeout)

    async def start(self):
        """Starts the runtime in a Daytona sandbox."""
        self._init_daytona()
        self.logger.info("Creating Daytona sandbox...")

        # Create workspace with specified parameters
        params = CreateSandboxFromImageParams(
            image=self._config.image,
        )
        assert self._daytona is not None

        self._sandbox = self._daytona.create(params)
        self._sandbox_id = self._sandbox.id
        self.logger.info(f"Created Daytona sandbox with ID: {self._sandbox_id}")

        # Generate authentication token
        self._auth_token = self._get_token()

        # Run the SWE Rex server in the sandbox
        command = self._get_command(token=self._auth_token)
        self.logger.info("Starting SWE Rex server in Daytona sandbox...")

        # Create a session for the long-running process
        session_id = f"swerex-server-{uuid.uuid4().hex[:8]}"
        self._sandbox.process.create_session(session_id)

        req = SessionExecuteRequest(command=command, runAsync=True)
        # Execute the command in the session
        response = self._sandbox.process.execute_session_command(session_id, req)
        if response.exit_code != 0:
            self.logger.error(f"Failed to start SWE Rex server: {response.output}")
            await self.stop()
            msg = f"Failed to start SWE Rex server: {response.output}"
            raise RuntimeError(msg)

        sweRexHost = self._sandbox.get_preview_link(self._config.port)

        # Create the remote runtime
        self._runtime = RemoteRuntime(host=sweRexHost, port=None, auth_token=self._auth_token, logger=self.logger)

        # Wait for the runtime to be alive
        t0 = time.time()
        await self._wait_until_alive(timeout=self._config.runtime_timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    async def stop(self):
        """Stops the runtime and removes the Daytona sandbox."""
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

        if self._sandbox is not None and self._daytona is not None:
            try:
                self.logger.info(f"Removing Daytona sandbox with ID: {self._sandbox_id}")
                self._daytona.delete(self._sandbox)
                self.logger.info("Daytona sandbox removed successfully")
            except Exception as e:
                self.logger.error(f"Failed to remove Daytona sandbox: {str(e)}")

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
            msg = "Runtime not started"
            raise RuntimeError(msg)
        return self._runtime
