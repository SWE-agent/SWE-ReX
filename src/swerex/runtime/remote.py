import shutil
import tempfile
import traceback
from pathlib import Path

import requests

from swerex.models import (
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
    UploadRequest,
    UploadResponse,
    WriteFileRequest,
    WriteFileResponse,
)
from swerex.runtime.abstract import AbstractRuntime


class RemoteRuntime(AbstractRuntime):
    def __init__(self, host: str):
        self.host = host

    def is_alive(self) -> bool:
        try:
            response = requests.get(f"{self.host}")
            if response.status_code == 200 and response.json().get("message") == "running":
                return True
            return False
        except requests.RequestException:
            print(f"Failed to connect to {self.host}")
            print(traceback.format_exc())
            return False

    def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        response = requests.post(f"{self.host}/create_session", json=request.model_dump())
        response.raise_for_status()
        return CreateSessionResponse(**response.json())

    def run_in_session(self, action: Action) -> Observation:
        print("----")
        print(action)
        response = requests.post(f"{self.host}/run_in_session", json=action.model_dump())
        response.raise_for_status()
        obs = Observation(**response.json())
        if not obs.success:
            print(f"Command failed: {obs.failure_reason}")
        return obs

    def close_session(self, request: CloseSessionRequest) -> CloseSessionResponse:
        response = requests.post(f"{self.host}/close_session", json=request.model_dump())
        response.raise_for_status()
        return CloseSessionResponse(**response.json())

    def execute(self, command: Command) -> CommandResponse:
        response = requests.post(f"{self.host}/execute", json=command.model_dump())
        response.raise_for_status()
        return CommandResponse(**response.json())

    def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        response = requests.post(f"{self.host}/read_file", json=request.model_dump())
        response.raise_for_status()
        return ReadFileResponse(**response.json())

    def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        response = requests.post(f"{self.host}/write_file", json=request.model_dump())
        response.raise_for_status()
        return WriteFileResponse(**response.json())

    def upload(self, request: UploadRequest) -> UploadResponse:
        source = Path(request.source_path)
        if source.is_dir():
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = Path(temp_dir) / f"{source.name}.zip"
                shutil.make_archive(str(zip_path.with_suffix("")), "zip", source)
                files = {"file": zip_path.open("rb")}
                data = {"target_path": request.target_path, "unzip": "true"}
                response = requests.post(f"{self.host}/upload", files=files, data=data)
                response.raise_for_status()
                return UploadResponse(**response.json())
        else:
            files = {"file": source.open("rb")}
            data = {"target_path": request.target_path, "unzip": "false"}
            response = requests.post(f"{self.host}/upload", files=files, data=data)
            response.raise_for_status()
            return UploadResponse(**response.json())

    def close(self):
        response = requests.post(f"{self.host}/close")
        response.raise_for_status()
