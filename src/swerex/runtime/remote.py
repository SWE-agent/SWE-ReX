import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel

from swerex.runtime.abstract import (
    AbstractRuntime,
    Action,
    CloseResponse,
    CloseSessionRequest,
    CloseSessionResponse,
    Command,
    CommandResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    IsAliveResponse,
    Observation,
    ReadFileRequest,
    ReadFileResponse,
    SweRexception,
    UploadRequest,
    UploadResponse,
    WriteFileRequest,
    WriteFileResponse,
    _ExceptionTransfer,
)
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive

__all__ = ["RemoteRuntime"]


class RemoteRuntime(AbstractRuntime):
    def __init__(
        self,
        *,
        auth_token: str,
        host: str = "http://127.0.0.1",
        port: int | None = None,
        timeout: float = 0.15,
    ):
        """A runtime that connects to a remote server.

        Args:
            host: The host to connect to.
            port: The port to connect to.
            auth_token: The token to use for authentication
            timeout: The timeout to use for requests.
        """
        self.logger = get_logger("RR")
        if not host.startswith("http"):
            self.logger.warning("Host %s does not start with http, adding http://", host)
            host = f"http://{host}"
        self.host = host
        self.port = port
        self._token = auth_token
        self._timeout = timeout

    def _get_timeout(self, timeout: float | None = None) -> float:
        if timeout is None:
            return self._timeout
        return timeout

    @property
    def _headers(self) -> dict[str, str]:
        """Request headers to use for authentication."""
        if self._token:
            return {"X-API-Key": self._token}
        return {}

    @property
    def _api_url(self) -> str:
        if self.port is None:
            return self.host
        return f"{self.host}:{self.port}"

    def _handle_transfer_exception(self, exc_transfer: _ExceptionTransfer) -> None:
        """Reraise exceptions that were thrown on the remote."""
        if exc_transfer.traceback:
            print("Traceback: ", exc_transfer.traceback, file=sys.stderr)
        try:
            module, _, exc_name = exc_transfer.class_path.rpartition(".")
            exception = getattr(sys.modules[module], exc_name)
        except AttributeError:
            self.logger.error(f"Unknown exception class: {exc_transfer.class_path!r}")
            raise SweRexception(exc_transfer.message) from None
        raise exception(exc_transfer.message) from None

    def _handle_response_errors(self, response: requests.Response) -> None:
        """Raise exceptions found in the request response."""
        if response.status_code == 511:
            exc_transfer = _ExceptionTransfer(**response.json()["swerexception"])
            self._handle_transfer_exception(exc_transfer)
        response.raise_for_status()

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive.

        Internal server errors are thrown, everything else just has us return False
        together with the message.
        """
        try:
            response = requests.get(
                f"{self._api_url}/is_alive", headers=self._headers, timeout=self._get_timeout(timeout)
            )
            if response.status_code == 200:
                return IsAliveResponse(**response.json())
            elif response.status_code == 511:
                exc_transfer = _ExceptionTransfer(**response.json()["swerexception"])
                self._handle_transfer_exception(exc_transfer)
            msg = (
                f"Status code {response.status_code} from {self._api_url}/is_alive. "
                f"Message: {response.json().get('detail')}"
            )
            return IsAliveResponse(is_alive=False, message=msg)
        except requests.RequestException:
            msg = f"Failed to connect to {self.host}\n"
            msg += traceback.format_exc()
            return IsAliveResponse(is_alive=False, message=msg)
        except Exception:
            msg = f"Failed to connect to {self.host}\n"
            msg += traceback.format_exc()
            return IsAliveResponse(is_alive=False, message=msg)

    async def wait_until_alive(self, *, timeout: float = 60.0):
        return await _wait_until_alive(self.is_alive, timeout=timeout)

    def _request(self, endpoint: str, request: BaseModel | None, output_class: Any):
        """Small helper to make requests to the server and handle errors and output."""
        response = requests.post(
            f"{self._api_url}/{endpoint}", json=request.model_dump() if request else None, headers=self._headers
        )
        self._handle_response_errors(response)
        return output_class(**response.json())

    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        """Creates a new session."""
        return self._request("create_session", request, CreateSessionResponse)

    async def run_in_session(self, action: Action) -> Observation:
        """Runs a command in a session."""
        return self._request("run_in_session", action, Observation)

    async def close_session(self, request: CloseSessionRequest) -> CloseSessionResponse:
        """Closes a shell session."""
        return self._request("close_session", request, CloseSessionResponse)

    async def execute(self, command: Command) -> CommandResponse:
        """Executes a command (independent of any shell session)."""
        return self._request("execute", command, CommandResponse)

    async def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        """Reads a file"""
        return self._request("read_file", request, ReadFileResponse)

    async def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        """Writes a file"""
        return self._request("write_file", request, WriteFileResponse)

    async def upload(self, request: UploadRequest) -> UploadResponse:
        """Uploads a file"""
        source = Path(request.source_path).resolve()
        self.logger.debug("Uploading file from %s to %s", request.source_path, request.target_path)
        if source.is_dir():
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = Path(temp_dir) / "zipped_transfer.zip"
                shutil.make_archive(str(zip_path.with_suffix("")), "zip", source)
                self.logger.debug("Created zip file at %s", zip_path)
                files = {"file": zip_path.open("rb")}
                data = {"target_path": request.target_path, "unzip": "true"}
                response = requests.post(f"{self._api_url}/upload", files=files, data=data, headers=self._headers)
                self._handle_response_errors(response)
                return UploadResponse(**response.json())
        elif source.is_file():
            self.logger.debug("Uploading file from %s to %s", source, request.target_path)
            files = {"file": source.open("rb")}
            data = {"target_path": request.target_path, "unzip": "false"}
            response = requests.post(f"{self._api_url}/upload", files=files, data=data, headers=self._headers)
            self._handle_response_errors(response)
            return UploadResponse(**response.json())
        else:
            msg = f"Source path {source} is not a file or directory"
            raise ValueError(msg)

    async def close(self) -> CloseResponse:
        """Closes the runtime."""
        return self._request("close", None, CloseResponse)
