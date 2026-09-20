import json

import pytest

from swerex.exceptions import BashIncorrectSyntaxError, SwerexException
from swerex.runtime.abstract import _ExceptionTransfer
from swerex.runtime.remote import RemoteRuntime
from swerex.server import exception_handler


async def test_unicode_decode_error_transfer():
    error = UnicodeDecodeError("utf-8", bytes(range(256)), 128, 129, "invalid start byte")
    error.extra_info = {"source": "test"}
    response = await exception_handler(None, error)
    assert response.status_code == 511
    transfer = _ExceptionTransfer(**json.loads(response.body)["swerexception"])
    with pytest.raises(UnicodeDecodeError) as actual:
        RemoteRuntime(auth_token="")._handle_transfer_exception(transfer)
    assert actual.value.args == error.args
    assert str(actual.value) == str(error)
    assert actual.value.extra_info == error.extra_info


@pytest.mark.parametrize(
    ("class_path", "exception_type"),
    [
        ("builtins.FileNotFoundError", FileNotFoundError),
        ("swerex.exceptions.BashIncorrectSyntaxError", BashIncorrectSyntaxError),
        ("builtins.UnicodeDecodeError", SwerexException),
    ],
)
def test_legacy_exception_transfer(class_path, exception_type):
    transfer = _ExceptionTransfer(class_path=class_path, message="original message", extra_info={"source": "test"})
    with pytest.raises(exception_type, match="original message") as actual:
        RemoteRuntime(auth_token="")._handle_transfer_exception(transfer)
    assert actual.value.extra_info == transfer.extra_info


def test_malformed_unicode_decode_error_transfer():
    transfer = _ExceptionTransfer(
        class_path="builtins.UnicodeDecodeError",
        message="original message",
        unicode_decode_error={"encoding": "utf-8", "object_hex": "not hex", "start": 0, "end": 1, "reason": "invalid"},
    )
    with pytest.raises(SwerexException, match="original message"):
        RemoteRuntime(auth_token="")._handle_transfer_exception(transfer)
