import asyncio
import logging
import os
import shlex
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import requests
from typing_extensions import Self

from swerex import PACKAGE_NAME, REMOTE_EXECUTABLE_NAME
from swerex.deployment.abstract import AbstractDeployment
from swerex.deployment.config import DockerDeploymentConfig
from swerex.deployment.hooks.abstract import CombinedDeploymentHook, DeploymentHook
from swerex.exceptions import DeploymentNotStartedError, DockerPullError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.config import RemoteRuntimeConfig
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.free_port import find_free_port
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive

__all__ = ["DockerDeployment", "DockerDeploymentConfig"]

REMOTE_EXECUTABLE_PATH = Path("/", REMOTE_EXECUTABLE_NAME)


def _is_image_available(image: str, runtime: str = "docker") -> bool:
    try:
        subprocess.check_call(
            [runtime, "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _pull_image(image: str, runtime: str = "docker") -> bytes:
    try:
        return subprocess.check_output([runtime, "pull", image], stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        # e.stderr contains the error message as bytes
        raise subprocess.CalledProcessError(e.returncode, e.cmd, e.output, e.stderr) from None


def _remove_image(image: str, runtime: str = "docker") -> bytes:
    return subprocess.check_output([runtime, "rmi", image], timeout=30)


class DockerDeployment(AbstractDeployment):
    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ):
        """Deployment to local container image using Docker or Podman.

        Args:
            **kwargs: Keyword arguments (see `DockerDeploymentConfig` for details).
        """
        self._config = DockerDeploymentConfig(**kwargs)
        self._runtime: RemoteRuntime | None = None
        self._container_process = None
        self._container_name = None
        self.logger = logger or get_logger("rex-deploy")
        self._runtime_timeout = 0.15
        self._hooks = CombinedDeploymentHook()

    def add_hook(self, hook: DeploymentHook):
        self._hooks.add_hook(hook)

    @classmethod
    def from_config(cls, config: DockerDeploymentConfig) -> Self:
        return cls(**config.model_dump())

    def _get_container_name(self) -> str:
        """Returns a unique container name based on the image name."""
        image_name_sanitized = "".join(c for c in self._config.image if c.isalnum() or c in "-_.")
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
            self.logger.error(self._container_process.stdout.read().decode())  # type: ignore
            self.logger.error(self._container_process.stderr.read().decode())  # type: ignore
            assert self._container_process is not None
            await self.stop()
            raise e

    def _get_token(self) -> str:
        return str(uuid.uuid4())

    def _get_swerex_start_cmd(self, token: str) -> list[str]:
        rex_args = f"--auth-token {token}"
        cmd = f"chmod +x {REMOTE_EXECUTABLE_PATH} && {REMOTE_EXECUTABLE_PATH} --port 8000 {rex_args}"
        # Need to wrap with /bin/sh -c to avoid having '&&' interpreted by the parent shell
        return [
            "/bin/sh",
            # "-l",
            "-c",
            cmd,
        ]

    def _pull_image(self) -> None:
        if self._config.pull == "never":
            return
        if self._config.pull == "missing" and _is_image_available(self._config.image, self._config.container_runtime):
            return
        self.logger.info(f"Pulling image {self._config.image!r}")
        self._hooks.on_custom_step("Pulling container image")
        try:
            _pull_image(self._config.image, self._config.container_runtime)
        except subprocess.CalledProcessError as e:
            msg = f"Failed to pull image {self._config.image}. "
            msg += f"Error: {e.stderr.decode()}"
            msg += f"Output: {e.output.decode()}"
            raise DockerPullError(msg) from e

    @property
    def glibc_dockerfile(self) -> str:
        # will only work with glibc-based systems
        if self._config.platform:
            platform_arg = f"--platform={self._config.platform}"
        else:
            platform_arg = ""
        return (
            "ARG BASE_IMAGE\n\n"
            # Build stage for standalone Python
            f"FROM {platform_arg} python:3.11.9-slim-bookworm AS builder\n"
            # Install build dependencies
            "RUN apt-get update && apt-get install -y \\\n"
            "    wget \\\n"
            "    gcc \\\n"
            "    make \\\n"
            "    zlib1g-dev \\\n"
            "    libssl-dev \\\n"
            "    && rm -rf /var/lib/apt/lists/*\n\n"
            # Download and compile Python as standalone
            "WORKDIR /build\n"
            "RUN wget https://www.python.org/ftp/python/3.11.8/Python-3.11.8.tgz \\\n"
            "    && tar xzf Python-3.11.8.tgz\n"
            "WORKDIR /build/Python-3.11.8\n"
            "RUN ./configure \\\n"
            "    --prefix=/root/python3.11 \\\n"
            "    --enable-shared \\\n"
            "    LDFLAGS='-Wl,-rpath=/root/python3.11/lib' && \\\n"
            "    make -j$(nproc) && \\\n"
            "    make install && \\\n"
            "    ldconfig\n\n"
            # Production stage
            f"FROM {platform_arg} $BASE_IMAGE\n"
            # Ensure we have the required runtime libraries
            "RUN apt-get update && apt-get install -y \\\n"
            "    libc6 \\\n"
            "    && rm -rf /var/lib/apt/lists/*\n"
            # Copy the standalone Python installation
            f"COPY --from=builder /root/python3.11 {self._config.python_standalone_dir}/python3.11\n"
            f"ENV LD_LIBRARY_PATH={self._config.python_standalone_dir}/python3.11/lib:${{LD_LIBRARY_PATH:-}}\n"
            # Verify installation
            f"RUN {self._config.python_standalone_dir}/python3.11/bin/python3 --version\n"
            # Install swe-rex using the standalone Python
            f"RUN /root/python3.11/bin/pip3 install --no-cache-dir {PACKAGE_NAME}\n\n"
            f"RUN ln -s /root/python3.11/bin/{REMOTE_EXECUTABLE_NAME} /usr/local/bin/{REMOTE_EXECUTABLE_NAME}\n\n"
            f"RUN {REMOTE_EXECUTABLE_NAME} --version\n"
        )

    def _build_image(self) -> str:
        """Builds image, returns image ID."""
        self.logger.info(
            f"Building image {self._config.image} to install a standalone python to {self._config.python_standalone_dir}. "
            "This might take a while (but you only have to do it once). To skip this step, set `python_standalone_dir` to None."
        )
        dockerfile = self.glibc_dockerfile
        platform_arg = []
        if self._config.platform:
            platform_arg = ["--platform", self._config.platform]
        build_cmd = [
            self._config.container_runtime,
            "build",
            "-q",
            *platform_arg,
            "--build-arg",
            f"BASE_IMAGE={self._config.image}",
            "-",
        ]
        image_id = (
            subprocess.check_output(
                build_cmd,
                input=dockerfile.encode(),
            )
            .decode()
            .strip()
        )
        if not image_id.startswith("sha256:"):
            msg = f"Failed to build image. Image ID is not a SHA256: {image_id}"
            raise RuntimeError(msg)
        return image_id

    async def start(self):
        """Starts the runtime."""
        asyncio.to_thread(self._pull_image)
        if self._config.python_standalone_dir:
            image_id = self._build_image()
        else:
            image_id = self._config.image
        if self._config.port is None:
            self._config.port = find_free_port()
        assert self._container_name is None
        self._container_name = self._get_container_name()
        token = self._get_token()
        platform_arg = []
        if self._config.platform is not None:
            platform_arg = ["--platform", self._config.platform]
        rm_arg = []
        if self._config.remove_container:
            rm_arg = ["--rm"]

        image_arch = subprocess.check_output(
            self._config.container_runtime + " inspect --format '{{.Architecture}}' " + image_id, shell=True, text=True
        ).strip()
        assert image_arch in {"amd64", "arm64"}, f"Unsupported architecture: {image_arch}"
        t0 = time.time()

        def _start_and_copy():
            with tempfile.TemporaryDirectory() as temp_dir:
                # download the remote server
                tmp_exec_path = Path(temp_dir) / REMOTE_EXECUTABLE_NAME
                exec_url = f"https://github.com/Co1lin/SWE-ReX/releases/latest/download/swerex-remote-{image_arch}"
                self.logger.info(f"Downloading remote executable from {exec_url} to {tmp_exec_path}")
                r_exec = requests.get(exec_url)
                r_exec.raise_for_status()
                with open(tmp_exec_path, "wb") as f:
                    f.write(r_exec.content)
                # start the container
                cmds_run = [
                    self._config.container_runtime,
                    "run",
                    *rm_arg,
                    "-p",
                    f"{self._config.port}:8000",
                    *platform_arg,
                    *self._config.docker_args,
                    "--name",
                    self._container_name,
                    "-itd",
                    image_id,
                ]
                self.logger.info(
                    f"Starting container {self._container_name} with image {self._config.image} serving on port {self._config.port}: {shlex.join(cmds_run)}"
                )
                subprocess.check_output(cmds_run, stderr=subprocess.STDOUT)
                # copy the remote server executable into the container
                self._copy_to(tmp_exec_path, REMOTE_EXECUTABLE_PATH)

        await asyncio.to_thread(_start_and_copy)
        # execute the remote server
        cmds_exec = [
            self._config.container_runtime,
            "exec",
            self._container_name,
            *self._get_swerex_start_cmd(token),
        ]
        self.logger.info(f"Executing remote server in container {self._container_name}: {shlex.join(cmds_exec)}")
        self._container_process = subprocess.Popen(cmds_exec, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._hooks.on_custom_step("Starting runtime")
        self._runtime = RemoteRuntime.from_config(
            RemoteRuntimeConfig(port=self._config.port, timeout=self._runtime_timeout, auth_token=token)
        )
        await self._wait_until_alive(timeout=self._config.startup_timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    async def stop(self):
        """Stops the runtime."""
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

        if self._container_process is not None:
            try:
                subprocess.check_call(
                    [self._config.container_runtime, "kill", self._container_name],  # type: ignore
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
                self.logger.info(f"Killed container {self._container_name}")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                self.logger.warning(
                    f"Failed to kill container {self._container_name}: {e}. Will try harder.",
                    exc_info=False,
                )
            for _ in range(3):
                self._container_process.kill()
                try:
                    self._container_process.wait(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    continue
            else:
                self.logger.warning(f"Failed to kill container {self._container_name} with SIGKILL")

            self._container_process = None
            self._container_name = None

        if self._config.remove_images:
            if _is_image_available(self._config.image, self._config.container_runtime):
                self.logger.info(f"Removing image {self._config.image}")
                try:
                    _remove_image(self._config.image, self._config.container_runtime)
                except subprocess.CalledProcessError:
                    self.logger.error(f"Failed to remove image {self._config.image}", exc_info=True)

    @property
    def runtime(self) -> RemoteRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime

    def _copy_to(self, src: str, dst: str) -> None:
        """
        Copies a file or directory from the host to the container.

        Args:
            src (str): The path to the source file or directory on the host.
            dst (str): The destination path inside the container. If `dst` ends
                       with '/', it's treated as a directory.
        """
        # Separate the destination path into directory and filename
        dst_dir, dst_filename = os.path.split(dst)

        # If dst is a directory path (e.g., "/path/to/dir/"), dst_filename will be empty.
        # In this case, the destination filename should be the source filename.
        if not dst_filename:
            dst_filename = Path(src).name
        dst_path = Path(dst_dir) / dst_filename

        # Step 1: docker cp (host -> container)
        subprocess.check_output(["docker", "cp", src, f"{self._container_name}:{dst_path}"], stderr=subprocess.STDOUT)

        # Step 2: fix ownership to match container user
        uid = subprocess.check_output(
            ["docker", "exec", self._container_name, "id", "-u"],
            text=True,
        ).strip()
        gid = subprocess.check_output(
            ["docker", "exec", self._container_name, "id", "-g"],
            text=True,
        ).strip()
        subprocess.check_output(
            ["docker", "exec", self._container_name, "chown", "-R", f"{uid}:{gid}", dst_path],
            stderr=subprocess.STDOUT,
        )
