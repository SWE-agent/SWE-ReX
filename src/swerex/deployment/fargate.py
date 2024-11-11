import time
import uuid

import boto3

from swerex import PACKAGE_NAME, REMOTE_EXECUTABLE_NAME
from swerex.deployment.abstract import AbstractDeployment, DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.aws import (
    get_cloudwatch_log_url,
    get_cluster_arn,
    get_container_name,
    get_default_vpc_and_subnet,
    get_execution_role_arn,
    get_public_ip,
    get_security_group,
    get_task_definition,
    run_fargate_task,
)
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive


class FargateDeployment(AbstractDeployment):
    def __init__(
        self,
        image: str,
        port: int = 8880,
        cluster_name: str = "swe-rex-cluster",
        execution_role_prefix: str = "swe-rex-execution-role",
        task_definition_prefix: str = "swe-rex-task",
        log_group: str | None = "/ecs/swe-rex-deployment",
        security_group_prefix: str = "swe-rex-deployment-sg",
        fargate_args: dict | None = None,
        container_timeout: float = 60 * 15,
        runtime_timeout: float = 30,
    ):
        self._image = image
        self._runtime: RemoteRuntime | None = None
        self._port = port
        self._container_process = None
        self._container_name = None
        if fargate_args is None:
            fargate_args = {}
        self._fargate_args = fargate_args
        self._container_timeout = container_timeout
        self._cluster_name = cluster_name
        self._execution_role_prefix = execution_role_prefix
        self._task_definition_prefix = task_definition_prefix
        self._log_group = log_group
        self._security_group_prefix = security_group_prefix
        self.logger = get_logger("deploy")
        # we need to setup ecs and ec2 to run containers
        self._cluster_arn = None
        self._execution_role_arn = None
        self._vpc_id = None
        self._subnet_id = None
        self._task_arn = None
        self._security_group_id = None
        self._runtime_timeout = runtime_timeout

    def _init_aws(self):
        self._cluster_arn = get_cluster_arn(self._cluster_name)
        self._execution_role_arn = get_execution_role_arn(execution_role_prefix=self._execution_role_prefix)
        self._task_definition = get_task_definition(
            image_name=self._image,
            port=self._port,
            execution_role_arn=self._execution_role_arn,
            task_definition_prefix=self._task_definition_prefix,
            log_group=self._log_group,
        )
        self._vpc_id, self._subnet_id = get_default_vpc_and_subnet()
        self._security_group_id = get_security_group(
            vpc_id=self._vpc_id,
            port=self._port,
            security_group_prefix=self._security_group_prefix,
        )
        self._container_name = get_container_name(self._image)

    def _get_container_name(self) -> str:
        return self._container_name

    @property
    def container_name(self) -> str | None:
        return self._container_name

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive. The return value can be
        tested with bool().

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None or self._task_arn is None:
            raise DeploymentNotStartedError()
        else:
            # check if the task is running
            ecs_client = boto3.client("ecs")
            task_details = ecs_client.describe_tasks(cluster=self._cluster_arn, tasks=[self._task_arn])
            if task_details["tasks"][0]["lastStatus"] != "RUNNING":
                msg = f"Container process not running: {task_details['tasks'][0]['lastStatus']}"
                raise RuntimeError(msg)
        return await self._runtime.is_alive(timeout=timeout)

    async def _wait_until_alive(self, timeout: float | None = None):
        return await _wait_until_alive(self.is_alive, timeout=timeout, function_timeout=self._container_timeout)

    def _get_command(self, *, token: str) -> list[str]:
        main_command = f"{REMOTE_EXECUTABLE_NAME} --port {self._port}"
        fallback_commands = [
            "apt-get update -y",
            "apt-get install pipx -y",
            "pipx ensurepath",
            f"pipx run {PACKAGE_NAME} --port {self._port} --auth-token {token}",
        ]
        fallback_script = " && ".join(fallback_commands)
        # Wrap the entire command in bash -c to ensure timeout applies to everything
        inner_command = f"{main_command} || ( {fallback_script} )"
        full_command = f"timeout {self._container_timeout}s bash -c '{inner_command}'"
        assert full_command.startswith("timeout "), "command must start with timeout!"
        return [full_command]

    def _get_token(self) -> str:
        return str(uuid.uuid4())

    async def start(
        self,
    ):
        """Starts the runtime."""
        self._init_aws()
        self._container_name = self._get_container_name()
        self.logger.info(f"Starting runtime with container name {self._container_name}")
        token = self._get_token()
        self._task_arn = run_fargate_task(
            command=self._get_command(token=token),
            name=self._container_name,
            task_definition_arn=self._task_definition["taskDefinitionArn"],
            subnet_id=self._subnet_id,
            security_group_id=self._security_group_id,
            cluster_arn=self._cluster_arn,
            **self._fargate_args,
        )
        self.logger.info(f"Container task submitted: {self._task_arn} - waiting for it to start...")
        # wait until the container is running
        t0 = time.time()
        ecs_client = boto3.client("ecs")
        waiter = ecs_client.get_waiter("tasks_running")
        waiter.wait(cluster=self._cluster_arn, tasks=[self._task_arn])
        self.logger.info(f"Fargate container started in {time.time() - t0:.2f}s")
        if self._log_group:
            try:
                log_url = get_cloudwatch_log_url(
                    task_arn=self._task_arn,
                    task_definition=self._task_definition,
                    container_name=self._container_name,
                )
                self.logger.info(f"Monitor logs at: {log_url}")
            except Exception as e:
                self.logger.warning(f"Failed to get CloudWatch Logs URL: {str(e)}")
        public_ip = get_public_ip(self._task_arn, self._cluster_arn)
        self.logger.info(f"Container public IP: {public_ip}")
        self._runtime = RemoteRuntime(host=public_ip, port=self._port, auth_token=token)
        t0 = time.time()
        await self._wait_until_alive(timeout=self._runtime_timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    async def stop(self):
        """Stops the runtime."""
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None
        if self._task_arn is not None:
            ecs_client = boto3.client("ecs")
            ecs_client.stop_task(task=self._task_arn, cluster=self._cluster_arn)
        self._task_arn = None
        self._container_name = None

    @property
    def runtime(self) -> RemoteRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            msg = "Runtime not started"
            raise RuntimeError(msg)
        return self._runtime
