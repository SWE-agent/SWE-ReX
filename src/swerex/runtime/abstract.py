import logging
from abc import ABC, abstractmethod
from typing import Annotated, Any, Literal

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
    startup_timeout: float = 1.0
    """The timeout for the startup commands."""


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

    check: Literal["silent", "raise", "ignore"] = "raise"
    """Whether to check for the exit code.
    If "silent", we will extract the exit code, but not raise any errors. If there is an error extracting the exit code, it will be set to None.
    If "raise", we will raise a `NonZeroExitCodeError` if the command has a non-zero exit code or if there is an error extracting the exit code.
    If "ignore", we will not attempt to extract the exit code, but always leave it as None.
    """

    error_msg: str = ""
    """This error message will be used in the `NonZeroExitCodeError` if the
    command has a non-zero exit code and `check` is True.
    """

    expect: list[str] = []
    """Outputs to expect in addition to the PS1"""

    action_type: Literal["bash"] = "bash"
    """Used for type discrimination. Do not change."""


class BashInterruptAction(BaseModel):
    session: str = "default"

    timeout: float = 0.2
    """The timeout for the command. None means no timeout."""

    n_retry: int = 3
    """How many times to retry quitting."""

    expect: list[str] = []
    """Outputs to expect in addition to the PS1"""

    action_type: Literal["bash_interrupt"] = "bash_interrupt"


Action = Annotated[BashAction | BashInterruptAction, Field(discriminator="action_type")]
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

    env: dict[str, str] | None = None
    """Environment variables to pass to the command."""

    cwd: str | None = None
    """The current working directory to run the command in."""


class CommandResponse(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None


class ReadFileRequest(BaseModel):
    path: str
    """Path to read from."""

    encoding: str | None = None
    """Encoding to use when reading the file. None means default encoding. 
    This is the same as the `encoding` argument of `Path.read_text()`."""

    errors: str | None = None
    """Error handling to use when reading the file. None means default error handling. 
    This is the same as the `errors` argument of `Path.read_text()`."""


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

    extra_info: dict[str, Any] = {}


class AbstractRuntime(ABC):
    """This is the main entry point for running stuff.

    It keeps track of all the sessions (individual repls) that are currently open.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        self.logger: logging.Logger

    @abstractmethod
    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive and running."""
        pass

    @abstractmethod
    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        """Creates a new session (e.g., a bash shell)."""
        pass

    @abstractmethod
    async def run_in_session(self, action: Action) -> Observation:
        """Runs a command in a session (e.g., a bash shell).
        The name of the session is determined by the `session` field in the `Action`.
        """
        pass

    @abstractmethod
    async def close_session(self, request: CloseSessionRequest) -> CloseSessionResponse:
        """Closes a shell session (e.g., a bash shell that we started earlier)."""
        pass

    @abstractmethod
    async def execute(self, command: Command) -> CommandResponse:
        """Executes a command (in a sub-shell, similar to `subprocess.run()`)."""
        pass

    @abstractmethod
    async def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        """Reads a file and returns the content as a string."""
        pass

    @abstractmethod
    async def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        """Writes a string to a file."""
        pass

    @abstractmethod
    async def upload(self, request: UploadRequest) -> UploadResponse:
        """Uploads a file from the local machine to the remote machine."""
        pass

    @abstractmethod
    async def close(self) -> CloseResponse:
        """Closes the runtime."""
        pass
