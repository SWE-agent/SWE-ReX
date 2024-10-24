import asyncio
import os
import time
import uuid
from pathlib import Path, PurePath
from typing import Any

import boto3
import modal
from botocore.exceptions import NoCredentialsError

from swerex import REMOTE_EXECUTABLE_NAME
from swerex.deployment.abstract import AbstractDeployment, DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive

__all__ = ["ModalDeployment"]


def _get_modal_user() -> str:
    # not sure how to get the user from the modal api
    return modal.config._profile  # type: ignore


class _ImageBuilder:
    """_ImageBuilder.auto() is used by ModalDeployment"""

    def from_file(self, image: PurePath, *, build_context: PurePath | None = None) -> modal.Image:
        if build_context is None:
            build_context = Path(image).resolve().parent
        build_context = Path(build_context)
        context_mount = modal.Mount.from_local_dir(
            local_path=build_context,
            remote_path=".",  # to current WORKDIR
        )
        return modal.Image.from_dockerfile(str(image), context_mount=context_mount)

    def from_registry(self, image: str) -> modal.Image:
        if os.environ.get("DOCKER_USERNAME") and os.environ.get("DOCKER_PASSWORD"):
            secret = modal.Secret.from_dict(
                {
                    "DOCKER_USERNAME": os.environ["DOCKER_USERNAME"],
                    "DOCKER_PASSWORD": os.environ["DOCKER_PASSWORD"],
                }
            )
            secrets = [secret]
        else:
            secrets = None
        return modal.Image.from_registry(image, secrets=secrets)

    def from_ecr(self, image: str) -> modal.Image:
        try:
            session = boto3.Session()
            credentials = session.get_credentials()
            aws_access_key_id = credentials.access_key
            aws_secret_access_key = credentials.secret_key
            secret = modal.Secret.from_dict(
                {
                    "AWS_ACCESS_KEY_ID": aws_access_key_id,
                    "AWS_SECRET_ACCESS_KEY": aws_secret_access_key,
                }
            )
            return modal.Image.from_ecr(  # type: ignore
                image,
                secrets=[secret],
            )
        except NoCredentialsError as e:
            msg = "AWS credentials not found. Please configure your AWS credentials."
            raise ValueError(msg) from e

    def ensure_pipx_installed(self, image: modal.Image) -> modal.Image:
        image = image.apt_install("pipx")
        return image.run_commands("pipx ensurepath")

    def auto(self, image_spec: str | modal.Image | PurePath) -> modal.Image:
        if isinstance(image_spec, modal.Image):
            image = image_spec
        elif isinstance(image_spec, PurePath) and not Path(image_spec).is_file():
            msg = f"File {image_spec} does not exist"
            raise FileNotFoundError(msg)
        elif Path(image_spec).is_file():
            image = self.from_file(Path(image_spec))
        elif "amazonaws.com" in image_spec:  # type: ignore
            image = self.from_ecr(image_spec)  # type: ignore
        else:
            image = self.from_registry(image_spec)  # type: ignore

        return self.ensure_pipx_installed(image)


class ModalDeployment(AbstractDeployment):
    def __init__(
        self,
        image: str | modal.Image | PurePath,
        container_timeout: float = 1800,
        runtime_timeout: float = 0.4,
        modal_sandbox_kwargs: dict[str, Any] | None = None,
    ):
        """Deployment for modal.com. The deployment will only start when the
        `start` method is being called.

        Args:
            image: Image to use for the deployment. One of the following:
                1. `modal.Image` object
                2. Path to a Dockerfile
                3. Dockerhub image name (e.g. `python:3.11-slim`)
                4. ECR image name (e.g. `123456789012.dkr.ecr.us-east-1.amazonaws.com/my-image:tag`)
            container_timeout:
            runtime_timeout:
            modal_sandbox_kwargs: Additional arguments to pass to `modal.Sandbox.create`
        """
        self._image = _ImageBuilder().auto(image)
        self._runtime: RemoteRuntime | None = None
        self._container_timeout = container_timeout
        self._sandbox: modal.Sandbox | None = None
        self._port = 8880
        self.logger = get_logger("deploy")
        self._app = modal.App.lookup("swe-rex", create_if_missing=True)
        self._user = _get_modal_user()
        self._runtime_timeout = runtime_timeout
        if modal_sandbox_kwargs is None:
            modal_sandbox_kwargs = {}
        self._modal_kwargs = modal_sandbox_kwargs

    def _get_token(self) -> str:
        return str(uuid.uuid4())

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        if self._runtime is None or self._sandbox is None:
            raise DeploymentNotStartedError()
        if self._sandbox.poll() is not None:
            msg = "Container process terminated."
            output = "stdout:\n" + self._sandbox.stdout.read()  # type: ignore
            output += "\nstderr:\n" + self._sandbox.stderr.read()  # type: ignore
            msg += "\n" + output
            raise RuntimeError(msg)
        return await self._runtime.is_alive(timeout=timeout)

    async def _wait_until_alive(self, timeout: float | None = None):
        assert self._runtime is not None
        return await _wait_until_alive(self.is_alive, timeout=timeout, function_timeout=self._runtime._timeout)

    def _start_swerex_cmd(self, token: str) -> str:
        """Start swerex-server on the remote. If swerex is not installed arelady,
        install pipx and then run swerex-server with pipx run
        """
        pkg_name = "0fdb5604"
        return f"{REMOTE_EXECUTABLE_NAME} --port {self._port} --auth-token {token} || pipx run {pkg_name} --port {self._port} --auth-token {token}"

    def get_modal_log_url(self) -> str:
        """Returns URL to modal logs"""
        return f"https://modal.com/apps/{self._user}/main/deployed/{self.app.name}?activeTab=logs&taskId={self.sandbox._get_task_id()}"

    async def start(
        self,
        *,
        timeout: float = 60,
    ):
        self.logger.info("Starting modal sandbox")
        t0 = time.time()
        token = self._get_token()
        self._sandbox = modal.Sandbox.create(
            "/bin/bash",
            "-c",
            self._start_swerex_cmd(token),
            image=self._image,
            timeout=int(self._container_timeout),
            unencrypted_ports=[self._port],
            app=self._app,
            **self._modal_kwargs,
        )
        tunnel = self._sandbox.tunnels()[self._port]
        self.logger.info(f"Sandbox ({self._sandbox.object_id}) created in {time.time() - t0:.2f}s")
        self.logger.info(f"Check sandbox logs at {self.get_modal_log_url()}")
        self.logger.info(f"Sandbox created with id {self._sandbox.object_id}")
        await asyncio.sleep(1)
        self.logger.info(f"Starting runtime at {tunnel.url}")
        self._runtime = RemoteRuntime(host=tunnel.url, timeout=self._runtime_timeout, auth_token=token)
        t0 = time.time()
        await self._wait_until_alive(timeout=timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    async def stop(self):
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None
        if self._sandbox is not None and not self._sandbox.poll():
            self._sandbox.terminate()
        self._sandbox = None
        self._app = None

    @property
    def runtime(self) -> RemoteRuntime:
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime

    @property
    def app(self) -> modal.App:
        """Returns the modal app

        Raises:
            DeploymentNotStartedError: If the deployment is not started.
        """
        if self._app is None:
            raise DeploymentNotStartedError()
        return self._app

    @property
    def sandbox(self) -> modal.Sandbox:
        """Returns the modal sandbox

        Raises:
            DeploymentNotStartedError: If the deployment is not started.
        """
        if self._sandbox is None:
            raise DeploymentNotStartedError()
        return self._sandbox
