import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

import requests

from swerex.runtime.abstract import (
    AbstractRuntime,
    Action,
    CloseSessionRequest,
    CloseSessionResponse,
    Command,
    CommandResponse,
    CreateSessionRequest,
    CreateSessionResponse,
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

__all__ = ["RemoteRuntime"]


class RemoteRuntime(AbstractRuntime):
    def __init__(self, host: str):
        self.host = host
        self.logger = get_logger("RR")

    def _handle_transfer_exception(self, exc_transfer: _ExceptionTransfer):
        if exc_transfer.traceback:
            self.logger.debug("Traceback: %s", exc_transfer.traceback)
        try:
            module, _, exc_name = exc_transfer.class_path.rpartition(".")
            exception = getattr(sys.modules[module], exc_name)
        except AttributeError:
            self.logger.error(f"Unknown exception class: {exc_transfer.class_path!r}")
            raise SweRexception(exc_transfer.message) from None
        raise exception(exc_transfer.message) from None

    def _handle_response_errors(self, response: requests.Response):
        if response.status_code == 511:
            exc_transfer = _ExceptionTransfer(**response.json()["swerexception"])
            self._handle_transfer_exception(exc_transfer)
        response.raise_for_status()

    async def is_alive(self, *, timeout: float | None = None) -> bool:
        try:
            response = requests.get(f"{self.host}", timeout=timeout)
            if response.status_code == 200 and response.json().get("message") == "running":
                return True
            return False
        except requests.RequestException:
            self.logger.error(f"Failed to connect to {self.host}")
            self.logger.error(traceback.format_exc())
            return False

    async def wait_until_alive(self, *, timeout: float | None = None):
        if timeout is None:
            timeout = 10
        end_time = time.time() + timeout
        while time.time() < end_time:
            if await self.is_alive(timeout=0.1):
                return
            time.sleep(0.1)
        msg = "Failed to start runtime"
        raise TimeoutError(msg)

    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        response = requests.post(f"{self.host}/create_session", json=request.model_dump())
        response.raise_for_status()
        return CreateSessionResponse(**response.json())

    async def run_in_session(self, action: Action) -> Observation:
        self.logger.debug("Running action: %s", action)
        response = requests.post(f"{self.host}/run_in_session", json=action.model_dump())
        self._handle_response_errors(response)
        return Observation(**response.json())

    async def close_session(self, request: CloseSessionRequest) -> CloseSessionResponse:
        response = requests.post(f"{self.host}/close_session", json=request.model_dump())
        self._handle_response_errors(response)
        return CloseSessionResponse(**response.json())

    async def execute(self, command: Command) -> CommandResponse:
        response = requests.post(f"{self.host}/execute", json=command.model_dump())
        self._handle_response_errors(response)
        return CommandResponse(**response.json())

    async def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        response = requests.post(f"{self.host}/read_file", json=request.model_dump())
        self._handle_response_errors(response)
        return ReadFileResponse(**response.json())

    async def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        response = requests.post(f"{self.host}/write_file", json=request.model_dump())
        response.raise_for_status()
        return WriteFileResponse(**response.json())

    async def upload(self, request: UploadRequest) -> UploadResponse:
        source = Path(request.source_path)
        if source.is_dir():
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = Path(temp_dir) / f"{source.name}.zip"
                shutil.make_archive(str(zip_path.with_suffix("")), "zip", source)
                files = {"file": zip_path.open("rb")}
                data = {"target_path": request.target_path, "unzip": "true"}
                response = requests.post(f"{self.host}/upload", files=files, data=data)
                self._handle_response_errors(response)
                return UploadResponse(**response.json())
        else:
            files = {"file": source.open("rb")}
            data = {"target_path": request.target_path, "unzip": "false"}
            response = requests.post(f"{self.host}/upload", files=files, data=data)
            self._handle_response_errors(response)
            return UploadResponse(**response.json())

    async def close(self):
        response = requests.post(f"{self.host}/close")
        response.raise_for_status()
