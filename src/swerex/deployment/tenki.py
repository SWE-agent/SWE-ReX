import logging
import time
import uuid
from typing import Any

from tenki_sandbox import Client, Sandbox
from typing_extensions import Self

from swerex import PACKAGE_NAME, REMOTE_EXECUTABLE_NAME
from swerex.deployment.abstract import AbstractDeployment
from swerex.deployment.config import TenkiDeploymentConfig
from swerex.deployment.hooks.abstract import CombinedDeploymentHook, DeploymentHook
from swerex.exceptions import DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive

__all__ = ["TenkiDeployment", "TenkiDeploymentConfig"]


class TenkiDeployment(AbstractDeployment):
    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ):
        """Deployment for running the SWE-ReX server in a Tenki sandbox (https://tenki.cloud).

        Args:
            **kwargs: Keyword arguments (see `TenkiDeploymentConfig` for details).
        """
        self._config = TenkiDeploymentConfig(**kwargs)
        self._runtime: RemoteRuntime | None = None
        self._sandbox: Sandbox | None = None
        self._sandbox_id = None
        self._auth_token = None
        self.logger = logger or get_logger("rex-deploy")
        self._hooks = CombinedDeploymentHook()

    def add_hook(self, hook: DeploymentHook):
        self._hooks.add_hook(hook)

    @classmethod
    def from_config(cls, config: TenkiDeploymentConfig) -> Self:
        return cls(**config.model_dump())

    def _get_token(self) -> str:
        """Generate a unique authentication token."""
        return str(uuid.uuid4())

    def _get_client_kwargs(self) -> dict[str, Any]:
        client_kwargs: dict[str, Any] = {}
        if self._config.api_key:
            client_kwargs["auth_token"] = self._config.api_key
        if self._config.base_url:
            client_kwargs["base_url"] = self._config.base_url
        return client_kwargs

    def _resolve_project_id(self) -> str:
        """Resolve the project to create the sandbox in from the API key's identity.

        Raises:
            RuntimeError: If the API key has access to more than one project.
        """
        client = Client(**self._get_client_kwargs())
        identity = client.who_am_i()
        projects = [project.id for workspace in identity.workspaces for project in workspace.projects]
        if len(projects) != 1:
            msg = (
                f"Could not resolve the Tenki project automatically (found {len(projects)} projects). "
                "Please set project_id in the deployment configuration."
            )
            raise RuntimeError(msg)
        return projects[0]

    def _get_command(self, *, token: str) -> str:
        """Generate the command to run the SWE Rex server."""
        main_command = f"{REMOTE_EXECUTABLE_NAME} --port {self._config.port} --auth-token {token}"
        fallback_commands = [
            # The default Tenki image runs as a non-root user with passwordless sudo
            "SUDO=; if [ $(id -u) -ne 0 ] && command -v sudo > /dev/null; then SUDO=sudo; fi",
            "$SUDO apt-get update -y",
            "$SUDO apt-get install pipx -y",
            "pipx ensurepath",
            f"pipx run {PACKAGE_NAME} --port {self._config.port} --auth-token {token}",
        ]
        fallback_script = " && ".join(fallback_commands)
        inner_command = f"{main_command} || ( {fallback_script} )"
        # `exec` streams the command's output until it closes, so the server is
        # backgrounded with its streams detached (see the Tenki docs on port exposure).
        return (
            f"timeout {self._config.container_timeout}s bash -c '{inner_command}' > /tmp/swerex.log 2>&1 < /dev/null &"
        )

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None or self._sandbox is None:
            raise DeploymentNotStartedError()

        try:
            self._sandbox.refresh()
            state = self._sandbox.state
        except Exception as e:
            msg = f"Error checking Tenki sandbox status: {e}"
            raise RuntimeError(msg)
        if state != "RUNNING":
            msg = f"Tenki sandbox is not running (state: {state})"
            raise RuntimeError(msg)

        return await self._runtime.is_alive(timeout=timeout)

    async def _wait_until_alive(self, timeout: float):
        """Wait until the runtime is alive."""
        return await _wait_until_alive(self.is_alive, timeout=timeout, function_timeout=self._config.runtime_timeout)

    def _read_server_log(self) -> str:
        """Best-effort read of the server log in the sandbox (for error messages)."""
        if self._sandbox is None:
            return "<no sandbox>"
        try:
            result = self._sandbox.exec("bash", "-lc", "tail -c 4096 /tmp/swerex.log")
            return result.stdout_text.strip() or "<empty>"
        except Exception as e:
            return f"<could not read /tmp/swerex.log: {e}>"

    def _terminate_sandbox(self):
        """Terminates the sandbox (if any).

        The sandbox handle is only cleared if termination succeeds, so that a
        failed `stop()` can be retried.
        """
        if self._sandbox is None:
            return
        self.logger.info(f"Terminating Tenki sandbox with ID: {self._sandbox_id}")
        self._sandbox.close_if_open()
        self.logger.info("Tenki sandbox terminated successfully")
        self._sandbox = None
        self._sandbox_id = None

    async def start(self):
        """Starts the runtime in a Tenki sandbox.

        Raises:
            RuntimeError: If the deployment is already started or the runtime fails to start.
        """
        if self._sandbox is not None:
            msg = "The deployment is already started. Call stop() before starting it again."
            raise RuntimeError(msg)
        self.logger.info("Creating Tenki sandbox...")

        create_kwargs: dict[str, Any] = {
            "name": f"swe-rex-{uuid.uuid4().hex[:8]}",
            "project_id": self._config.project_id or self._resolve_project_id(),
            # Inbound is required to expose the server port, outbound for the
            # pipx fallback installation of swe-rex.
            "allow_inbound": True,
            "allow_outbound": True,
            # Kill switch so that a forgotten sandbox doesn't run forever.
            "max_duration": self._config.container_timeout,
        }
        create_kwargs.update(self._get_client_kwargs())
        if self._config.workspace_id:
            create_kwargs["workspace_id"] = self._config.workspace_id
        if self._config.image is not None:
            create_kwargs["image"] = self._config.image
        if self._config.snapshot_id is not None:
            create_kwargs["snapshot_id"] = self._config.snapshot_id
        if self._config.cpu_cores is not None:
            create_kwargs["cpu_cores"] = self._config.cpu_cores
        if self._config.memory_mb is not None:
            create_kwargs["memory_mb"] = self._config.memory_mb
        if self._config.disk_size_gb is not None:
            create_kwargs["disk_size_gb"] = self._config.disk_size_gb
        create_kwargs.update(self._config.sandbox_kwargs)

        # Waits until the sandbox is RUNNING and exec-ready
        self._sandbox = Sandbox.create(**create_kwargs)
        self._sandbox_id = self._sandbox.id
        self.logger.info(f"Created Tenki sandbox with ID: {self._sandbox_id}")

        try:
            self._auth_token = self._get_token()

            command = self._get_command(token=self._auth_token)
            self.logger.info("Starting SWE Rex server in Tenki sandbox...")
            result = self._sandbox.exec("bash", "-lc", command)
            if result.exit_code != 0:
                # The server itself is backgrounded, so this only catches failures
                # of the launcher; server failures surface via the timeout below.
                msg = f"Failed to launch the SWE Rex server: {result.stderr_text}"
                raise RuntimeError(msg)

            preview = self._sandbox.expose_port(self._config.port, ttl=self._config.container_timeout)

            self._runtime = RemoteRuntime(
                host=preview.url,
                port=None,
                auth_token=self._auth_token,
                timeout=self._config.runtime_timeout,
                num_retries=self._config.runtime_retries,
                logger=self.logger,
            )

            t0 = time.time()
            try:
                await self._wait_until_alive(timeout=self._config.startup_timeout)
            except Exception as e:
                msg = (
                    f"The SWE Rex server did not start within {self._config.startup_timeout}s. "
                    f"Server log (/tmp/swerex.log in the sandbox):\n{self._read_server_log()}"
                )
                raise RuntimeError(msg) from e
            self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")
        except BaseException:
            # Don't leave the sandbox running (and billing) if startup fails
            # or is cancelled.
            self._runtime = None
            self._auth_token = None
            try:
                self._terminate_sandbox()
            except Exception as cleanup_exc:
                self.logger.error(f"Failed to terminate Tenki sandbox after failed startup: {cleanup_exc}")
            raise

    async def stop(self):
        """Stops the runtime and terminates the Tenki sandbox.

        Sandbox termination errors are raised (with the sandbox handle kept),
        so that a failed `stop()` can be retried.
        """
        try:
            if self._runtime is not None:
                try:
                    await self._runtime.close()
                except Exception as e:
                    # Closing the runtime must not prevent the sandbox from being terminated
                    self.logger.error(f"Failed to close runtime: {e}")
                finally:
                    self._runtime = None
        finally:
            # Terminate the sandbox even if closing the runtime was cancelled.
            # The SDK call is synchronous, so cancellation cannot interrupt it.
            self._auth_token = None
            self._terminate_sandbox()

    @property
    def runtime(self) -> RemoteRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime
