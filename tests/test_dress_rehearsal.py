import asyncio
from pathlib import Path

import pytest

from swerex.runtime.abstract import (
    BashIncorrectSyntaxError,
    CloseSessionRequest,
    CommandTimeoutError,
    CreateSessionRequest,
    ReadFileRequest,
    SessionDoesNotExistError,
    UploadRequest,
    WriteFileRequest,
)
from swerex.runtime.remote import RemoteRuntime

from .conftest import _Action as A
from .conftest import _Command as C


async def test_server_alive(remote_runtime: RemoteRuntime):
    assert await remote_runtime.is_alive()


async def test_server_dead():
    r = RemoteRuntime(host="http://doesnotexistadsfasdfasdf234123qw34.com", auth_token="")
    assert not await r.is_alive()


async def test_read_write_file(remote_runtime: RemoteRuntime, tmp_path: Path):
    path = tmp_path / "test.txt"
    await remote_runtime.write_file(WriteFileRequest(path=str(path), content="test"))
    assert path.read_text() == "test"
    assert (await remote_runtime.read_file(ReadFileRequest(path=str(path)))).content == "test"


async def test_read_non_existent_file(remote_runtime: RemoteRuntime):
    with pytest.raises(FileNotFoundError):
        await remote_runtime.read_file(ReadFileRequest(path="non_existent.txt"))


async def test_execute_command(remote_runtime: RemoteRuntime):
    assert (await remote_runtime.execute(C(command="echo 'hello world'", shell=True))).stdout == "hello world\n"


async def test_execute_command_shell_false(remote_runtime: RemoteRuntime):
    assert (await remote_runtime.execute(C(command=["echo", "hello world"], shell=False))).stdout == "hello world\n"


async def test_execute_command_timeout(remote_runtime: RemoteRuntime):
    with pytest.raises(CommandTimeoutError):
        await remote_runtime.execute(C(command=["sleep", "10"], timeout=0.1))


async def test_create_close_shell(remote_runtime: RemoteRuntime):
    await remote_runtime.create_session(CreateSessionRequest())
    await remote_runtime.close_session(CloseSessionRequest())


async def test_run_in_shell(runtime_with_default_session: RemoteRuntime):
    r = await runtime_with_default_session.run_in_session(A(command="echo 'hello world'"))
    assert r.exit_code == 0
    r = await runtime_with_default_session.run_in_session(A(command="doesntexit"))
    assert r.exit_code == 127
    r = await runtime_with_default_session.run_in_session(A(command="false && true"))
    assert r.exit_code == 1
    r = await runtime_with_default_session.run_in_session(A(command="false || true"))
    assert r.exit_code == 0


async def test_run_in_shell_non_existent_session(remote_runtime: RemoteRuntime):
    with pytest.raises(SessionDoesNotExistError):
        await remote_runtime.run_in_session(A(command="echo 'hello world'", session="non_existent"))


async def test_close_shell_non_existent_session(remote_runtime: RemoteRuntime):
    with pytest.raises(SessionDoesNotExistError):
        await remote_runtime.close_session(CloseSessionRequest(session="non_existent"))


async def test_close_shell_twice(remote_runtime: RemoteRuntime):
    n = "mynewsession"
    await remote_runtime.create_session(CreateSessionRequest(session=n))
    await remote_runtime.close_session(CloseSessionRequest(session=n))
    with pytest.raises(SessionDoesNotExistError):
        await remote_runtime.close_session(CloseSessionRequest(session=n))


async def test_run_in_shell_timeout(runtime_with_default_session: RemoteRuntime):
    with pytest.raises(CommandTimeoutError):
        await runtime_with_default_session.run_in_session(A(command="sleep 10", timeout=0.1))


async def test_run_in_shell_interactive_command(runtime_with_default_session: RemoteRuntime):
    r = await runtime_with_default_session.run_in_session(
        A(command="python", is_interactive_command=True, expect=[">>> "])
    )

    r = await runtime_with_default_session.run_in_session(
        A(command="print('hello world')", is_interactive_command=True, expect=[">>> "])
    )

    r = await runtime_with_default_session.run_in_session(A(command="quit()\n", is_interactive_quit=True))
    assert r.exit_code == 0


async def test_run_in_shell_multiple_interactive_and_normal_commands(runtime_with_default_session: RemoteRuntime):
    run = runtime_with_default_session
    r = await run.run_in_session(A(command="ls"))
    assert r.exit_code == 0
    r = await run.run_in_session(A(command="python", is_interactive_command=True, expect=[">>> "]))

    r = await run.run_in_session(A(command="print('hello world')", is_interactive_command=True, expect=[">>> "]))
    assert "hello world" in r.output

    r = await run.run_in_session(A(command="quit()\n", is_interactive_quit=True))
    assert r.exit_code == 0

    r = await run.run_in_session(A(command="echo 'hello world'"))
    assert r.exit_code == 0
    assert "hello world" in r.output

    r = await run.run_in_session(A(command="python", is_interactive_command=True, expect=[">>> "]))

    r = await run.run_in_session(A(command="print('hello world')", is_interactive_command=True, expect=[">>> "]))

    r = await run.run_in_session(A(command="quit()\n", is_interactive_quit=True))
    assert r.exit_code == 0

    r = await run.run_in_session(A(command="echo 'hello world'"))
    assert r.exit_code == 0
    assert "hello world" in r.output


async def test_run_in_shell_interactive_command_timeout(runtime_with_default_session: RemoteRuntime):
    with pytest.raises(CommandTimeoutError):
        await runtime_with_default_session.run_in_session(
            A(command="python", is_interactive_command=True, expect=["WONTHITTHIS"], timeout=0.1)
        )


async def test_write_to_non_existent_directory(remote_runtime: RemoteRuntime, tmp_path: Path):
    non_existent_dir = tmp_path / "non_existent_dir" / "test.txt"
    await remote_runtime.write_file(WriteFileRequest(path=str(non_existent_dir), content="test"))


async def test_read_large_file(remote_runtime: RemoteRuntime, tmp_path: Path):
    large_file = tmp_path / "large_file.txt"
    content = "x" * 1024 * 1024  # 1 MB of data
    large_file.write_text(content)

    response = await remote_runtime.read_file(ReadFileRequest(path=str(large_file)))
    assert len(response.content) == len(content)


async def test_multiple_isolated_shells(remote_runtime: RemoteRuntime):
    await remote_runtime.create_session(CreateSessionRequest(session="shell1"))
    await remote_runtime.create_session(CreateSessionRequest(session="shell2"))

    await asyncio.gather(
        remote_runtime.run_in_session(A(command="x=42", session="shell1")),
        remote_runtime.run_in_session(A(command="y=24", session="shell2")),
    )

    response1 = await remote_runtime.run_in_session(A(command="echo $x", session="shell1"))
    response2 = await remote_runtime.run_in_session(A(command="echo $y", session="shell2"))

    assert response1.output.strip() == "42"
    assert response2.output.strip() == "24"

    response3 = await remote_runtime.run_in_session(A(command="echo $y", session="shell1"))
    response4 = await remote_runtime.run_in_session(A(command="echo $x", session="shell2"))

    assert response3.output.strip() == ""
    assert response4.output.strip() == ""

    await remote_runtime.close_session(CloseSessionRequest(session="shell1"))
    await remote_runtime.close_session(CloseSessionRequest(session="shell2"))


async def test_empty_command(remote_runtime: RemoteRuntime):
    await remote_runtime.execute(C(command="", shell=True))
    await remote_runtime.execute(C(command="\n", shell=True))


async def test_empty_command_in_shell(runtime_with_default_session: RemoteRuntime):
    r = await runtime_with_default_session.run_in_session(A(command=""))
    assert r.exit_code == 0
    r = await runtime_with_default_session.run_in_session(A(command="\n"))
    assert r.exit_code == 0
    r = await runtime_with_default_session.run_in_session(A(command="\n\n \n"))
    assert r.exit_code == 0


async def test_command_with_linebreaks(runtime_with_default_session: RemoteRuntime):
    await runtime_with_default_session.run_in_session(A(command="\n echo 'test'\n\n"))


async def test_multiple_commands_with_linebreaks_in_shell(runtime_with_default_session: RemoteRuntime):
    r = await runtime_with_default_session.run_in_session(
        A(command="\n\n\n echo 'test1' \n  \n \n echo 'test2' \n\n\n")
    )
    assert r.exit_code == 0
    assert r.output.splitlines() == ["test1", "test2"]


async def test_bash_multiline_command_eof(runtime_with_default_session: RemoteRuntime):
    command = "\n".join(["python <<EOF", "print('hello world')", "print('hello world 2')", "EOF"])
    r = await runtime_with_default_session.run_in_session(A(command=command))
    assert r.exit_code == 0
    assert "hello world" in r.output
    assert "hello world 2" in r.output


async def test_run_in_shell_subshell_command(runtime_with_default_session: RemoteRuntime):
    r = await runtime_with_default_session.run_in_session(A(command="(sleep 10) &"))
    assert r.exit_code == 0


async def test_run_just_comment(runtime_with_default_session: RemoteRuntime):
    r = await runtime_with_default_session.run_in_session(A(command="# echo 'hello world'"))
    assert r.exit_code == 0
    assert r.output == ""


async def test_run_in_shell_multiple_commands(runtime_with_default_session: RemoteRuntime):
    r = await runtime_with_default_session.run_in_session(A(command="echo 'hello world'; echo 'hello again'"))
    assert r.exit_code == 0
    assert r.output.splitlines() == ["hello world", "hello again"]
    r = await runtime_with_default_session.run_in_session(A(command="echo 'hello world' && echo 'hello again'"))
    assert r.exit_code == 0
    assert r.output.splitlines() == ["hello world", "hello again"]


async def test_run_in_shell_while_loop(runtime_with_default_session: RemoteRuntime):
    r = await runtime_with_default_session.run_in_session(A(command="for i in {1..3};\n do echo 'hello world';\n done"))
    assert r.exit_code == 0
    assert r.output.splitlines() == ["hello world"] * 3


async def test_run_in_shell_bashlex_errors(runtime_with_default_session: RemoteRuntime):
    # One of the bugs in bashlex
    r = await runtime_with_default_session.run_in_session(A(command="[[ $env == $env ]]"))
    assert r.exit_code == 0


async def test_run_shell_check_exit_code(runtime_with_default_session: RemoteRuntime):
    r = await runtime_with_default_session.run_in_session(A(command="/bin/bash -n <<'EOF'\necho 'hello world'\nEOF"))
    assert r.exit_code == 0


async def test_with_bashlex_errors(runtime_with_default_session: RemoteRuntime):
    r = await runtime_with_default_session.run_in_session(A(command="echo 'hw';A=();echo 'asdf'"))
    assert r.exit_code == 0
    assert "hw" in r.output
    assert "asdf" in r.output


async def test_upload_file(runtime_with_default_session: RemoteRuntime, tmp_path: Path):
    file_path = tmp_path / "source.txt"
    file_path.write_text("test")
    tmp_target = tmp_path / "target.txt"
    await runtime_with_default_session.upload(UploadRequest(source_path=str(file_path), target_path=str(tmp_target)))
    result = await runtime_with_default_session.read_file(ReadFileRequest(path=str(tmp_target)))
    assert result.content == "test"


async def test_upload_directory(runtime_with_default_session: RemoteRuntime, tmp_path: Path):
    dir_path = tmp_path / "source_dir"
    dir_path.mkdir()
    (dir_path / "file1.txt").write_text("test1")
    (dir_path / "file2.txt").write_text("test2")
    tmp_target = tmp_path / "target_dir"
    await runtime_with_default_session.upload(UploadRequest(source_path=str(dir_path), target_path=str(tmp_target)))

    assert (
        await runtime_with_default_session.read_file(ReadFileRequest(path=str(tmp_target / "file1.txt")))
    ).content == "test1"
    assert (
        await runtime_with_default_session.read_file(ReadFileRequest(path=str(tmp_target / "file2.txt")))
    ).content == "test2"


async def test_fail_bashlex_errors(runtime_with_default_session: RemoteRuntime):
    r = await runtime_with_default_session.run_in_session(A(command="A=(); false"))
    assert r.exit_code == 1
    assert r.output == ""


async def test_check_bash_command_invalid(runtime_with_default_session: RemoteRuntime):
    with pytest.raises(BashIncorrectSyntaxError):
        await runtime_with_default_session.run_in_session(A(command="(a"))
