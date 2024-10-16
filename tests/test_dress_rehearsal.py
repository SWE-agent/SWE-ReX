from pathlib import Path

from swerex.local import RemoteRuntime
from swerex.models import Action, CloseRequest, Command, CreateShellRequest, ReadFileRequest, WriteFileRequest


def test_server_alive(remote_runtime: RemoteRuntime):
    assert remote_runtime.is_alive()


def test_server_dead():
    r = RemoteRuntime("http://doesnotexistadsfasdfasdf234123qw34.com")
    assert not r.is_alive()


def test_read_write_file(remote_runtime: RemoteRuntime, tmp_path: Path):
    path = tmp_path / "test.txt"
    remote_runtime.write_file(WriteFileRequest(path=str(path), content="test"))
    assert path.read_text() == "test"
    assert remote_runtime.read_file(ReadFileRequest(path=str(path))).content == "test"


def test_read_non_existent_file(remote_runtime: RemoteRuntime):
    assert not remote_runtime.read_file(ReadFileRequest(path="non_existent.txt")).success


def test_execute_command(remote_runtime: RemoteRuntime):
    assert remote_runtime.execute(Command(command="echo 'hello world'", shell=True)).stdout == "hello world\n"


def test_execute_command_shell_false(remote_runtime: RemoteRuntime):
    assert remote_runtime.execute(Command(command=["echo", "hello world"], shell=False)).stdout == "hello world\n"


def test_execute_command_timeout(remote_runtime: RemoteRuntime):
    r = remote_runtime.execute(Command(command=["sleep", "10"], timeout=0.1))
    assert not r.success
    assert "timeout" in r.stderr.lower()
    assert not r.stdout


def test_create_close_shell(remote_runtime: RemoteRuntime):
    r = remote_runtime.create_shell(CreateShellRequest())
    assert r.success
    r = remote_runtime.close_shell(CloseRequest())
    assert r.success


def test_run_in_shell(remote_runtime: RemoteRuntime):
    name = "test_run_in_shell"
    r = remote_runtime.create_shell(CreateShellRequest(session=name))
    assert r.success
    r = remote_runtime.run_in_shell(Action(command="echo 'hello world'", session=name))
    assert r.success
    r = remote_runtime.run_in_shell(Action(command="doesntexit", session=name))
    assert not r.success
    r = remote_runtime.close_shell(CloseRequest(session=name))
    assert r.success


def test_run_in_shell_non_existent_session(remote_runtime: RemoteRuntime):
    r = remote_runtime.run_in_shell(Action(command="echo 'hello world'", session="non_existent"))
    assert not r.success
    assert "does not exist" in r.failure_reason


def test_close_shell_non_existent_session(remote_runtime: RemoteRuntime):
    r = remote_runtime.close_shell(CloseRequest(session="non_existent"))
    assert not r.success
    assert "does not exist" in r.failure_reason


def test_close_shell_twice(remote_runtime: RemoteRuntime):
    r = remote_runtime.create_shell(CreateShellRequest())
    assert r.success
    r = remote_runtime.close_shell(CloseRequest())
    assert r.success
    r = remote_runtime.close_shell(CloseRequest())
    assert not r.success
    assert "does not exist" in r.failure_reason


def test_run_in_shell_timeout(runtime_with_default_session: RemoteRuntime):
    print("in test")
    r = runtime_with_default_session.run_in_shell(Action(command="sleep 10", timeout=0.1))
    assert not r.success
    assert "timeout" in r.failure_reason
    assert not r.output


def test_run_in_shell_interactive_command(runtime_with_default_session: RemoteRuntime):
    r = runtime_with_default_session.run_in_shell(
        Action(command="python", is_interactive_command=True, expect=[">>> "])
    )
    assert r.success
    r = runtime_with_default_session.run_in_shell(
        Action(command="print('hello world')", is_interactive_command=True, expect=[">>> "])
    )
    assert r.success
    r = runtime_with_default_session.run_in_shell(Action(command="quit()\n", is_interactive_quit=True))
    assert r.success


def test_run_in_shell_multiple_interactive_and_normal_commands(runtime_with_default_session: RemoteRuntime):
    run = runtime_with_default_session
    r = run.run_in_shell(Action(command="ls"))
    assert r.success
    r = run.run_in_shell(Action(command="python", is_interactive_command=True, expect=[">>> "]))
    assert r.success
    r = run.run_in_shell(Action(command="print('hello world')", is_interactive_command=True, expect=[">>> "]))
    assert "hello world" in r.output
    assert r.success
    r = run.run_in_shell(Action(command="quit()\n", is_interactive_quit=True))
    assert r.success
    r = run.run_in_shell(Action(command="echo 'hello world'"))
    assert r.success
    assert "hello world" in r.output
    r = run.run_in_shell(Action(command="python", is_interactive_command=True, expect=[">>> "]))
    assert r.success
    r = run.run_in_shell(Action(command="print('hello world')", is_interactive_command=True, expect=[">>> "]))
    assert r.success
    r = run.run_in_shell(Action(command="quit()\n", is_interactive_quit=True))
    assert r.success
    r = run.run_in_shell(Action(command="echo 'hello world'"))
    assert r.success
    assert "hello world" in r.output


def test_run_in_shell_interactive_command_timeout(runtime_with_default_session: RemoteRuntime):
    r = runtime_with_default_session.run_in_shell(
        Action(command="python", is_interactive_command=True, expect=["WONTHITTHIS"], timeout=0.1)
    )
    assert not r.success
    assert "timeout" in r.failure_reason


def test_write_to_non_existent_directory(remote_runtime: RemoteRuntime, tmp_path: Path):
    non_existent_dir = tmp_path / "non_existent_dir" / "test.txt"
    response = remote_runtime.write_file(WriteFileRequest(path=str(non_existent_dir), content="test"))
    assert response.success


def test_read_large_file(remote_runtime: RemoteRuntime, tmp_path: Path):
    large_file = tmp_path / "large_file.txt"
    content = "x" * 1024 * 1024  # 1 MB of data
    large_file.write_text(content)

    response = remote_runtime.read_file(ReadFileRequest(path=str(large_file)))
    assert response.success
    assert len(response.content) == len(content)


def test_multiple_isolated_shells(remote_runtime: RemoteRuntime):
    shell1 = remote_runtime.create_shell(CreateShellRequest(session="shell1"))
    shell2 = remote_runtime.create_shell(CreateShellRequest(session="shell2"))

    assert shell1.success and shell2.success

    remote_runtime.run_in_shell(Action(command="x=42", session="shell1"))
    remote_runtime.run_in_shell(Action(command="y=24", session="shell2"))

    response1 = remote_runtime.run_in_shell(Action(command="echo $x", session="shell1"))
    response2 = remote_runtime.run_in_shell(Action(command="echo $y", session="shell2"))

    assert response1.output.strip() == "42"
    assert response2.output.strip() == "24"

    response3 = remote_runtime.run_in_shell(Action(command="echo $y", session="shell1"))
    response4 = remote_runtime.run_in_shell(Action(command="echo $x", session="shell2"))

    assert response3.output.strip() == ""
    assert response4.output.strip() == ""

    remote_runtime.close_shell(CloseRequest(session="shell1"))
    remote_runtime.close_shell(CloseRequest(session="shell2"))


def test_empty_command(remote_runtime: RemoteRuntime):
    r = remote_runtime.execute(Command(command="", shell=True))
    assert r.success
    r = remote_runtime.execute(Command(command="\n", shell=True))
    assert r.success


def test_empty_command_in_shell(runtime_with_default_session: RemoteRuntime):
    r = runtime_with_default_session.run_in_shell(
        Action(
            command="",
        )
    )
    assert r.success
    r = runtime_with_default_session.run_in_shell(Action(command="\n"))
    assert r.success
    r = runtime_with_default_session.run_in_shell(Action(command="\n\n \n"))
    assert r.success


def test_command_with_linebreaks(runtime_with_default_session: RemoteRuntime):
    r = runtime_with_default_session.run_in_shell(Action(command="\n echo 'test'\n\n"))
    assert r.success


def test_multiple_commands_with_linebreaks_in_shell(runtime_with_default_session: RemoteRuntime):
    r = runtime_with_default_session.run_in_shell(Action(command="\n\n\n echo 'test1' \n  \n \n echo 'test2' \n\n\n"))
    assert r.success
    assert r.output.splitlines() == ["test1", "test2"]


def test_bash_multiline_command_eof(runtime_with_default_session: RemoteRuntime):
    command = "\n".join(["python <<EOF", "print('hello world')", "print('hello world 2')", "EOF"])
    r = runtime_with_default_session.run_in_shell(Action(command=command))
    assert r.success
    assert "hello world" in r.output
    assert "hello world 2" in r.output


def test_run_in_shell_subshell_command(runtime_with_default_session: RemoteRuntime):
    r = runtime_with_default_session.run_in_shell(Action(command="(sleep 10) &"))
    assert r.success


def test_run_just_comment(runtime_with_default_session: RemoteRuntime):
    r = runtime_with_default_session.run_in_shell(Action(command="# echo 'hello world'"))
    assert r.success
    assert r.output == ""


def test_run_in_shell_multiple_commands(runtime_with_default_session: RemoteRuntime):
    r = runtime_with_default_session.run_in_shell(Action(command="echo 'hello world'; echo 'hello again'"))
    assert r.success
    assert r.output.splitlines() == ["hello world", "hello again"]
    r = runtime_with_default_session.run_in_shell(Action(command="echo 'hello world' && echo 'hello again'"))
    assert r.success
    assert r.output.splitlines() == ["hello world", "hello again"]


def test_run_in_shell_while_loop(runtime_with_default_session: RemoteRuntime):
    r = runtime_with_default_session.run_in_shell(Action(command="for i in {1..3};\n do echo 'hello world';\n done"))
    assert r.success
    assert r.output.splitlines() == ["hello world"] * 3


def test_run_in_shell_bashlex_errors(runtime_with_default_session: RemoteRuntime):
    # One of the bugs in bashlex
    r = runtime_with_default_session.run_in_shell(Action(command="[[ $env == $env ]]"))
    assert r.success
