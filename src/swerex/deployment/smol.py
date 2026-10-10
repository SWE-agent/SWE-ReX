"""SWE-ReX deployment inside a Smol Machines microVM.

The guest runs SWE-ReX's own HTTP server, preserving interactive Bash and
interactive shell sessions. A local published port or Smol Cloud's authenticated connect
bridge carries the standard RemoteRuntime protocol. The optional native SDK
is imported only on start, so other deployments do not require it.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import shlex
import uuid
from typing import TYPE_CHECKING, Any

from typing_extensions import Self

from swerex import __version__
from swerex.deployment.abstract import AbstractDeployment
from swerex.deployment.config import SmolDeploymentConfig
from swerex.deployment.hooks.abstract import CombinedDeploymentHook, DeploymentHook
from swerex.exceptions import DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.free_port import find_free_port
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive

if TYPE_CHECKING:
    from smol import Machine

__all__ = ["SmolDeployment", "SmolDeploymentConfig"]


class _SmolRemoteRuntime(RemoteRuntime):
    def __init__(self, *, bridge_headers: dict[str, str], **kwargs: Any):
        super().__init__(**kwargs)
        self._bridge_headers = dict(bridge_headers)

    @property
    def _headers(self) -> dict[str, str]:
        # X-API-Key authenticates to the SWE-ReX guest; Cloud additionally
        # requires the tenant Bearer token at the VM connect bridge.
        return {**super()._headers, **self._bridge_headers}


async def _drain(task: asyncio.Task[Any]) -> Any:
    """Finish an already-started lifecycle operation despite repeated cancellation."""
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


class SmolDeployment(AbstractDeployment):
    def __init__(self, *, logger: logging.Logger | None = None, **kwargs: Any):
        self._config = SmolDeploymentConfig(**kwargs)
        self.logger = logger or get_logger("rex-deploy")
        self._hooks = CombinedDeploymentHook()
        self._runtime: RemoteRuntime | None = None
        self._machine: Machine | None = None
        self._starting = False
        self._lifecycle_lock = asyncio.Lock()

    @classmethod
    def from_config(cls, config: SmolDeploymentConfig) -> Self:
        return cls(**config.model_dump())

    def add_hook(self, hook: DeploymentHook):
        self._hooks.add_hook(hook)

    @property
    def runtime(self) -> RemoteRuntime:
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        return await self.runtime.is_alive(timeout=timeout)

    def _create_machine(self, token: str) -> Machine:
        try:
            from smol import ConnectOptions, Machine, MachineConfig, PortSpec, ResourceSpec
        except ImportError as exc:
            msg = "SmolDeployment requires the optional 'smolmachines' SDK: pip install 'swe-rex[smol]'"
            raise ImportError(msg) from exc

        cfg = self._config
        install = (
            f"python3 -m pip install -q {shlex.quote('swe-rex==' + __version__)} && " if cfg.install_server else ""
        )
        cmd = f'{install}exec swerex-remote --port {cfg.port} --auth-token "$SWEREX_AUTH_TOKEN"'
        # A cloud PortSpec's host port is ignored; the control plane allocates
        # the actual mapping. Local VMs need an available host port up front.
        host_port = cfg.host_port or find_free_port()
        return Machine.create(
            MachineConfig(
                name=f"swerex-smol-{uuid.uuid4().hex[:16]}",
                image=cfg.image,
                command=["sh", "-c", cmd],
                env={"SWEREX_AUTH_TOKEN": token},
                ports=[PortSpec(host=host_port, guest=cfg.port)],
                resources=ResourceSpec(
                    cpus=cfg.cpus,
                    memory_mb=cfg.memory_mb,
                    storage_gb=cfg.storage_gb,
                    overlay_gb=cfg.overlay_gb,
                    network=True,
                ),
                # This deployment has no reconnect path after process exit.
                # Local SDK persistence would retain the VM and its disk.
                persistent=False,
                ttl_seconds=cfg.ttl_seconds if cfg.target == "cloud" else None,
                ready_timeout_seconds=cfg.startup_timeout,
            ),
            ConnectOptions(target=cfg.target, api_key=cfg.api_key.get_secret_value() if cfg.api_key else None),
        )

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._machine is not None or self._starting:
                msg = "Smol deployment is already running"
                raise RuntimeError(msg)
            self._starting = True
            machine: Machine | None = None
            worker: asyncio.Task[Machine] | None = None
            try:
                token = secrets.token_hex(24)
                self._hooks.on_custom_step("Starting Smol microVM")
                worker = asyncio.create_task(asyncio.to_thread(self._create_machine, token))
                machine = await asyncio.shield(worker)
                endpoint = machine.endpoint(self._config.port)
                runtime = _SmolRemoteRuntime(
                    bridge_headers=endpoint.headers,
                    host=endpoint.http_url,
                    port=None,
                    auth_token=token,
                    timeout=self._config.runtime_timeout,
                    logger=self.logger,
                )
                # RemoteRuntime.wait_until_alive gives each HTTP probe only
                # 100 ms, shorter than a typical Smol Cloud bridge round-trip.
                await _wait_until_alive(
                    runtime.is_alive,
                    timeout=self._config.runtime_timeout,
                    function_timeout=min(self._config.runtime_timeout, 10.0),
                )
                self._machine = machine
                self._runtime = runtime
            except BaseException:
                # A cancelled to_thread call keeps running: wait for it to
                # return its VM handle before deleting, or it would leak.
                if machine is None and worker is not None:
                    try:
                        machine = await _drain(worker)
                    except Exception:
                        pass  # create already cleans up its own failure
                if machine is not None:
                    await _drain(asyncio.create_task(asyncio.to_thread(machine.delete)))
                raise
            finally:
                self._starting = False

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            machine = self._machine
            runtime = self._runtime
            if machine is None:
                return
            cancelled = None
            if runtime is not None:
                try:
                    await asyncio.wait_for(runtime.close(), timeout=min(self._config.runtime_timeout, 10))
                except asyncio.CancelledError as exc:
                    cancelled = exc
                except Exception as exc:
                    self.logger.warning("Could not close SWE-ReX sessions before deleting Smol VM: %s", exc)
            # Closing a remote session can be cancelled, but the VM is ours and
            # must still be deleted before control returns to the caller.
            await _drain(asyncio.create_task(asyncio.to_thread(machine.delete)))
            self._machine = None
            self._runtime = None
            if cancelled is not None:
                raise cancelled
