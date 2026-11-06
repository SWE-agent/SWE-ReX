import logging
import traceback
from pathlib import Path

import pytest

from swerex.exceptions import BashIncorrectSyntaxError, SwerexException
from swerex.runtime.abstract import ReadFileRequest, _ExceptionTransfer
from swerex.runtime.remote import RemoteRuntime

MESSAGE = "original message"
TRACEBACK = 'Traceback (most recent call last):\n  File "remote.py", line 1, in f\nValueError: original message\n'
TRACEBACK_HEADER = "Traceback (most recent call last)"


def _formatted(exc: BaseException) -> str:
    """What `logger.exception` or `traceback.format_exc` show for this exception."""
    return "".join(traceback.format_exception(exc))


def _runtime_logs(runtime: RemoteRuntime, caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Only the client's records: the test server runs in the same process."""
    return [r for r in caplog.records if r.name == runtime.logger.name]


@pytest.fixture
def runtime(caplog: pytest.LogCaptureFixture):
    """Runtime whose logger reports to caplog (`get_logger` sets `propagate = False`)."""
    r = RemoteRuntime(port=1, auth_token="")
    r.logger.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger=r.logger.name)
    try:
        yield r
    finally:
        r.logger.removeHandler(caplog.handler)


@pytest.fixture
def logged_remote_runtime(remote_runtime: RemoteRuntime, caplog: pytest.LogCaptureFixture):
    remote_runtime.logger.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger=remote_runtime.logger.name)
    try:
        yield remote_runtime
    finally:
        remote_runtime.logger.removeHandler(caplog.handler)


@pytest.mark.parametrize(
    ("class_path", "expected_type"),
    [
        pytest.param("builtins.ValueError", ValueError, id="builtin"),
        pytest.param("builtins.ClassThatDoesNotExist", SwerexException, id="missing-builtin"),
        pytest.param("swerex.exceptions.SessionExistsError", ValueError, id="imported-module"),
        pytest.param("swerex.exceptions.BashIncorrectSyntaxError", BashIncorrectSyntaxError, id="custom-constructor"),
        pytest.param("module_that_does_not_exist.SomeError", SwerexException, id="failed-import"),
        pytest.param("swerex.exceptions.ClassThatDoesNotExist", SwerexException, id="missing-class"),
        pytest.param("json.JSONDecodeError", SwerexException, id="incompatible-constructor"),
    ],
)
def test_traceback_is_the_cause_and_not_logged(
    runtime: RemoteRuntime,
    caplog: pytest.LogCaptureFixture,
    class_path: str,
    expected_type: type[Exception],
):
    transfer = _ExceptionTransfer(message=MESSAGE, class_path=class_path, traceback=TRACEBACK)
    with pytest.raises(expected_type) as e:
        runtime._handle_transfer_exception(transfer)
    assert str(e.value) == MESSAGE
    assert TRACEBACK in _formatted(e.value)
    assert not [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert not [r for r in caplog.records if TRACEBACK_HEADER in r.getMessage()]


def test_traceback_is_kept_when_str_escapes_its_argument(runtime: RemoteRuntime):
    transfer = _ExceptionTransfer(message=MESSAGE, class_path="builtins.KeyError", traceback=TRACEBACK)
    with pytest.raises(KeyError) as e:
        runtime._handle_transfer_exception(transfer)
    assert str(e.value) == repr(MESSAGE)
    assert TRACEBACK in _formatted(e.value)


@pytest.mark.parametrize(
    "class_path",
    [
        "builtins.ValueError",
        "swerex.exceptions.BashIncorrectSyntaxError",
        "module_that_does_not_exist.SomeError",
        "swerex.exceptions.ClassThatDoesNotExist",
    ],
)
def test_no_cause_without_traceback(runtime: RemoteRuntime, class_path: str):
    transfer = _ExceptionTransfer(message=MESSAGE, class_path=class_path, traceback="")
    with pytest.raises(Exception) as e:
        runtime._handle_transfer_exception(transfer)
    assert str(e.value) == MESSAGE
    assert e.value.__cause__ is None


def test_nothing_printed_to_stdout(runtime: RemoteRuntime, capsys: pytest.CaptureFixture):
    transfer = _ExceptionTransfer(message=MESSAGE, class_path="builtins.ValueError", traceback=TRACEBACK)
    capsys.readouterr()
    with pytest.raises(ValueError):
        runtime._handle_transfer_exception(transfer)
    assert capsys.readouterr().out == ""


def test_extra_info_reaches_custom_constructor_exception(runtime: RemoteRuntime):
    extra_info = {"bash_stdout": "out", "bash_stderr": "err"}
    transfer = _ExceptionTransfer(
        message=MESSAGE,
        class_path="swerex.exceptions.BashIncorrectSyntaxError",
        traceback=TRACEBACK,
        extra_info=extra_info,
    )
    with pytest.raises(BashIncorrectSyntaxError) as e:
        runtime._handle_transfer_exception(transfer)
    assert e.value.extra_info == extra_info


async def test_exception_raised_on_remote_end_to_end(
    logged_remote_runtime: RemoteRuntime, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture
):
    capsys.readouterr()
    with pytest.raises(FileNotFoundError) as e:
        await logged_remote_runtime.read_file(ReadFileRequest(path="non_existent.txt"))
    assert str(e.value).startswith("[Errno 2] No such file or directory")
    assert TRACEBACK_HEADER not in str(e.value)
    assert "swerex/server.py" in _formatted(e.value) or "swerex\\server.py" in _formatted(e.value)
    assert "builtins FileNotFoundError" not in capsys.readouterr().out
    logs = _runtime_logs(logged_remote_runtime, caplog)
    assert not [r for r in logs if r.levelno >= logging.CRITICAL]
    assert not [r for r in logs if TRACEBACK_HEADER in r.getMessage()]
    request_errors = [r.getMessage() for r in logs if "Error making request" in r.getMessage()]
    assert len(request_errors) == 1
    assert "No such file or directory" in request_errors[0]


async def test_exception_that_cannot_be_rebuilt_end_to_end(
    logged_remote_runtime: RemoteRuntime, caplog: pytest.LogCaptureFixture, tmp_path: Path
):
    """`UnicodeDecodeError` can't be built from just a message, so this reaches the fallback."""
    path = tmp_path / "binary.dat"
    path.write_bytes(b"\xff\xfe\x80\x81")
    with pytest.raises(SwerexException) as e:
        await logged_remote_runtime.read_file(ReadFileRequest(path=str(path)))
    assert TRACEBACK_HEADER not in str(e.value)
    assert "UnicodeDecodeError" in _formatted(e.value)
    logs = _runtime_logs(logged_remote_runtime, caplog)
    assert any("Could not initialize transferred exception" in r.getMessage() for r in logs)
    assert not [r for r in logs if TRACEBACK_HEADER in r.getMessage()]
