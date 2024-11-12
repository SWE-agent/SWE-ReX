import shlex
import subprocess
import time
import uuid
from typing import Literal

from swerex import PACKAGE_NAME, REMOTE_EXECUTABLE_NAME
from swerex.deployment.abstract import AbstractDeployment, DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.free_port import find_free_port
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive

__all__ = ["DockerDeployment"]


def _is_image_available(image: str) -> bool:
    try:
        subprocess.check_call(["docker", "inspect", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def _pull_image(image: str):
    subprocess.check_output(["docker", "pull", image])

def _remove_image(image: str):
    subprocess.check_output(["docker", "rmi", image])


class DockerDeployment(AbstractDeployment):
    def __init__(
        self,
        image: str,
        *,
        port: int | None = None,
        docker_args: list[str] | None = None,
        startup_timeout: float = 60.0,
        pull: Literal["never", "always", "missing"] = "missing",
        remove_images: bool = False,
    ):
        """Deployment to local docker image.

        Args:
            image: The name of the docker image to use.
            port: The port that the docker container connects to. If None, a free port is found.
            docker_args: Additional arguments to pass to the docker run command.
            startup_timeout: The time to wait for the runtime to start.
            pull: When to pull docker images.
            remove_images: Whether to remove the imageafter it has stopped.
        """
        self._image_name = image
        self._runtime: RemoteRuntime | None = None
        self._port = port
        self._container_process = None
        if docker_args is None:
            docker_args = []
        self._docker_args = docker_args
        self._container_name = None
        self.logger = get_logger("deploy")
        self._runtime_timeout = 0.15
        self._startup_timeout = startup_timeout
        self._pull = pull
        self._remove_images = remove_images

    def _get_container_name(self) -> str:
        """Returns a unique container name based on the image name."""
        image_name_sanitized = "".join(c for c in self._image_name if c.isalnum() or c in "-_.")
        return f"{image_name_sanitized}-{uuid.uuid4()}"

    @property
    def container_name(self) -> str | None:
        return self._container_name

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive. The return value can be
        tested with bool().

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
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

    async def _wait_until_alive(self, timeout: float = 10.0):
        try:
            return await _wait_until_alive(self.is_alive, timeout=timeout, function_timeout=self._runtime_timeout)
        except TimeoutError as e:
            self.logger.error("Runtime did not start within timeout. Here's the output from the container process.")
            assert self._container_process is not None
            self._container_process.terminate()
            self.logger.error(self._container_process.stdout.read().decode())  # type: ignore
            self.logger.error(self._container_process.stderr.read().decode())  # type: ignore
            raise e

    def _get_token(self) -> str:
        return str(uuid.uuid4())

    def _get_swerex_start_cmd(self, token: str) -> list[str]:
        rex_args = f"--auth-token {token}"
        pipx_install = "python3 -m pip install pipx && python3 -m pipx ensurepath"
        # todo: update
        # Need to wrap with /bin/sh -c to avoid having '&&' interpreted by the parent shell
        return [
            "/bin/sh",
            # "-l",
            "-c",
            f"{REMOTE_EXECUTABLE_NAME} {rex_args} || ({pipx_install} && pipx run {PACKAGE_NAME} {rex_args})",
        ]
    
    def _pull_image(self):
        if self._pull == "never":
            return
        if self._pull == "missing" and _is_image_available(self._image_name):
            return
        self.logger.info(f"Pulling image {self._image_name!r}")
        _pull_image(self._image_name)

    async def start(self):
        """Starts the runtime."""
        self._pull_image()
        port = self._port or find_free_port()
        if self._port is None:
            self._port = find_free_port()
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
            *self._get_swerex_start_cmd(token),
        ]
        cmd_str = shlex.join(cmds)
        self.logger.info(
            f"Starting container {self._container_name} with image {self._image_name} serving on port {self._port}"
        )
        self.logger.debug(f"Command: {cmd_str!r}")
        # shell=True required for && etc.
        self._container_process = subprocess.Popen(cmds, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.logger.info(f"Starting runtime at {self._port}")
        self._runtime = RemoteRuntime(port=self._port, timeout=self._runtime_timeout, auth_token=token)
        t0 = time.time()
        await self._wait_until_alive(timeout=self._startup_timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    async def stop(self):
        """Stops the runtime."""
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None
        if self._container_process is not None:
            self._container_process.terminate()
            self._container_process = None
        self._container_name = None
        if self._remove_images:
            if _is_image_available(self._image_name):
                self._remove_image(self._image_name)

    @property
    def runtime(self) -> RemoteRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime
