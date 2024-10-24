import subprocess
import time
import uuid

from swerex import REMOTE_EXECUTABLE_NAME
from swerex.deployment.abstract import AbstractDeployment, DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive

__all__ = ["DockerDeployment"]


class DockerDeployment(AbstractDeployment):
    def __init__(self, image_name: str, *, port: int = 8000, docker_args: list[str] | None = None):
        """Deployment to local docker image.

        Args:
            image_name: The name of the docker image to use.
            port: The port that is being exposed by the docker container
            docker_args: Additional arguments to pass to the docker run command.
        """
        self._image_name = image_name
        self._runtime: RemoteRuntime | None = None
        self._port = port
        self._container_process = None
        if docker_args is None:
            docker_args = []
        self._docker_args = docker_args
        self._container_name = None
        self.logger = get_logger("deploy")
        self._runtime_timeout = 0.15

    def _get_container_name(self) -> str:
        """Returns a unique container name based on the image name."""
        image_name_sanitized = "".join(c for c in self._image_name if c.isalnum() or c in "-_.")
        return f"{image_name_sanitized}-{uuid.uuid4()}"

    @property
    def container_name(self) -> str | None:
        return self._container_name

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        if self._runtime is None:
            msg = "Runtime not started"
            raise RuntimeError(msg)
        if self._container_process is None:
            msg = "Container process not started"
            raise RuntimeError(msg)
        if self._container_process.poll() is not None:
            msg = "Container process terminated."
            output = "stdout:\n" + self._container_process.stdout.read().decode()  # type: ignore
            output += "\nstderr:\n" + self._container_process.stderr.read().decode()  # type: ignore
            msg += "\n" + output
            raise RuntimeError(msg)
        return await self._runtime.is_alive(timeout=timeout)

    async def _wait_until_alive(self, timeout: float | None = None):
        return await _wait_until_alive(self.is_alive, timeout=timeout, function_timeout=self._runtime_timeout)

    def _get_token(self) -> str:
        return str(uuid.uuid4())

    async def start(
        self,
        *,
        timeout: float | None = None,
    ):
        assert self._container_name is None
        self._container_name = self._get_container_name()
        token = self._get_token()
        cmds = [
            "docker",
            "run",
            "--rm",
            "-p",
            f"{self._port}:8000",
            *self._docker_args,
            "--name",
            self._container_name,
            self._image_name,
            REMOTE_EXECUTABLE_NAME,
            "--auth-token",
            token,
        ]
        self.logger.info(
            f"Starting container {self._container_name} with image {self._image_name} serving on port {self._port}"
        )
        self.logger.debug(f"Command: {' '.join(cmds)}")
        self._container_process = subprocess.Popen(cmds, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.logger.info(f"Starting runtime at {self._port}")
        self._runtime = RemoteRuntime(port=self._port, timeout=self._runtime_timeout, auth_token=token)
        t0 = time.time()
        await self._wait_until_alive(timeout=timeout)
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
            raise DeploymentNotStartedError()
        return self._runtime
