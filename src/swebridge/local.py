#!/usr/bin/env python3

import traceback
from abc import ABC, abstractmethod

import requests

from swebridge.models import (
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


class AbstractRuntime(ABC):
    """This is the main entry point for running stuff

    It keeps track of all the sessions (individual repls) that are currently open.
    """

    @abstractmethod
    def create_shell(self, request: CreateShellRequest) -> CreateShellResponse:
        """Creates a new shell session."""
        pass

    @abstractmethod
    def run_in_shell(self, action: Action) -> Observation:
        """Runs a command in a shell session."""
        pass

    @abstractmethod
    def close_shell(self, request: CloseRequest):
        """Closes a shell session."""
        pass

    @abstractmethod
    def execute(self, command: Command) -> CommandResponse:
        """Executes a command (independent of any shell session)."""
        pass

    @abstractmethod
    def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        """Reads a file"""
        pass

    @abstractmethod
    def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        """Writes a file"""
        pass


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


if __name__ == "__main__":
    runtime = RemoteRuntime("localhost:8000")
    # ----
    # print(runtime.execute(Command(command="ls", shell=True)))
    # ----
    # fmt: off
    # test sessions and commands that run in them
    # print(runtime.is_alive())
    # print(runtime.create_shell(CreateShellRequest()))
    # print(runtime.run_in_shell(Action(command="python", is_interactive_command=True, expect=[">>> "])))
    # print(runtime.run_in_shell(Action(command="print('hello world')", is_interactive_command=True, expect=[">>> "])))
    # print(runtime.run_in_shell(Action(command="quit()\n", is_interactive_quit=True)))
    # print( runtime.run_in_shell( Action( command="touch test && ls",)))
    # print( runtime.run_in_shell( Action( command="echo 'test'",)))
    # print( runtime.run_in_shell( Action( command="echo 'answer'",)))
    # print(runtime.run_in_shell(Action(command="python", is_interactive_command=True, expect=[">>> "])))
    # print(runtime.run_in_shell(Action(command="print('hello world')", is_interactive_command=True, expect=[">>> "])))
    # print(runtime.run_in_shell(Action(command="quit()\n", is_interactive_quit=True)))
    # print( runtime.run_in_shell( Action( command="touch test && ls",)))
    # print( runtime.run_in_shell( Action( command="doesnexist",)))
    # print(runtime.close_shell(CloseRequest()))
    # fmt: on
