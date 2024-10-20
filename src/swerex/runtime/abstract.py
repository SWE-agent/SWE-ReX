from abc import ABC, abstractmethod

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    session: str = "default"
    # Source the following files before running commands.
    # The reason this gets a special treatment is that these files
    # often overwrite PS1, which we need to reset.
    startup_source: list[str] = []


class CreateSessionResponse(BaseModel):
    output: str = ""


# todo: implement non-output-timeout
class Action(BaseModel):
    command: str
    session: str = "default"
    timeout: float | None = None
    # For a non-exiting command to an interactive program
    # (e.g., gdb), set this to True.
    # This will disable checking for exit codes, since the command won't terminate.
    # If the command is something like "quit" and should terminate the
    # interactive program, set this to False.
    is_interactive_command: bool = False
    is_interactive_quit: bool = False
    # Outputs to expect in addition to the PS1
    expect: list[str] = []


class Observation(BaseModel):
    output: str = ""
    exit_code: int | None = None
    failure_reason: str = ""
    # Which of the expect strings was matched to terminate the command.
    # Empty string if the command timed out etc.
    expect_string: str = ""


class CloseSessionRequest(BaseModel):
    session: str = "default"


class CloseSessionResponse(BaseModel):
    pass


class Command(BaseModel):
    command: str | list[str]
    timeout: float | None = None
    shell: bool = False


class CommandResponse(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None


class ReadFileRequest(BaseModel):
    path: str


class ReadFileResponse(BaseModel):
    content: str = ""


class WriteFileRequest(BaseModel):
    content: str
    path: str


class WriteFileResponse(BaseModel):
    pass


class UploadRequest(BaseModel):
    source_path: str
    target_path: str


class UploadResponse(BaseModel):
    pass


class CloseResponse(BaseModel):
    pass


class _ExceptionTransfer(BaseModel):
    message: str = ""
    class_path: str = ""
    traceback: str = ""


class SweRexception(RuntimeError): ...


class BashIncorrectSyntaxError(SweRexception, RuntimeError): ...


class UninitializedShellError(SweRexception, ValueError): ...


class CommandTimeoutError(SweRexception, RuntimeError): ...


class NoExitCodeError(SweRexception, RuntimeError): ...


class SessionExistsError(SweRexception, ValueError): ...


class SessionDoesNotExistError(SweRexception, ValueError): ...


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
    async def close(self) -> CloseResponse:
        """Closes the runtime."""
        pass
