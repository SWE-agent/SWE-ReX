from pathlib import Path

from swebridge.local import RemoteRuntime
from swebridge.models import Action, CloseRequest, Command, CreateShellRequest, ReadFileRequest, WriteFileRequest


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


def test_run_in_shell_timeout(remote_runtime: RemoteRuntime):
    print("in test")
    r = remote_runtime.create_shell(CreateShellRequest())
    assert r.success
    r = remote_runtime.run_in_shell(Action(command="sleep 10", timeout=0.1))
    assert not r.success
    assert "timeout" in r.failure_reason
    assert not r.output
    r = remote_runtime.close_shell(CloseRequest())
    assert r.success


def test_run_in_shell_interactive_command(remote_runtime: RemoteRuntime):
    r = remote_runtime.create_shell(CreateShellRequest())
    assert r.success
    r = remote_runtime.run_in_shell(Action(command="python", is_interactive_command=True, expect=[">>> "]))
    assert r.success
    r = remote_runtime.run_in_shell(
        Action(command="print('hello world')", is_interactive_command=True, expect=[">>> "])
    )
    assert r.success
    r = remote_runtime.run_in_shell(Action(command="quit()\n", is_interactive_quit=True))
    assert r.success
    r = remote_runtime.close_shell(CloseRequest())
    assert r.success
