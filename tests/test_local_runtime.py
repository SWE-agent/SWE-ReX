from pathlib import Path

import pytest

from swerex.exceptions import BashIncorrectSyntaxError, CommandTimeoutError
from swerex.runtime.abstract import (
    BashAction,
    BashInterruptAction,
    CreateBashSessionRequest,
    ReadFileRequest,
    UploadRequest,
)
from swerex.runtime.local import LocalRuntime, _check_bash_command

# The examples from https://github.com/SWE-agent/SWE-ReX/issues/286
SYNTAX_ERRORS = ["echo 'unclosed quote", "if [ -f file ]; then echo 1", "cat file | | grep pattern"]


@pytest.fixture
def local_runtime():
    return LocalRuntime()


@pytest.fixture
async def session_in_tmp_path(local_runtime: LocalRuntime, tmp_path: Path):
    """A session whose working directory contains only `a.txt`, so that globs have a known result."""
    (tmp_path / "a.txt").touch()
    await local_runtime.create_session(CreateBashSessionRequest())
    await local_runtime.run_in_session(BashAction(command=f"cd {tmp_path}", check="raise"))
    yield local_runtime
    await local_runtime.close()


def test_check_bash_command_accepts_extglob_if_it_will_be_active():
    _check_bash_command("shopt -s extglob\necho !(zzz)")
    _check_bash_command("echo !(zzz)", session_has_extglob=lambda: True)


def test_check_bash_command_rejects_extglob_if_it_will_not_be_active():
    with pytest.raises(BashIncorrectSyntaxError):
        _check_bash_command("echo !(zzz)")


@pytest.mark.parametrize("name", ["foo+", "foo@", "foo!", "foo?", "foo*"])
def test_check_bash_command_accepts_function_names_only_valid_without_extglob(name: str):
    _check_bash_command(f"{name}() {{ echo hi; }}")


@pytest.mark.parametrize("command", SYNTAX_ERRORS)
def test_check_bash_command_rejects_syntax_errors_by_default(command: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SWEREX_DISABLE_SYNTAX_CHECK", raising=False)
    with pytest.raises(BashIncorrectSyntaxError):
        _check_bash_command(command)


@pytest.mark.parametrize("command", SYNTAX_ERRORS)
def test_check_bash_command_disabled_by_env_var(command: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SWEREX_DISABLE_SYNTAX_CHECK", "1")
    _check_bash_command(command)


@pytest.mark.parametrize("value", ["0", "", "true", "yes", " 1", "01"])
def test_check_bash_command_only_disabled_by_exact_value(value: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SWEREX_DISABLE_SYNTAX_CHECK", value)
    with pytest.raises(BashIncorrectSyntaxError):
        _check_bash_command("(a")


async def test_extglob_runs_after_enabling_it_in_session(session_in_tmp_path: LocalRuntime):
    await session_in_tmp_path.run_in_session(BashAction(command="shopt -s extglob", check="raise"))
    r = await session_in_tmp_path.run_in_session(BashAction(command="echo !(zzz)", check="raise", timeout=5))
    assert "a.txt" in r.output


async def test_extglob_runs_when_enabled_by_same_command(session_in_tmp_path: LocalRuntime):
    r = await session_in_tmp_path.run_in_session(
        BashAction(command="shopt -s extglob\necho !(zzz)", check="raise", timeout=5)
    )
    assert "a.txt" in r.output


async def test_extglob_without_shopt_is_rejected_as_a_whole(session_in_tmp_path: LocalRuntime, tmp_path: Path):
    """Otherwise bash would reject the first line and run the second one in the wrong directory."""
    with pytest.raises(BashIncorrectSyntaxError):
        await session_in_tmp_path.run_in_session(BashAction(command="cd @(nosuch)\ntouch created", timeout=5))
    assert not (tmp_path / "created").exists()
    r = await session_in_tmp_path.run_in_session(BashAction(command="echo alive", check="raise", timeout=5))
    assert "alive" in r.output


async def test_disabled_check_returns_raw_shell_error(
    session_in_tmp_path: LocalRuntime, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("SWEREX_DISABLE_SYNTAX_CHECK", "1")
    r = await session_in_tmp_path.run_in_session(
        BashAction(command="cat file | | grep pattern", check="silent", timeout=5)
    )
    assert "syntax error" in r.output
    assert r.exit_code not in (0, None)
    r = await session_in_tmp_path.run_in_session(BashAction(command="echo alive", check="raise", timeout=5))
    assert "alive" in r.output


@pytest.mark.parametrize("command", ["echo 'unclosed quote", "if [ -f file ]; then echo 1"])
async def test_disabled_check_times_out_on_incomplete_command(
    command: str, session_in_tmp_path: LocalRuntime, monkeypatch: pytest.MonkeyPatch
):
    """This is the risk documented in `_check_bash_command`: bash waits for the rest of the command."""
    monkeypatch.setenv("SWEREX_DISABLE_SYNTAX_CHECK", "1")
    with pytest.raises(CommandTimeoutError):
        await session_in_tmp_path.run_in_session(BashAction(command=command, check="silent", timeout=0.5))
    await session_in_tmp_path.run_in_session(BashInterruptAction())
    r = await session_in_tmp_path.run_in_session(BashAction(command="echo alive", check="raise", timeout=5))
    assert "alive" in r.output


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
