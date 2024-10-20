import subprocess
import time
import uuid

from swerex import REMOTE_EXECUTABLE_NAME
from swerex.deployment.abstract import AbstractDeployment
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.log import get_logger

__all__ = ["DockerDeployment"]


class DockerDeployment(AbstractDeployment):
    def __init__(self, image_name: str, port: int = 8000, docker_args: list[str] | None = None):
        self._image_name = image_name
        self._runtime: RemoteRuntime | None = None
        self._port = port
        self._container_process = None
        if docker_args is None:
            docker_args = []
        self._docker_args = docker_args
        self._container_name = None
        self.logger = get_logger("deploy")

    def _get_container_name(self) -> str:
        image_name_sanitized = "".join(c for c in self._image_name if c.isalnum() or c in "-_.")
        return f"{image_name_sanitized}-{uuid.uuid4()}"

    @property
    def container_name(self) -> str | None:
        return self._container_name

    async def is_alive(self, *, timeout: float | None = None) -> bool:
        if self._runtime is None:
            return False
        return await self._runtime.is_alive(timeout=timeout)

    async def start(
        self,
        *,
        timeout: float | None = None,
    ):
        assert self._container_name is None
        self._container_name = self._get_container_name()
        cmds = [
            "docker",
            "run",
            "--rm",
            "-p",
            f"8000:{self._port}",
            *self._docker_args,
            "--name",
            self._container_name,
            self._image_name,
            REMOTE_EXECUTABLE_NAME,
        ]
        self.logger.info(
            f"Starting container {self._container_name} with image {self._image_name} serving on port {self._port}"
        )
        self.logger.debug(f"Command: {' '.join(cmds)}")
        self._container_process = subprocess.Popen(cmds)
        self.logger.info("Starting runtime")
        self._runtime = RemoteRuntime(port=self._port)
        t0 = time.time()
        await self._runtime.wait_until_alive(timeout=timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    async def stop(self):
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None
        if self._container_process is not None:
            self._container_process.terminate()
            self._container_process = None
        self._container_name = None

    @property
    def runtime(self) -> RemoteRuntime:
        if self._runtime is None:
            msg = "Runtime not started"
            raise RuntimeError(msg)
        return self._runtime
