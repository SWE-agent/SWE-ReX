import asyncio
import logging
import time
import uuid
from typing import Any

from daytona_sdk import (
    AsyncDaytona,
    CreateSandboxFromImageParams,
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
from swerex.runtime.daytona import DaytonaRuntime
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
        self._runtime: DaytonaRuntime | None = None
        self._sandbox = None
        self._sandbox_id = None
        self.logger = logger or get_logger("rex-deploy")
        self._hooks = CombinedDeploymentHook()
        self._daytona = None
        self._auth_token = None
        self._session_id = None

    def add_hook(self, hook: DeploymentHook):
        self._hooks.add_hook(hook)

    @classmethod
    def from_config(cls, config: DaytonaDeploymentConfig) -> Self:
        return cls(**config.model_dump())

    def _init_daytona(self):
        """Initialize the Daytona client with configuration."""
        if self._config.api_url:
            # Self-hosted: use api_url directly
            daytona_config = DaytonaConfig(api_key=self._config.api_key, api_url=self._config.api_url)
        else:
            # Cloud: use target region
            daytona_config = DaytonaConfig(api_key=self._config.api_key, target=self._config.target)
        self._daytona = AsyncDaytona(daytona_config)

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

    async def _poll_command(self, session_id: str, command_id: str, timeout: float) -> tuple[int, str]:
        """Poll a command until it completes or times out.
        
        Returns:
            tuple of (exit_code, output)
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = await self._sandbox.process.get_session_command(session_id, command_id)
            if response.exit_code is not None:
                logs = await self._sandbox.process.get_session_command_logs(session_id, command_id)
                return int(response.exit_code), logs.stdout or ""
            await asyncio.sleep(0.5)
        return -1, "Command timed out"

    async def _check_server_health(
        self, server_session_id: str, timeout: float, server_cmd_id: str, auth_token: str
    ) -> bool:
        """Check if swerex server is ready by polling is_alive endpoint inside sandbox.
        
        Uses a separate session for health checks to avoid conflicts with the server process.
        Uses Python's urllib instead of curl to avoid dependency on curl.
        
        Returns:
            True if server is healthy, False otherwise
        """
        # Create a separate session for health checks
        health_session_id = f"health-check-{uuid.uuid4().hex[:8]}"
        await self._sandbox.process.create_session(health_session_id)
        self.logger.info(f"Created health check session: {health_session_id}")
        
        # Use Python for health check with auth header
        health_cmd = (
            f"python -c \""
            f"import urllib.request; "
            f"req = urllib.request.Request('http://localhost:{self._config.port}/is_alive'); "
            f"req.add_header('X-API-Key', '{auth_token}'); "
            f"resp = urllib.request.urlopen(req, timeout=5); "
            f"print(resp.status)"
            f"\""
        )
        
        start_time = time.time()
        check_count = 0
        while time.time() - start_time < timeout:
            check_count += 1
            
            # Log server status on first check
            if check_count == 1:
                try:
                    server_logs = await self._sandbox.process.get_session_command_logs(
                        server_session_id, server_cmd_id
                    )
                    log_output = server_logs.stdout or server_logs.stderr or "No logs yet"
                    self.logger.info(f"Initial server logs: {log_output[:500]}")
                except Exception as log_e:
                    self.logger.info(f"Could not get initial server logs: {log_e}")
            
            try:
                response = await self._sandbox.process.execute_session_command(
                    health_session_id,
                    SessionExecuteRequest(command=health_cmd, run_async=True),
                )
                if response.cmd_id:
                    # Use longer timeout for remote environments (EKS, EC2)
                    exit_code, output = await self._poll_command(health_session_id, response.cmd_id, timeout=30)
                    self.logger.info(f"Health check #{check_count}: exit_code={exit_code}, output={output.strip()}")
                    if exit_code == 0 and "200" in output:
                        return True
            except Exception as e:
                self.logger.info(f"Health check #{check_count} failed: {e}")
            
            # Every 5 checks, log server process status
            if check_count % 5 == 0:
                try:
                    server_logs = await self._sandbox.process.get_session_command_logs(
                        server_session_id, server_cmd_id
                    )
                    log_output = server_logs.stdout or server_logs.stderr or ""
                    self.logger.info(f"Server logs (last 200 chars): {log_output[-200:]}")
                except Exception as log_e:
                    self.logger.info(f"Could not get server logs: {log_e}")
            
            await asyncio.sleep(1)
        return False

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None or self._sandbox is None:
            raise DeploymentNotStartedError()

        # Check if the workspace is still running
        try:
            sessions = await self._sandbox.process.list_sessions()
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
        """Starts the runtime in a Daytona sandbox.
        
        This method uses polling to verify swerex server is running inside the sandbox,
        then connects to it via Preview URL for external access.
        """
        self._init_daytona()
        self.logger.info("Creating Daytona sandbox...")

        # Create workspace with specified parameters
        params = CreateSandboxFromImageParams(
            image=self._config.image,
        )
        assert self._daytona is not None

        self._sandbox = await self._daytona.create(params)
        self._sandbox_id = self._sandbox.id
        self.logger.info(f"Created Daytona sandbox with ID: {self._sandbox_id}")

        # Generate authentication token
        self._auth_token = self._get_token()

        # Run the SWE Rex server in the sandbox
        command = self._get_command(token=self._auth_token)
        self.logger.info("Starting SWE Rex server in Daytona sandbox...")

        # Create a session for the long-running process
        self._session_id = f"swerex-server-{uuid.uuid4().hex[:8]}"
        await self._sandbox.process.create_session(self._session_id)
        
        # Execute server command asynchronously
        req = SessionExecuteRequest(command=command, run_async=True)
        server_response = await self._sandbox.process.execute_session_command(self._session_id, req)
        server_cmd_id = server_response.cmd_id
        self.logger.info(f"Server command executed in session {self._session_id}, cmd_id={server_cmd_id}")

        # Poll for server health inside the sandbox
        self.logger.info("Waiting for swerex server to be ready...")
        t0 = time.time()
        
        server_ready = await self._check_server_health(
            self._session_id, 
            timeout=self._config.runtime_timeout, 
            server_cmd_id=server_cmd_id,
            auth_token=self._auth_token,
        )
        
        if not server_ready:
            msg = f"Server failed to start within {self._config.runtime_timeout}s"
            raise RuntimeError(msg)
        
        self.logger.info(f"Server is ready (took {time.time() - t0:.2f}s)")

        # Create a runtime session for SDK-based communication
        runtime_session_id = f"swerex-runtime-{uuid.uuid4().hex[:8]}"
        await self._sandbox.process.create_session(runtime_session_id)
        self.logger.info(f"Created runtime session: {runtime_session_id}")

        # Create the DaytonaRuntime that uses SDK commands instead of HTTP
        # This bypasses OAuth authentication issues with Preview URLs
        self._runtime = DaytonaRuntime(
            sandbox=self._sandbox,
            session_id=runtime_session_id,
            auth_token=self._auth_token,
            port=self._config.port,
            logger=self.logger,
        )

        # Verify runtime is alive
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
                await self._daytona.delete(self._sandbox)
                self.logger.info("Daytona sandbox removed successfully")
            except Exception as e:
                self.logger.error(f"Failed to remove Daytona sandbox: {str(e)}")

        self._sandbox = None
        self._sandbox_id = None
        self._auth_token = None
        self._session_id = None

    @property
    def runtime(self) -> DaytonaRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            msg = "Runtime not started"
            raise RuntimeError(msg)
        return self._runtime
