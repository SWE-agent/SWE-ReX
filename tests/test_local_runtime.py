import shlex
import sys
from pathlib import Path

import pexpect
import pytest

from swerex.runtime.abstract import BashAction, CreateBashSessionRequest, ReadFileRequest, UploadRequest
from swerex.runtime.local import LocalRuntime


@pytest.fixture
def local_runtime():
    return LocalRuntime()


async def test_upload_file(local_runtime: LocalRuntime, tmp_path: Path):
    file_path = tmp_path / "source.txt"
    file_path.write_text("test")
    tmp_target = tmp_path / "target.txt"
    await local_runtime.upload(UploadRequest(source_path=str(file_path), target_path=str(tmp_target)))
    assert (await local_runtime.read_file(ReadFileRequest(path=str(tmp_target)))).content == "test"


async def test_upload_directory(local_runtime: LocalRuntime, tmp_path: Path):
    dir_path = tmp_path / "source_dir"
    dir_path.mkdir()
    (dir_path / "file1.txt").write_text("test1")
    (dir_path / "file2.txt").write_text("test2")
    tmp_target = tmp_path / "target_dir"
    await local_runtime.upload(UploadRequest(source_path=str(dir_path), target_path=str(tmp_target)))
    assert (await local_runtime.read_file(ReadFileRequest(path=str(tmp_target / "file1.txt")))).content == "test1"
    assert (await local_runtime.read_file(ReadFileRequest(path=str(tmp_target / "file2.txt")))).content == "test2"


@pytest.fixture
def shell_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Make the spawned shell independent of the machine running the tests.

    An rc file that replaces PS1 hides the stale prompt, and pyrepl is not used with TERM=dumb.
    The .bashrc runs after any system-wide rc file (e.g., Debian's sets PS1 unconditionally).
    """
    (tmp_path / ".bashrc").write_text("PS1='SHELLPS1PREFIX'\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("BASH_SILENCE_DEPRECATION_WARNING", "1")
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("PYTHON_BASIC_REPL", raising=False)
    monkeypatch.delenv("PYTHONSTARTUP", raising=False)
    return tmp_path


def _python_repl_step(command: str) -> BashAction:
    return BashAction(command=command, is_interactive_command=True, expect=[">>> "], timeout=10)


async def _assert_python_repl_works(runtime: LocalRuntime) -> None:
    r = await runtime.run_in_session(_python_repl_step(shlex.quote(sys.executable)))
    assert r.expect_string == ">>> "
    assert r.output.startswith(f"Python {sys.version_info.major}.{sys.version_info.minor}")
    r = await runtime.run_in_session(_python_repl_step("print('hello world')"))
    assert (r.expect_string, r.output) == (">>> ", "hello world")
    r = await runtime.run_in_session(_python_repl_step("print('hello 2')"))
    assert (r.expect_string, r.output) == (">>> ", "hello 2")
    await runtime.run_in_session(BashAction(command="quit()\n", is_interactive_quit=True, timeout=10))
    r = await runtime.run_in_session(BashAction(command="echo back in bash", check="raise", timeout=10))
    assert r.output.strip() == "back in bash"


async def test_no_stale_prompt_with_basic_repl(
    local_runtime: LocalRuntime, shell_env: Path, monkeypatch: pytest.MonkeyPatch
):
    """Isolates the unread startup prompt: the REPL is plain, so only prompt bookkeeping can go wrong."""
    monkeypatch.setenv("PYTHON_BASIC_REPL", "1")
    await local_runtime.create_session(CreateBashSessionRequest())
    await _assert_python_repl_works(local_runtime)
    await local_runtime.close()


async def test_python_repl_output_after_normal_command(local_runtime: LocalRuntime, shell_env: Path):
    """Isolates the Python 3.13+ REPL: a normal command first absorbs any stale prompt."""
    await local_runtime.create_session(CreateBashSessionRequest())
    await local_runtime.run_in_session(BashAction(command="true", check="raise", timeout=10))
    await _assert_python_repl_works(local_runtime)
    await local_runtime.close()


async def test_python_repl_output_on_fresh_session(local_runtime: LocalRuntime, shell_env: Path):
    await local_runtime.create_session(CreateBashSessionRequest())
    await _assert_python_repl_works(local_runtime)
    await local_runtime.close()


async def test_python_repl_output_when_rc_file_replaces_ps1(local_runtime: LocalRuntime, shell_env: Path):
    """Here the startup prompt isn't our PS1, so there is one fewer prompt to consume."""
    (shell_env / ".bashrc").write_text("PS1='custom$ '\n")
    await local_runtime.create_session(CreateBashSessionRequest())
    await _assert_python_repl_works(local_runtime)
    await local_runtime.close()


async def test_first_command_is_not_ended_by_stale_prompt(local_runtime: LocalRuntime, shell_env: Path):
    await local_runtime.create_session(CreateBashSessionRequest())
    r = await local_runtime.run_in_session(BashAction(command="echo hello", check="ignore", timeout=10))
    assert r.output.strip() == "hello"
    await local_runtime.close()


async def test_create_session_output_has_startup_source_output(local_runtime: LocalRuntime, shell_env: Path):
    startup_file = shell_env / "startup.sh"
    startup_file.write_text("echo sourced\nexport FROM_STARTUP=yes\n")
    response = await local_runtime.create_session(CreateBashSessionRequest(startup_source=[str(startup_file)]))
    assert response.output == "sourced"
    r = await local_runtime.run_in_session(BashAction(command="echo $FROM_STARTUP", check="raise", timeout=10))
    assert r.output.strip() == "yes"
    await local_runtime.close()


async def test_failed_create_session_can_be_retried(local_runtime: LocalRuntime, shell_env: Path):
    startup_file = shell_env / "startup.sh"
    startup_file.write_text("sleep 5\n")
    with pytest.raises(pexpect.TIMEOUT):
        await local_runtime.create_session(
            CreateBashSessionRequest(startup_source=[str(startup_file)], startup_timeout=0.5)
        )
    await local_runtime.create_session(CreateBashSessionRequest())
    r = await local_runtime.run_in_session(BashAction(command="echo alive", check="raise", timeout=10))
    assert "alive" in r.output
    await local_runtime.close()


async def test_create_session_output_is_empty_without_startup_output(local_runtime: LocalRuntime, shell_env: Path):
    response = await local_runtime.create_session(CreateBashSessionRequest())
    assert response.output == ""
    await local_runtime.close()


@pytest.mark.parametrize(("user_value", "expected"), [(None, "1"), ("custom", "custom")])
async def test_python_basic_repl_default_respects_user_value(
    local_runtime: LocalRuntime,
    shell_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    user_value: str | None,
    expected: str,
):
    if user_value is not None:
        monkeypatch.setenv("PYTHON_BASIC_REPL", user_value)
    await local_runtime.create_session(CreateBashSessionRequest())
    r = await local_runtime.run_in_session(BashAction(command='echo "$PYTHON_BASIC_REPL"', check="raise", timeout=10))
    assert r.output.strip() == expected
    await local_runtime.close()
