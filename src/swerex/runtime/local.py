import re
import subprocess
import time
from pathlib import Path

import bashlex
import bashlex.ast
import bashlex.errors
import pexpect

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


def split_bash_command(inpt: str) -> list[str]:
    r"""Split a bash command with linebreaks, escaped newlines, and heredocs into a list of
    individual commands.

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
    parsed = bashlex.parse(inpt)
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


def strip_control_chars(s: str) -> str:
    ansi_escape = re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]")
    return ansi_escape.sub("", s)


class Session:
    UNIQUE_STRING = "UNIQUESTRING29234"

    def __init__(self, request: CreateShellRequest):
        """This basically represents one REPL that we control.

        It's pretty similar to a `pexpect.REPLWrapper`.
        """
        self.request = request
        self._ps1 = "SHELLPS1PREFIX"
        self.shell: pexpect.spawn | None = None

    async def start(self) -> CreateShellResponse:
        self.shell = pexpect.spawn(
            "/bin/bash",
            encoding="utf-8",
            echo=False,
        )
        time.sleep(0.1)
        self.shell.sendline(f"echo '{self.UNIQUE_STRING}'")
        try:
            self.shell.expect(self.UNIQUE_STRING, timeout=1)
        except pexpect.TIMEOUT:
            return CreateShellResponse(success=False, failure_reason="timeout while initializing shell")
        output = self.shell.before
        cmds = [f"source {path}" for path in self.request.startup_source]
        cmds += [
            f"export PS1='{self._ps1}'",
            "export PS2=''",
            "export PS0=''",
        ]
        cmd = " ; ".join(cmds)
        self.shell.sendline(cmd)
        try:
            self.shell.expect(self._ps1, timeout=1)
        except pexpect.TIMEOUT:
            return CreateShellResponse(success=False, failure_reason="timeout while setting PS1")
        output += "\n---\n" + strip_control_chars(self.shell.before)  # type: ignore
        return CreateShellResponse(output=output)

    async def run(self, action: Action) -> Observation:
        if self.shell is None:
            return Observation(success=False, failure_reason="shell not initialized")
        fallback_terminator = False
        if not action.is_interactive_command and not action.is_interactive_quit:
            # Running multiple interactive commands by sending them with linebreaks would break things
            # because we get multiple PS1s back to back. Instead we just join them with ;
            # However, sometimes bashlex errors and we can't do this. In this case
            # we add a unique string to the end of the command and then seek to that
            # (which is also somewhat brittle, so we don't do this by default).
            try:
                individual_commands = split_bash_command(action.command)
            except bashlex.errors.ParsingError as e:
                print("Bashlex fail:")
                print(e)
                action.command += f"\nsleep 0.1; echo {self.UNIQUE_STRING}"
                fallback_terminator = True
            else:
                action.command = " ; ".join(individual_commands)
        self.shell.sendline(action.command)
        if not fallback_terminator:
            expect_strings = action.expect + [self._ps1]
        else:
            expect_strings = [self.UNIQUE_STRING]
        try:
            expect_index = self.shell.expect(expect_strings, timeout=action.timeout)  # type: ignore
            matched_expect_string = expect_strings[expect_index]
        except pexpect.TIMEOUT:
            matched_expect_string = ""
            return Observation(success=False, failure_reason="timeout while running command")
        output: str = strip_control_chars(self.shell.before).strip()  # type: ignore
        if not action.is_interactive_command and not action.is_interactive_quit:
            self.shell.sendline("\necho $?")
            try:
                self.shell.expect(self._ps1, timeout=1)
            except pexpect.TIMEOUT:
                return Observation(success=False, failure_reason="timeout while getting exit code")
            exit_code_raw: str = strip_control_chars(self.shell.before).strip()  # type: ignore
            # After quitting an interactive session, for some reason we oftentimes get double
            # PS1 for all following commands. So we might need to call expect again.
            # Alternatively we could have probably called `echo <<<$?>>>` or something.
            for _ in range(2):
                # Try 2 more times with very small timeout
                if not exit_code_raw.strip():
                    print("exit_code_raw was empty, trying again")
                    self.shell.expect(self._ps1, timeout=0.1)
                    exit_code_raw = strip_control_chars(self.shell.before).strip()  # type: ignore
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
                output=output,
                success=False,
                failure_reason=f"failed to parse exit code from output {exit_code_raw!r} (command: {action.command!r})",
            )
        return Observation(output=output, exit_code=exit_code, expect_string=matched_expect_string)

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
        shell = Session(request)
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
