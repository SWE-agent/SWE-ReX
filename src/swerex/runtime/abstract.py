from abc import ABC, abstractmethod

from swerex.models import (
    Action,
    CloseSessionRequest,
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


class AbstractRuntime(ABC):
    """This is the main entry point for running stuff

    It keeps track of all the sessions (individual repls) that are currently open.
    """

    @abstractmethod
    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        """Creates a new session."""
        pass

    @abstractmethod
    async def run_in_session(self, action: Action) -> Observation:
        """Runs a command in a session."""
        pass

    @abstractmethod
    async def close_session(self, request: CloseSessionRequest):
        """Closes a shell session."""
        pass

    @abstractmethod
    async def execute(self, command: Command) -> CommandResponse:
        """Executes a command (independent of any shell session)."""
        pass

    @abstractmethod
    async def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        """Reads a file"""
        pass

    @abstractmethod
    async def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        """Writes a file"""
        pass

    @abstractmethod
    async def upload(self, request: UploadRequest) -> UploadResponse:
        """Uploads a file"""
        pass

    @abstractmethod
    async def close(self):
        """Closes the runtime."""
        pass
