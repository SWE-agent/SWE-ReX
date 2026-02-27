import logging
import time
import uuid
from typing import Any

from typing_extensions import Self
from volcenginesdkapig import APIGApi
from volcenginesdkapig.models import (
    GetGatewayServiceRequest,
    GetGatewayServiceResponse,
)
from volcenginesdkcore import ApiClient, Configuration
from volcenginesdkvefaas import (
    CreateSandboxRequest,
    CreateSandboxResponse,
    InstanceImageInfoForCreateSandboxInput,
    KillSandboxRequest,
    VEFAASApi,
)

from swerex.deployment.abstract import AbstractDeployment
from swerex.deployment.config import VeFaasDeploymentConfig
from swerex.deployment.hooks.abstract import CombinedDeploymentHook, DeploymentHook
from swerex.exceptions import DeploymentNotStartedError, DeploymentStartupError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.config import RemoteRuntimeConfig
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive


class VeFaasDeployment(AbstractDeployment):
    def __init__(self, *, logger: logging.Logger | None = None, **kwargs: Any):
        self._config = VeFaasDeploymentConfig(**kwargs)
        self._runtime: RemoteRuntime | None = None
        self._container_name = None
        self._hooks = CombinedDeploymentHook()
        self.logger = logger or get_logger("rex-deploy")
        self._runtime_timeout = 0.15
        self._api_client = None

        self._sandbox_id = ""

    @classmethod
    def from_config(cls, config: VeFaasDeploymentConfig) -> Self:
        return cls(**config.model_dump())

    def add_hook(self, hook: DeploymentHook):
        self._hooks.add_hook(hook)

    def _get_token(self) -> str:
        return str(uuid.uuid4())

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive. The return value can be
        tested with bool().

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            msg = "Runtime not started"
            raise RuntimeError(msg)
        return await self._runtime.is_alive(timeout=timeout)

    async def _wait_until_alive(self, timeout: float = 10.0):
        try:
            return await _wait_until_alive(self.is_alive, timeout=timeout, function_timeout=self._runtime_timeout)
        except TimeoutError as e:
            self.logger.error("Runtime did not start within timeout. Here's the output from the container process.")
            await self.stop()
            raise e

    def _get_domain(self, apigs_id):
        api_instance = APIGApi(self._get_api_client())
        req = GetGatewayServiceRequest(
            id=apigs_id,
        )
        response = api_instance.get_gateway_service(req)
        if not isinstance(response, GetGatewayServiceResponse):
            raise Exception(response)

        https_domains = [d.domain for d in response.gateway_service.domains if d.domain.startswith("https://")]

        if https_domains:
            return https_domains[0]
        elif response.gateway_service.domains:
            return response.gateway_service.domains[0].domain
        else:
            return None

    def _get_container_name(self) -> str:
        """Returns a unique container name based on the image name."""
        image_str = self._config.image.split("/")
        image_name_sanitized = image_str[-1].replace("_", "-")
        image_name_sanitized = image_name_sanitized.replace(":", "-")
        image_name_sanitized = image_name_sanitized.replace(".", "-")

        return image_name_sanitized[:-14]

    def _get_api_client(self) -> ApiClient:
        if self._api_client:
            return self._api_client

        access_key = self._config.ak
        secret_key = self._config.sk
        region = self._config.region

        if not access_key or not secret_key:
            emsg = "VOLCENGINE_ACCESS_KEY and VOLCENGINE_SECRET_KEY must be set"
            raise DeploymentStartupError(emsg)

        config = Configuration()
        config.ak = access_key
        config.sk = secret_key
        config.region = region
        _api_client = ApiClient(config)

        self._api_client = _api_client
        return self._api_client

    async def create_sandbox(self, function_id, image, cmd, request_timeout) -> str:
        client = VEFAASApi(self._get_api_client())

        instance_image_info = InstanceImageInfoForCreateSandboxInput(image=image, port=8000, command=cmd)

        response = client.create_sandbox(
            CreateSandboxRequest(
                function_id=function_id,
                instance_image_info=instance_image_info,
                request_timeout=request_timeout,
                timeout=120,
            )
        )
        if not isinstance(response, CreateSandboxResponse):
            emsg = "Failed to create sandbox"
            raise DeploymentStartupError(emsg)
        if not response.sandbox_id:
            emsg = "Failed to create sandbox: no sandbox id"
            raise DeploymentStartupError(emsg)
        return response.sandbox_id

    async def kill_sandbox(self) -> str:
        client = VEFAASApi(self._get_api_client())

        if self._sandbox_id:
            response = client.kill_sandbox(
                KillSandboxRequest(function_id=self._config.function_id, sandbox_id=self._sandbox_id)
            )
            if not isinstance(response, CreateSandboxResponse):
                self.logger.warning(f"Kill Sandbox {self._sandbox_id} Failed")
        self._sandbox_id = ""

    async def start(self):
        """Start Faas runtime"""

        assert self._container_name is None
        self._container_name = self._get_container_name()

        self.logger.info(f"Starting container {self._container_name}")

        # Gen swe-rex command
        token = self._get_token()
        cmd = f"curl -fsSL https://vefaas-swe.tos-cn-beijing.volces.com/swe-rex/install_1.4.0.sh | bash -s -- {token}"

        # create sandbox
        sandbox_id = await self.create_sandbox(
            self._config.function_id, self._config.image, cmd, self._config.request_timeout
        )
        self._sandbox_id = sandbox_id

        domain = self._get_domain(self._config.apigateway_service_id)

        self._runtime = RemoteRuntime.from_config(
            RemoteRuntimeConfig(
                host=domain, timeout=self._runtime_timeout, auth_token=token, faas_instance_name=self._sandbox_id
            )
        )

        t0 = time.time()
        await self._wait_until_alive(timeout=self._config.startup_timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    async def stop(self):
        """Stop the runtime"""
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

        # kill sandbox
        await self.kill_sandbox()

    @property
    def runtime(self) -> RemoteRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime
