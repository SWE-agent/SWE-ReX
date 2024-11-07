from abc import ABC, abstractmethod
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class IsAliveResponse(BaseModel):
    """Response to the is_alive request.

    You can test the result with bool().
    """

    is_alive: bool

    message: str = ""
    """Error message if is_alive is False."""

    def __bool__(self) -> bool:
        return self.is_alive


class CreateBashSessionRequest(BaseModel):
    startup_source: list[str] = []
    """Source the following files before running commands.
    The reason this gets a special treatment is that these files
    often overwrite PS1, which we need to reset.
    """
    session: str = "default"
    session_type: Literal["bash"] = "bash"


CreateSessionRequest = Annotated[CreateBashSessionRequest, Field(discriminator="session_type")]
"""Union type for all create session requests. Do not use this directly."""


class CreateBashSessionResponse(BaseModel):
    output: str = ""
    """Output from starting the session."""

    session_type: Literal["bash"] = "bash"


CreateSessionResponse = Annotated[CreateBashSessionResponse, Field(discriminator="session_type")]
"""Union type for all create session responses. Do not use this directly."""


# todo: implement non-output-timeout
class BashAction(BaseModel):
    command: str
    """The command to run."""

    session: str = "default"
    """The session to run the command in."""

    timeout: float | None = None
    """The timeout for the command. None means no timeout."""

    is_interactive_command: bool = False
    """For a non-exiting command to an interactive program
    (e.g., gdb), set this to True."""

    is_interactive_quit: bool = False
    """This will disable checking for exit codes, since the command won't terminate.
    If the command is something like "quit" and should terminate the
    interactive program, set this to False.
    """

    check: bool = False
    """Whether to check for the exit code. If True, we will raise a
    `NonZeroExitCodeError` if the command has a non-zero exit code.
    """

    error_msg: str = ""
    """This error message will be used in the `NonZeroExitCodeError` if the
    command has a non-zero exit code and `check` is True.
    """

    expect: list[str] = []
    """Outputs to expect in addition to the PS1"""

    session_type: Literal["bash"] = "bash"
    """Used for type discrimination. Do not change."""


Action = Annotated[BashAction, Field(discriminator="session_type")]
"""Union type for all actions. Do not use this directly."""


class BashObservation(BaseModel):
    output: str = ""
    exit_code: int | None = None
    failure_reason: str = ""

    expect_string: str = ""
    """Which of the expect strings was matched to terminate the command.
    Empty string if the command timed out etc.
    """

    session_type: Literal["bash"] = "bash"


Observation = Annotated[BashObservation, Field(discriminator="session_type")]
"""Union type for all observations. Do not use this directly."""


class CloseBashSessionRequest(BaseModel):
    session: str = "default"
    session_type: Literal["bash"] = "bash"


CloseSessionRequest = Annotated[CloseBashSessionRequest, Field(discriminator="session_type")]
"""Union type for all close session requests. Do not use this directly."""


class CloseBashSessionResponse(BaseModel):
    session_type: Literal["bash"] = "bash"


CloseSessionResponse = Annotated[CloseBashSessionResponse, Field(discriminator="session_type")]
"""Union type for all close session responses. Do not use this directly."""


class Command(BaseModel):
    """A command to run as a subprocess."""

    command: str | list[str]
    """The command to run. Should be a list of strings (recommended because
    of automatic escaping of spaces etc.) unless you set `shell=True`
    (i.e., exactly like with `subprocess.run()`).
    """

    timeout: float | None = None
    """The timeout for the command. None means no timeout."""

    shell: bool = False
    """Same as the `subprocess.run()` `shell` argument."""

    check: bool = False
    """Whether to check for the exit code. If True, we will raise a
    `CommandFailedError` if the command fails.
    """

    error_msg: str = ""
    """This error message will be used in the `NonZeroExitCodeError` if the
    command has a non-zero exit code and `check` is True.
    """


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
    """Helper class to transfer exceptions from the remote runtime to the client."""

    message: str = ""
    class_path: str = ""
    traceback: str = ""


# todo: move?
class SweRexception(Exception):
    """Any exception that is raised by SWE-Rex."""


class SessionNotInitializedError(SweRexception, RuntimeError):
    """Raised if we try to run a command in a shell that is not initialized."""


class NonZeroExitCodeError(SweRexception, RuntimeError):
    """Can be raised if we execute a command in the shell and it has a non-zero exit code."""


class BashIncorrectSyntaxError(SweRexception, RuntimeError):
    """Before running a bash command, we check for syntax errors.
    This is the error message for those syntax errors.
    """


class CommandTimeoutError(SweRexception, RuntimeError, TimeoutError): ...


class NoExitCodeError(SweRexception, RuntimeError): ...


class SessionExistsError(SweRexception, ValueError): ...


class SessionDoesNotExistError(SweRexception, ValueError): ...


class AbstractRuntime(ABC):
    """This is the main entry point for running stuff.

    It keeps track of all the sessions (individual repls) that are currently open.
    """

    @abstractmethod
    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive."""
        pass

    @abstractmethod
    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        """Creates a new session."""
        pass

    @abstractmethod
    async def run_in_session(self, action: Action) -> Observation:
        """Runs a command in a session."""
        pass

    @abstractmethod
    async def close_session(self, request: CloseSessionRequest) -> CloseSessionResponse:
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
