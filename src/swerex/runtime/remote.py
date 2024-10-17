import traceback

import requests

from swerex.models import (
    Action,
    CloseRequest,
    CloseResponse,
    Command,
    CommandResponse,
    CreateShellRequest,
    CreateShellResponse,
    Observation,
    ReadFileRequest,
    ReadFileResponse,
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

    def create_shell(self, request: CreateShellRequest) -> CreateShellResponse:
        response = requests.post(f"{self.host}/create_shell", json=request.model_dump())
        response.raise_for_status()
        return CreateShellResponse(**response.json())

    def run_in_shell(self, action: Action) -> Observation:
        print("----")
        print(action)
        response = requests.post(f"{self.host}/run_in_shell", json=action.model_dump())
        response.raise_for_status()
        obs = Observation(**response.json())
        if not obs.success:
            print(f"Command failed: {obs.failure_reason}")
        return obs

    def close_shell(self, request: CloseRequest) -> CloseResponse:
        response = requests.post(f"{self.host}/close_shell", json=request.model_dump())
        response.raise_for_status()
        return CloseResponse(**response.json())

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
