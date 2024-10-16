import subprocess
import time
from pathlib import Path

import bashlex
import bashlex.ast
import bashlex.errors
import pexpect

from swerex.local import AbstractRuntime
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


def split_bash_command(inpt: str) -> list[str]:
    r"""Split a bash command with linebreaks, escaped newlines, and heredocs into a list of
    individual commands.

    This relies on the bashlex library. It has quite a few bugs, so if we hit a
    parsing error we just return the input unsplit and hope for the best.

    Args:
        inpt: The input string to split into commands.
    Returns:
        A list of commands as strings.

    Examples:

    "cmd1\ncmd2" are two commands
    "cmd1\\\n asdf" is one command (because the linebreak is escaped)
    "cmd1<<EOF\na\nb\nEOF" is one command (because of the heredoc)
    """
    inpt = inpt.strip()
    if not inpt or all(l.strip().startswith("#") for l in inpt.splitlines()):
        # bashlex can't deal with empty strings or the like :/
        return []
    try:
        parsed = bashlex.parse(inpt)
    except bashlex.errors.ParsingError as e:
        print(e)
        print("Return input unsplit; this might cause issues.")
        return [inpt]
    cmd_strings = []

    def find_range(cmd: bashlex.ast.node) -> tuple[int, int]:
        start = cmd.pos[0]  # type: ignore
        end = cmd.pos[1]  # type: ignore
        for part in getattr(cmd, "parts", []):
            part_start, part_end = find_range(part)
            start = min(start, part_start)
            end = max(end, part_end)
        return start, end

    for cmd in parsed:
        start, end = find_range(cmd)
        cmd_strings.append(inpt[start:end])
    return cmd_strings


class Session:
    def __init__(self):
        """This basically represents one REPL that we control.

        It's pretty similar to a `pexpect.REPLWrapper`.
        """
        self._ps1 = "SHELLPS1PREFIX"
        self.shell: pexpect.spawn | None = None

    async def start(self) -> CreateShellResponse:
        self.shell = pexpect.spawn(
            "/bin/bash",
            encoding="utf-8",
            echo=False,
        )
        time.sleep(0.1)
        self.shell.sendline("echo 'fully_initialized'")
        try:
            self.shell.expect("fully_initialized", timeout=1)
        except pexpect.TIMEOUT:
            return CreateShellResponse(success=False, failure_reason="timeout while initializing shell")
        output = self.shell.before
        self.shell.sendline(f"umask 002; export PS1='{self._ps1}'; export PS2=''")
        try:
            self.shell.expect(self._ps1, timeout=1)
        except pexpect.TIMEOUT:
            return CreateShellResponse(success=False, failure_reason="timeout while setting PS1")
        output += "\n---\n" + self.shell.before  # type: ignore
        return CreateShellResponse(output=output)

    async def run(self, action: Action) -> Observation:
        if self.shell is None:
            return Observation(success=False, failure_reason="shell not initialized")
        if not action.is_interactive_command and not action.is_interactive_quit:
            # Running multiple interactive commands by sending them with linebreaks would break things
            # because we get multiple PS1s back to back. Instead we just join them with ;
            individual_commands = split_bash_command(action.command)
            action.command = " ; ".join(individual_commands)
        self.shell.sendline(action.command)
        try:
            expect_strings = action.expect + [self._ps1]
            expect_index = self.shell.expect(expect_strings, timeout=action.timeout)  # type: ignore
            expect_string = expect_strings[expect_index]
        except pexpect.TIMEOUT:
            expect_string = ""
            return Observation(success=False, failure_reason="timeout while running command")
        output: str = self.shell.before  # type: ignore
        if not action.is_interactive_command and not action.is_interactive_quit:
            self.shell.sendline("\necho $?")
            try:
                self.shell.expect(self._ps1, timeout=1)
            except pexpect.TIMEOUT:
                return Observation(success=False, failure_reason="timeout while getting exit code")
            exit_code_raw: str = self.shell.before.strip()  # type: ignore
            # After quitting an interactive session, for some reason we oftentimes get double
            # PS1 for all following commands. So we might need to call expect again.
            # Alternatively we could have probably called `echo <<<$?>>>` or something.
            if not exit_code_raw.strip():
                print("exit_code_raw was empty, trying again")
                self.shell.expect(self._ps1, timeout=1)
                exit_code_raw = self.shell.before.strip()  # type: ignore
        elif action.is_interactive_quit:
            assert not action.is_interactive_command
            exit_code_raw = "0"
            self.shell.setecho(False)
            self.shell.waitnoecho()
            self.shell.sendline("stty -echo; echo 'doneremovingecho'; echo 'doneremovingecho'")
            # Might need two expects for some reason
            print(self.shell.expect("doneremovingecho", timeout=1))
            print(self.shell.expect(self._ps1, timeout=1))
        else:
            # Trouble with echo mode within an interactive session that we
            output = output.lstrip().removeprefix(action.command).strip()
            exit_code_raw = "0"

        try:
            exit_code = int(exit_code_raw)
        except ValueError:
            return Observation(
                output=output, success=False, failure_reason=f"failed to parse exit code from output {exit_code_raw!r}"
            )
        return Observation(output=output, exit_code=exit_code, expect_string=expect_string)

    async def close(self) -> CloseResponse:
        if self.shell is None:
            return CloseResponse()
        self.shell.close()
        self.shell = None
        return CloseResponse()


class Runtime(AbstractRuntime):
    def __init__(self):
        self.sessions: dict[str, Session] = {}

    async def create_shell(self, request: CreateShellRequest) -> CreateShellResponse:
        if request.session in self.sessions:
            return CreateShellResponse(success=False, failure_reason=f"session {request.session} already exists")
        shell = Session()
        self.sessions[request.session] = shell
        return await shell.start()

    async def run_in_shell(self, action: Action) -> Observation:
        if action.session not in self.sessions:
            return Observation(success=False, failure_reason=f"session {action.session!r} does not exist")
        return await self.sessions[action.session].run(action)

    async def close_shell(self, request: CloseRequest) -> CloseResponse:
        if request.session not in self.sessions:
            return CloseResponse(success=False, failure_reason=f"session {request.session!r} does not exist")
        out = await self.sessions[request.session].close()
        del self.sessions[request.session]
        return out

    async def execute(self, command: Command) -> CommandResponse:
        try:
            result = subprocess.run(command.command, shell=command.shell, timeout=command.timeout, capture_output=True)
            return CommandResponse(
                stdout=result.stdout.decode(errors="backslashreplace"),
                stderr=result.stderr.decode(errors="backslashreplace"),
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return CommandResponse(
                failure_reason=f"Timeout ({command.timeout}s) exceeded while running command", success=False
            )
        except Exception as e:
            return CommandResponse(failure_reason=str(e), success=False)

    async def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        try:
            content = Path(request.path).read_text()
            return ReadFileResponse(success=True, content=content)
        except Exception as e:
            return ReadFileResponse(success=False, failure_reason=str(e))

    async def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        Path(request.path).parent.mkdir(parents=True, exist_ok=True)
        Path(request.path).write_text(request.content)
        return WriteFileResponse(success=True)
