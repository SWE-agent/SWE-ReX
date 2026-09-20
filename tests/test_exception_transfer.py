import json
import logging

import pytest
from starlette.requests import Request

from swerex.exceptions import BashIncorrectSyntaxError, SwerexException, TruncatedUnicodeDecodeError
from swerex.runtime.abstract import _ExceptionTransfer
from swerex.runtime.remote import RemoteRuntime
from swerex.server import exception_handler


@pytest.fixture
def http_request():
    return Request({"type": "http", "method": "POST", "path": "/read_file", "headers": []})


async def test_unicode_decode_error_transfer(http_request):
    error = UnicodeDecodeError("utf-8", bytes(range(256)), 128, 129, "invalid start byte")
    error.extra_info = {"source": "test"}
    response = await exception_handler(http_request, error)
    assert response.status_code == 511
    transfer = _ExceptionTransfer(**json.loads(response.body)["swerexception"])
    with pytest.raises(UnicodeDecodeError) as actual:
        RemoteRuntime(auth_token="")._handle_transfer_exception(transfer)
    assert actual.value.args == error.args
    assert str(actual.value) == str(error)
    assert actual.value.extra_info == error.extra_info
    assert type(actual.value) is UnicodeDecodeError


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


@pytest.mark.parametrize(
    "invalid",
    [
        {"object_hex": "private-file-contents"},
        {"object_hex": "736563726574" * 1000 + "z"},
        {"object_hex": "00" * 4097},
        {"object_hex": "0"},
        {"object_hex": ""},
        {"object_hex": "00 11"},
        {"start": -1},
        {"start": 1, "end": 1},
        {"start": 2, "end": 1},
        {"start": True},
        {"end": 3},
        {"end": 1.5},
        {"end": "1"},
        {"object_offset": -1},
        {"object_offset": 1},
        {"object_offset": 2, "start": 2, "end": 3, "object_length": 3},
        {"start": 2, "end": 3, "object_length": 3},
        {"object_length": 0},
        {"object_length": 1},
    ],
)
def test_malformed_unicode_decode_error_transfer(invalid, caplog):
    data = {
        "encoding": "utf-8",
        "object_hex": "ff00",
        "object_offset": 0,
        "object_length": 2,
        "start": 0,
        "end": 1,
        "reason": "invalid start byte",
    }
    data.update(invalid)
    transfer = _ExceptionTransfer(
        class_path="builtins.UnicodeDecodeError",
        message="original message",
        unicode_decode_error=data,
    )
    with caplog.at_level(logging.ERROR), pytest.raises(SwerexException, match="original message"):
        RemoteRuntime(auth_token="", logger=logging.getLogger(__name__))._handle_transfer_exception(transfer)
    assert "Could not initialize transferred exception" in caplog.text
    assert "object_hex" not in caplog.text
    assert "Transfer object" not in caplog.text
    if len(data["object_hex"]) > 8:
        assert data["object_hex"] not in caplog.text


@pytest.mark.parametrize("length", [4096, 4097, 10000])
@pytest.mark.parametrize("position", ["first", "middle", "last"])
async def test_decode_error_context_boundaries(http_request, length, position):
    start = {"first": 0, "middle": length // 2, "last": length - 1}[position]
    content = b"a" * start + b"\xff" + b"b" * (length - start - 1)
    error = UnicodeDecodeError("utf-8", content, start, start + 1, "invalid start byte")
    response = await exception_handler(http_request, error)
    assert len(response.body) < 10000
    transfer = _ExceptionTransfer(**json.loads(response.body)["swerexception"])
    with pytest.raises(UnicodeDecodeError) as actual:
        RemoteRuntime(auth_token="")._handle_transfer_exception(transfer)
    result = actual.value
    assert result.encoding == error.encoding
    assert result.reason == error.reason
    assert result.object[result.start : result.end] == b"\xff"
    if length <= 4096:
        assert type(result) is UnicodeDecodeError
        assert result.args == error.args
        assert str(result) == str(error)
    else:
        assert isinstance(result, TruncatedUnicodeDecodeError)
        assert result.original_start == start
        assert result.original_end == start + 1
        assert result.object_length == length
        assert result.object == content[result.object_offset : result.object_offset + len(result.object)]
        assert len(result.object) <= 4096
        assert result.start == start - result.object_offset
        assert "truncated byte context" in str(result)
        assert f"[{start}, {start + 1})" in str(result)


async def test_decode_error_span_larger_than_context(http_request):
    content = b"+" + b"A" * 16385 + b"!"
    with pytest.raises(UnicodeDecodeError) as expected:
        content.decode("utf-7")
    response = await exception_handler(http_request, expected.value)
    transfer = _ExceptionTransfer(**json.loads(response.body)["swerexception"])
    with pytest.raises(UnicodeDecodeError) as actual:
        RemoteRuntime(auth_token="")._handle_transfer_exception(transfer)
    result = actual.value
    assert isinstance(result, TruncatedUnicodeDecodeError)
    assert result.reason == expected.value.reason
    assert result.encoding == expected.value.encoding
    assert result.original_start == expected.value.start
    assert result.original_end == expected.value.end
    assert result.original_end > 4096
    assert 0 <= result.start < result.end <= len(result.object) <= 4096
    assert "truncated byte context" in str(result)


async def test_decode_error_subclass_has_no_unused_payload(http_request):
    class CustomDecodeError(UnicodeDecodeError):
        pass

    error = CustomDecodeError("utf-8", b"\xff" * 10000, 0, 1, "invalid start byte")
    response = await exception_handler(http_request, error)
    assert json.loads(response.body)["swerexception"]["unicode_decode_error"] is None
    assert len(response.body) < 1000


async def test_invalid_server_decode_error_preserves_generic_fallback(http_request):
    error = UnicodeDecodeError("utf-8", b"\xff", -1, 2, "invalid start byte")
    response = await exception_handler(http_request, error)
    transfer = _ExceptionTransfer(**json.loads(response.body)["swerexception"])
    with pytest.raises(SwerexException) as actual:
        RemoteRuntime(auth_token="")._handle_transfer_exception(transfer)
    assert str(actual.value) == str(error)
