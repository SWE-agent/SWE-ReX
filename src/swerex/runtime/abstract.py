from abc import ABC, abstractmethod

from pydantic import BaseModel


class IsAliveResponse(BaseModel):
    """Response to the is_alive request.

    You can test the result with bool().
    """

    is_alive: bool

    message: str = ""
    """Error message if is_alive is False."""

    def __bool__(self) -> bool:
        return self.is_alive


class CreateSessionRequest(BaseModel):
    session: str = "default"
    """The name of the session to create."""

    startup_source: list[str] = []
    """Source the following files before running commands.
    The reason this gets a special treatment is that these files
    often overwrite PS1, which we need to reset.
    """


class CreateSessionResponse(BaseModel):
    output: str = ""
    """Output from starting the session."""


# todo: implement non-output-timeout
class Action(BaseModel):
    """An action to run in a session."""

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

    expect: list[str] = []
    """Outputs to expect in addition to the PS1"""


class Observation(BaseModel):
    output: str = ""
    exit_code: int | None = None
    failure_reason: str = ""

    expect_string: str = ""
    """Which of the expect strings was matched to terminate the command.
    Empty string if the command timed out etc.
    """


class CloseSessionRequest(BaseModel):
    session: str = "default"


class CloseSessionResponse(BaseModel):
    pass


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


class SweRexception(RuntimeError): ...


class BashIncorrectSyntaxError(SweRexception, RuntimeError):
    """Before running a bash command, we check for syntax errors.
    This is the error message for those syntax errors.
    """


class UninitializedShellError(SweRexception, ValueError): ...


class CommandTimeoutError(SweRexception, RuntimeError): ...


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
