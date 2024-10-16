from pydantic import BaseModel


class CreateShellRequest(BaseModel):
    session: str = "default"


class CreateShellResponse(BaseModel):
    success: bool = True
    failure_reason: str = ""
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
    output: str
    # The output of an interactive command will always be set to -400.
    exit_code_raw: str = ""
    failure_reason: str = ""
    # Which of the expect strings was matched to terminate the command.
    # Empty string if the command timed out.
    expect_string: str = ""

    @property
    def exit_code(self) -> int:
        try:
            return int(self.exit_code_raw)
        except ValueError:
            return -1

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class CloseRequest(BaseModel):
    session: str = "default"


class CloseResponse(BaseModel):
    success: bool = True
    failure_reason: str = ""


class Command(BaseModel):
    command: str | list[str]
    timeout: float | None = None
    shell: bool = False


class CommandResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class ReadFileRequest(BaseModel):
    path: str


class ReadFileResponse(BaseModel):
    success: bool = True
    failure_reason: str = ""
    content: str = ""


class WriteFileRequest(BaseModel):
    content: str
    path: str


class WriteFileResponse(BaseModel):
    success: bool = True
    failure_reason: str = ""
