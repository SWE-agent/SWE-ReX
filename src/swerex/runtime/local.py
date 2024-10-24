import asyncio
import re
import shutil
import subprocess
import time
from pathlib import Path

import bashlex
import bashlex.ast
import bashlex.errors
import pexpect

from swerex.runtime.abstract import (
    AbstractRuntime,
    Action,
    BashIncorrectSyntaxError,
    CloseResponse,
    CloseSessionRequest,
    CloseSessionResponse,
    Command,
    CommandResponse,
    CommandTimeoutError,
    CreateSessionRequest,
    CreateSessionResponse,
    IsAliveResponse,
    NoExitCodeError,
    Observation,
    ReadFileRequest,
    ReadFileResponse,
    SessionDoesNotExistError,
    SessionExistsError,
    UploadRequest,
    UploadResponse,
    WriteFileRequest,
    WriteFileResponse,
)
from swerex.utils.log import get_logger

__all__ = ["Runtime", "Session"]


def _split_bash_command(inpt: str) -> list[str]:
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


def _strip_control_chars(s: str) -> str:
    ansi_escape = re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]")
    return ansi_escape.sub("", s)


def _check_bash_command(command: str) -> None:
    """Check if a bash command is valid. Raises BashIncorrectSyntaxError if it's not."""
    _unique_string = "SOUNIQUEEOF"
    cmd = f"/bin/bash -n << '{_unique_string}'\n{command}\n{_unique_string}"
    result = subprocess.run(cmd, shell=True, capture_output=True)
    if result.returncode == 0:
        return
    stdout = result.stdout.decode(errors="backslashreplace")
    stderr = result.stderr.decode(errors="backslashreplace")
    msg = (
        f"Error ({result.returncode}) while checking bash command \n{command!r}\n"
        f"Stderr: {stderr!r}\nStdout: {stdout!r}"
    )
    raise BashIncorrectSyntaxError(msg)


class Session:
    _UNIQUE_STRING = "UNIQUESTRING29234"

    def __init__(self, request: CreateSessionRequest):
        """This basically represents one REPL that we control.

        It's pretty similar to a `pexpect.REPLWrapper`.
        """
        self.request = request
        self._ps1 = "SHELLPS1PREFIX"
        self._shell: pexpect.spawn | None = None
        self.logger = get_logger(f"RexS ({request.session})")

    @property
    def shell(self) -> pexpect.spawn:
        if self._shell is None:
            msg = "shell not initialized"
            raise RuntimeError(msg)
        return self._shell

    async def start(self) -> CreateSessionResponse:
        """Spawn the session, source any startupfiles and set the PS1."""
        self._shell = pexpect.spawn(
            "/bin/bash",
            encoding="utf-8",
            echo=False,
        )
        time.sleep(0.1)
        self.shell.sendline(f"echo '{self._UNIQUE_STRING}'")
        try:
            self.shell.expect(self._UNIQUE_STRING, timeout=1)
        except pexpect.TIMEOUT:
            msg = "timeout while initializing shell"
            raise pexpect.TIMEOUT(msg)
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
            msg = "timeout while setting PS1"
            raise pexpect.TIMEOUT(msg)
        output += "\n---\n" + _strip_control_chars(self.shell.before)  # type: ignore
        return CreateSessionResponse(output=output)

    async def run(self, action: Action) -> Observation:
        if self.shell is None:
            msg = "shell not initialized"
            raise RuntimeError(msg)
        if action.is_interactive_command or action.is_interactive_quit:
            return await self._run_interactive(action)
        return await self._run_normal(action)

    async def _run_interactive(self, action: Action) -> Observation:
        """Run an interactive action. This is different because we don't seek to
        the PS1 and don't attempt to get the exit code.
        """
        assert self.shell is not None
        self.shell.sendline(action.command)
        expect_strings = action.expect + [self._ps1]
        try:
            expect_index = self.shell.expect(expect_strings, timeout=action.timeout)  # type: ignore
            matched_expect_string = expect_strings[expect_index]
        except pexpect.TIMEOUT as e:
            msg = f"timeout while running command {action.command!r}"
            raise CommandTimeoutError(msg) from e
        output: str = _strip_control_chars(self.shell.before).strip()  # type: ignore
        if action.is_interactive_quit:
            assert not action.is_interactive_command
            self.shell.setecho(False)
            self.shell.waitnoecho()
            self.shell.sendline(f"stty -echo; echo '{self._UNIQUE_STRING}'")
            # Might need two expects for some reason
            self.shell.expect(self._UNIQUE_STRING, timeout=1)
            self.shell.expect(self._ps1, timeout=1)
        else:
            # Interactive command.
            # For some reason, this often times enables echo mode within the shell.
            output = output.lstrip().removeprefix(action.command).strip()

        return Observation(output=output, exit_code=0, expect_string=matched_expect_string)

    async def _run_normal(self, action: Action) -> Observation:
        """Run a normal action. This is the default mode.

        There are three steps to this:

        1. Check if the command is valid
        2. Execute the command
        3. Get the exit code
        """
        assert self.shell is not None
        _check_bash_command(action.command)
        fallback_terminator = False
        # Running multiple interactive commands by sending them with linebreaks would break things
        # because we get multiple PS1s back to back. Instead we just join them with ;
        # However, sometimes bashlex errors and we can't do this. In this case
        # we add a unique string to the end of the command and then seek to that
        # (which is also somewhat brittle, so we don't do this by default).
        try:
            individual_commands = _split_bash_command(action.command)
        except bashlex.errors.ParsingError as e:
            self.logger.error("Bashlex fail: %s", e)
            action.command += f"\n TMPEXITCODE=$? ; sleep 0.1; echo '{self._UNIQUE_STRING}' ; (exit $TMPEXITCODE)"
            fallback_terminator = True
        else:
            action.command = " ; ".join(individual_commands)
        self.shell.sendline(action.command)
        if not fallback_terminator:
            expect_strings = action.expect + [self._ps1]
        else:
            expect_strings = [self._UNIQUE_STRING]
        try:
            expect_index = self.shell.expect(expect_strings, timeout=action.timeout)  # type: ignore
            matched_expect_string = expect_strings[expect_index]
        except pexpect.TIMEOUT as e:
            msg = f"timeout while running command {action.command!r}"
            raise CommandTimeoutError(msg) from e
        output: str = _strip_control_chars(self.shell.before).strip()  # type: ignore
        self.shell.sendline("\necho $?")
        try:
            self.shell.expect(self._ps1, timeout=1)
        except pexpect.TIMEOUT:
            msg = "timeout while getting exit code"
            raise NoExitCodeError(msg)
        exit_code_raw: str = _strip_control_chars(self.shell.before).strip()  # type: ignore
        # After quitting an interactive session, for some reason we oftentimes get double
        # PS1 for all following commands. So we might need to call expect again.
        # Alternatively we could have probably called `echo <<<$?>>>` or something.
        for _ in range(2):
            # Try 2 more times with very small timeout
            if not exit_code_raw.strip():
                self.logger.warning("exit_code_raw was empty, trying again")
                self.shell.expect(self._ps1, timeout=0.1)
                exit_code_raw = _strip_control_chars(self.shell.before).strip()  # type: ignore

        output = output.replace(self._UNIQUE_STRING, "").replace(self._ps1, "")

        try:
            exit_code = int(exit_code_raw)
        except ValueError as e:
            msg = f"failed to parse exit code from output {exit_code_raw!r} (command: {action.command!r})"
            raise NoExitCodeError(msg) from e
        return Observation(output=output, exit_code=exit_code, expect_string=matched_expect_string)

    async def close(self) -> CloseSessionResponse:
        if self._shell is None:
            return CloseSessionResponse()
        self.shell.close()
        self._shell = None
        return CloseSessionResponse()

    def interact(self) -> None:
        """Enter interactive mode."""
        self.shell.interact()


class Runtime(AbstractRuntime):
    def __init__(self):
        """A Runtime that runs locally and actually executes commands in a shell.
        If you are deploying to Modal/Fargate/etc., this class will be running within the docker container
        on Modal/Fargate/etc.
        """
        self._sessions: dict[str, Session] = {}

    @property
    def sessions(self) -> dict[str, Session]:
        return self._sessions

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        return IsAliveResponse(is_alive=True)

    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        if request.session in self.sessions:
            msg = f"session {request.session} already exists"
            raise SessionExistsError(msg)
        shell = Session(request)
        self.sessions[request.session] = shell
        return await shell.start()

    async def run_in_session(self, action: Action) -> Observation:
        if action.session not in self.sessions:
            msg = f"session {action.session!r} does not exist"
            raise SessionDoesNotExistError(msg)
        return await self.sessions[action.session].run(action)

    async def close_session(self, request: CloseSessionRequest) -> CloseSessionResponse:
        if request.session not in self.sessions:
            msg = f"session {request.session!r} does not exist"
            raise SessionDoesNotExistError(msg)
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
        except subprocess.TimeoutExpired as e:
            msg = f"Timeout ({command.timeout}s) exceeded while running command"
            raise CommandTimeoutError(msg) from e

    async def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        content = Path(request.path).read_text()
        return ReadFileResponse(content=content)

    async def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        Path(request.path).parent.mkdir(parents=True, exist_ok=True)
        Path(request.path).write_text(request.content)
        return WriteFileResponse()

    async def upload(self, request: UploadRequest) -> UploadResponse:
        if Path(request.source_path).is_dir():
            shutil.copytree(request.source_path, request.target_path)
        else:
            shutil.copy(request.source_path, request.target_path)
        return UploadResponse()

    async def close(self) -> CloseResponse:
        await asyncio.gather(*[self.close_session(CloseSessionRequest(session=s)) for s in self.sessions])
        return CloseResponse()
