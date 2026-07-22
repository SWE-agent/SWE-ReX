import logging
import shlex
import time
import uuid
from typing import Any

from tenki_sandbox.aio import AsyncClient, AsyncSandbox
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


class TenkiDeployment(AbstractDeployment):
    """Runs the SWE-ReX runtime inside a disposable Tenki (https://tenki.cloud) Firecracker microVM."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ):
        self._config = TenkiDeploymentConfig(**kwargs)
        self._runtime: RemoteRuntime | None = None
        self._client: AsyncClient | None = None
        self._sandbox: AsyncSandbox | None = None
        self._sandbox_id: str | None = None
        self._auth_token: str | None = None
        self.logger = logger or get_logger("rex-deploy")
        self._hooks = CombinedDeploymentHook()

    def add_hook(self, hook: DeploymentHook):
        self._hooks.add_hook(hook)

    @classmethod
    def from_config(cls, config: TenkiDeploymentConfig) -> Self:
        return cls(**config.model_dump())

    def _get_token(self) -> str:
        """Generate a unique authentication token for the SWE-ReX server."""
        return str(uuid.uuid4())

    def _get_command(self, *, token: str) -> str:
        """Command that launches the SWE-ReX server inside the sandbox.

        Unlike Daytona's async-session launch, Tenki's ``shell()`` blocks until the
        command returns — and the server runs forever — so we background it with
        ``nohup … &`` and return immediately. The primary command assumes ``swerex-remote``
        is on PATH; the fallback installs the package via pipx (same as the Daytona
        deployment). A ``timeout`` backstop bounds the process even if the microVM's own
        idle/lifetime caps don't fire first.
        """
        port = self._config.port
        exe, pkg = REMOTE_EXECUTABLE_NAME, PACKAGE_NAME
        args = f"--port {port} --auth-token {token}"
        # Prefer a preinstalled server; otherwise run it with uv (present on Tenki's
        # default image, fast, no root needed); last-ditch apt+pipx (with sudo) for
        # images that ship neither. Tenki sandboxes run as the non-root `tenki` user.
        server = (
            f"{exe} {args} "
            f"|| uvx --from {pkg} {exe} {args} "
            f"|| ( sudo apt-get update -y && sudo apt-get install -y pipx && pipx run {pkg} {args} )"
        )
        return (
            f"nohup timeout {self._config.container_timeout}s bash -c {shlex.quote(server)} "
            f"> /tmp/swerex-server.log 2>&1 &"
        )

    async def _resolve_target(self) -> tuple[str, str]:
        """Resolve the workspace/project pair Tenki requires for sandbox creation.

        Explicit config wins; otherwise the first workspace/project visible to the key
        (via ``who_am_i``) is used — mirroring the other Tenki SDK integrations.
        """
        workspace_id = self._config.workspace_id or None
        project_id = self._config.project_id or None
        assert self._client is not None
        identity = await self._client.who_am_i()
        workspace = next(
            (w for w in identity.workspaces if workspace_id is None or w.id == workspace_id),
            identity.workspaces[0] if identity.workspaces else None,
        )
        if workspace is None or not workspace.projects:
            msg = (
                "No Tenki workspace/project is visible for this API key. "
                "Set workspace_id and project_id on the deployment config."
            )
            raise RuntimeError(msg)
        project = next(
            (p for p in workspace.projects if project_id is None or p.id == project_id),
            workspace.projects[0],
        )
        return workspace.id, project.id

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None or self._sandbox is None:
            raise DeploymentNotStartedError()
        # Cheap liveness gate: the microVM must still be RUNNING before we trust the runtime.
        await self._sandbox.refresh()
        if self._sandbox.state != "RUNNING":
            msg = f"Tenki sandbox is not running (state: {self._sandbox.state})"
            raise RuntimeError(msg)
        return await self._runtime.is_alive(timeout=timeout)

    async def _wait_until_alive(self, timeout: float):
        return await _wait_until_alive(
            self.is_alive, timeout=timeout, function_timeout=self._config.container_timeout
        )

    async def start(self):
        """Starts the runtime in a Tenki sandbox."""
        self._client = AsyncClient(
            auth_token=self._config.api_key or None,
            base_url=self._config.base_url or None,
        )
        workspace_id, project_id = await self._resolve_target()

        self.logger.info("Creating Tenki sandbox...")
        create_kwargs: dict[str, Any] = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            # The server may pipx-install swe-rex, and agents need the network.
            "allow_outbound": True,
            "wait": True,
        }
        if self._config.image:
            create_kwargs["image"] = self._config.image
        if self._config.cpu_cores:
            create_kwargs["cpu_cores"] = self._config.cpu_cores
        if self._config.memory_mb:
            create_kwargs["memory_mb"] = self._config.memory_mb

        self._sandbox = await self._client.create(**create_kwargs)
        self._sandbox_id = self._sandbox.id
        self.logger.info(f"Created Tenki sandbox with ID: {self._sandbox_id}")

        self._auth_token = self._get_token()
        self.logger.info("Starting SWE-ReX server in the Tenki sandbox...")
        result = await self._sandbox.shell(self._get_command(token=self._auth_token))
        if result.exit_code != 0:
            self.logger.error(f"Failed to launch SWE-ReX server (exit {result.exit_code})")
            await self.stop()
            msg = f"Failed to launch SWE-ReX server: exit code {result.exit_code}"
            raise RuntimeError(msg)

        exposed = await self._sandbox.expose_port(self._config.port)
        self.logger.info(f"SWE-ReX server exposed at {exposed.url}")

        self._runtime = RemoteRuntime(
            host=exposed.url, port=None, auth_token=self._auth_token, logger=self.logger
        )

        t0 = time.time()
        await self._wait_until_alive(timeout=self._config.runtime_timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    async def stop(self):
        """Stops the runtime and terminates the Tenki sandbox."""
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

        if self._sandbox is not None:
            try:
                self.logger.info(f"Terminating Tenki sandbox with ID: {self._sandbox_id}")
                await self._sandbox.close()
            except Exception as e:
                self.logger.error(f"Failed to terminate Tenki sandbox: {str(e)}")

        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass

        self._sandbox = None
        self._sandbox_id = None
        self._auth_token = None
        self._client = None

    @property
    def runtime(self) -> RemoteRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime
