import atexit
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from weakref import WeakSet

from typing_extensions import Self

from swerex import PACKAGE_NAME, REMOTE_EXECUTABLE_NAME
from swerex.deployment.abstract import AbstractDeployment
from swerex.deployment.config import EnrootDeploymentConfig
from swerex.deployment.hooks.abstract import CombinedDeploymentHook, DeploymentHook
from swerex.exceptions import DeploymentNotStartedError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.config import RemoteRuntimeConfig
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.free_port import find_free_port
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive

__all__ = ["EnrootDeployment", "EnrootDeploymentConfig"]


# Global registry for tracking active deployments
_active_deployments: WeakSet = WeakSet()
_cleanup_lock = threading.Lock()
_signal_handlers_registered = False


def _cleanup_all_deployments():
    """Cleanup function called at exit to ensure all jobs are cancelled."""
    with _cleanup_lock:
        deployments_to_cleanup = list(_active_deployments)
        for deployment in deployments_to_cleanup:
            try:
                deployment._cleanup_job()
            except Exception as e:
                logging.getLogger("rex-deploy").warning(f"Error during cleanup: {e}")


def _register_global_signal_handlers():
    """Register signal handlers once in the main thread."""
    global _signal_handlers_registered
    if _signal_handlers_registered:
        return

    try:

        def signal_handler(signum, frame):
            logging.getLogger("rex-deploy").info(f"Received signal {signum}, cleaning up all jobs...")
            _cleanup_all_deployments()
            # Re-raise the signal to continue normal termination
            signal.signal(signum, signal.SIG_DFL)
            signal.raise_signal(signum)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        atexit.register(_cleanup_all_deployments)
        _signal_handlers_registered = True
    except ValueError:
        # Not in main thread, can't register signal handlers
        # Just register atexit handler
        atexit.register(_cleanup_all_deployments)


class EnrootDeployment(AbstractDeployment):
    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ):
        """Deployment using Enroot with Pyxis and Slurm.

        Args:
            **kwargs: Keyword arguments (see `EnrootDeploymentConfig` for details).
        """
        self._config = EnrootDeploymentConfig(**kwargs)
        self._runtime: RemoteRuntime | None = None
        self._job_process = None
        self._job_id: str | None = None
        self.logger = logger or get_logger("rex-deploy")
        self._runtime_timeout = 0.15
        self._hooks = CombinedDeploymentHook()

        # Register this deployment for cleanup tracking
        with _cleanup_lock:
            _active_deployments.add(self)

        # Try to register global signal handlers (will only work in main thread)
        _register_global_signal_handlers()

    def add_hook(self, hook: DeploymentHook):
        self._hooks.add_hook(hook)

    @classmethod
    def from_config(cls, config: EnrootDeploymentConfig) -> Self:
        return cls(**config.model_dump())

    def _get_job_name(self) -> str:
        """Returns a unique job name."""
        return f"{self._config.job_name}-{uuid.uuid4().hex[:8]}"

    @property
    def job_id(self) -> str | None:
        return self._job_id

    @property
    def container_image(self) -> str:
        cleaned_image = self._config.image.split(":", 1)[0].replace("/", "+") + ".sqsh"
        container_path = Path("./images") / cleaned_image
        if Path.exists(container_path):
            return self._config.image
        return str(container_path)

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive."""
        if self._runtime is None:
            msg = "Runtime not started"
            raise RuntimeError(msg)
        if self._job_process is None:
            msg = "Job process not started"
            raise RuntimeError(msg)
        if self._job_process.poll() is not None:
            msg = "Job process terminated."
            output = "stdout:\n" + self._job_process.stdout.read().decode()
            output += "\nstderr:\n" + self._job_process.stderr.read().decode()
            msg += "\n" + output
            raise RuntimeError(msg)

        # Check if Slurm job is still running
        if self._job_id:
            try:
                result = subprocess.run(
                    ["squeue", "-j", self._job_id, "-h", "-o", "%T"], capture_output=True, text=True, timeout=5
                )
                if result.returncode != 0 or not result.stdout.strip():
                    msg = f"Slurm job {self._job_id} is no longer running"
                    raise RuntimeError(msg)
            except subprocess.TimeoutExpired:
                self.logger.warning("Timeout checking Slurm job status")

        return await self._runtime.is_alive(timeout=timeout)

    def _get_job_node(self, job_id: str) -> str | None:
        """Get the node name where the job is running."""
        try:
            result = subprocess.run(
                ["squeue", "-j", job_id, "-h", "-o", "%N"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            self.logger.warning(f"Failed to get node for job {job_id}")
        return None

    async def _wait_until_alive(self, timeout: float = 10.0):
        try:
            return await _wait_until_alive(self.is_alive, timeout=timeout, function_timeout=self._runtime_timeout)
        except TimeoutError as e:
            self.logger.error("Runtime did not start within timeout. Here's the output from the job process.")
            if self._job_process:
                self.logger.error(self._job_process.stdout.read().decode())
                self.logger.error(self._job_process.stderr.read().decode())
            await self.stop()
            raise e

    def _get_token(self) -> str:
        return str(uuid.uuid4())

    def _get_swerex_start_cmd(self, token: str, port: int) -> str:
        """Get the command to start swerex in the container - matches Docker exactly."""
        rex_args = f"--port {port} --auth-token {token}"
        pipx_install = "apt-get update && apt-get install pipx -y && pipx ensurepath"
        return f"{REMOTE_EXECUTABLE_NAME} {rex_args} || ({pipx_install} && pipx run {PACKAGE_NAME} {rex_args})"

    def _create_sbatch_script(self, token: str, port: int) -> str:
        """Create the sbatch script content."""
        job_name = self._get_job_name()

        script_lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name={job_name}",
            f"#SBATCH --nodes={self._config.nodes}",
            f"#SBATCH --ntasks-per-node={self._config.ntasks_per_node}",
            f"#SBATCH --time={self._config.time_limit}",
            "#SBATCH --no-container-mount-home",
            "#SBATCH --container-workdir=/testbed",
        ]

        if self._config.partition:
            script_lines.append(f"#SBATCH --partition={self._config.partition}")

        if self._config.constraint:
            script_lines.append(f"#SBATCH --constraint={self._config.constraint}")

        if hasattr(self._config, "cpus_per_task"):
            script_lines.append(f"#SBATCH --cpus-per-task={self._config.cpus_per_task}")

        if self._config.memory:
            script_lines.append(f"#SBATCH --mem={self._config.memory}")

        if self._config.train_job:
            script_lines.append("#SBATCH --no-requeue")

        # Create logs directory if it doesn't exist
        logs_dir = Path(os.getenv("SWEREX_LOGS_DIR", "logs/slurm"))

        os.makedirs(logs_dir, exist_ok=True)

        output_path = logs_dir / f"{job_name}_%j.out"
        script_lines.append(f"#SBATCH --output={output_path}")

        error_path = logs_dir / f"{job_name}_%j.err"
        script_lines.append(f"#SBATCH --error={error_path}")

        # Add any additional sbatch arguments
        for arg in self._config.sbatch_args:
            if not arg.startswith("#SBATCH"):
                arg = f"#SBATCH {arg}"
            script_lines.append(arg)

        script_lines.extend(
            [
                "",
                "# Export port for the container to use",
                f"export SWEREX_PORT={port}",
                "",
                "# Build srun command with pyxis",
                f"srun --container-image={self.container_image} \\",
            ]
        )

        # Add pyxis container arguments
        pyxis_args = self._config.pyxis_args

        for arg in pyxis_args:
            if not arg.startswith("--container-"):
                arg = f"--container-{arg}"
            script_lines.append(f"    {arg} \\")

        # Add enroot arguments if any
        if self._config.enroot_args:
            for arg in self._config.enroot_args:
                script_lines.append(f"    {arg} \\")

        # Add the command to run
        swerex_cmd = self._get_swerex_start_cmd(token, port)
        script_lines.append(f"    /bin/bash -c '{swerex_cmd}'")

        return "\n".join(script_lines)

    async def start(self):
        """Starts the runtime using sbatch with pyxis and enroot."""
        if self._config.port is None:
            self._config.port = find_free_port()

        token = self._get_token()

        # Create sbatch script
        script_content = self._create_sbatch_script(token, self._config.port)

        self.logger.info(f"Starting Enroot job with image {self._config.image} on port {self._config.port}")
        self.logger.debug(f"Sbatch script:\n{script_content}")

        # Submit the job
        self._hooks.on_custom_step("Submitting Slurm job")
        try:
            result = subprocess.run(["sbatch"], input=script_content, text=True, capture_output=True, timeout=30)

            if result.returncode != 0:
                msg = f"Failed to submit sbatch job: {result.stderr}"
                raise RuntimeError(msg)

            # Extract job ID from sbatch output
            # Typical output: "Submitted batch job 123456"
            output_lines = result.stdout.strip().split("\n")
            job_line = next((line for line in output_lines if "batch job" in line.lower()), "")
            if job_line:
                self._job_id = job_line.split()[-1]
                self.logger.info(f"Submitted Slurm job {self._job_id}")
            else:
                self.logger.warning(f"Could not extract job ID from sbatch output: {result.stdout}")

        except subprocess.TimeoutExpired:
            msg = "Timeout submitting sbatch job"
            raise RuntimeError(msg)
        except subprocess.CalledProcessError as e:
            msg = f"Failed to submit sbatch job: {e.stderr.decode()}"
            raise RuntimeError(msg)

        try:
            # Create a dummy process to track the job
            # We'll use squeue to monitor the job status
            self._job_process = subprocess.Popen(["sleep", "infinity"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            self._hooks.on_custom_step("Starting runtime")

            # Wait for job to start and get the allocated node
            job_node = None
            if self._job_id:
                self.logger.info(f"Waiting for job {self._job_id} to start...")
                start_time = time.time()
                while time.time() - start_time < 3600:  # Wait up to 1 hour
                    job_node = self._get_job_node(self._job_id)
                    if job_node:
                        break
                    time.sleep(2)

                if not job_node:
                    msg = f"Failed to get node for job {self._job_id} after 1 hour"
                    raise RuntimeError(msg)

                self.logger.info(f"Job allocated to node: {job_node}")

            # Use the allocated node as host, fallback to localhost if no job_id
            host = job_node or "localhost"
            self.logger.info(f"Connecting to runtime at {host}:{self._config.port}")

            self._runtime = RemoteRuntime.from_config(
                RemoteRuntimeConfig(host=host, port=self._config.port, timeout=self._runtime_timeout, auth_token=token)
            )

            t0 = time.time()
            await self._wait_until_alive(timeout=self._config.startup_timeout)
            self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

        finally:
            # Clean up job if start fails after sbatch submission
            if self._job_id and self._runtime is None:
                self._cleanup_job()

    def _cleanup_job(self):
        """Cleanup the Slurm job and monitoring process."""
        # Cancel the Slurm job if we have a job ID
        if self._job_id:
            try:
                subprocess.run(["scancel", self._job_id], capture_output=True, timeout=10)
                self.logger.info(f"Cancelled Slurm job {self._job_id}")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                self.logger.warning(f"Failed to cancel Slurm job {self._job_id}: {e}")

            self._job_id = None

        if self._job_process is not None:
            self._job_process.kill()
            try:
                self._job_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.logger.warning("Job monitoring process did not terminate cleanly")
            self._job_process = None

    async def stop(self):
        """Stops the runtime and cancels the Slurm job."""
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

        self._cleanup_job()

        # Remove from active deployments tracking
        with _cleanup_lock:
            _active_deployments.discard(self)

    @property
    def runtime(self) -> RemoteRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime
