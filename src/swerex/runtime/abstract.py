from abc import ABC, abstractmethod

from swerex.models import (
    Action,
    CloseRequest,
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
