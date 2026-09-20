import copy
import json
import logging
import pickle

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


@pytest.mark.parametrize("operation", ["copy", "deepcopy", *range(pickle.HIGHEST_PROTOCOL + 1)])
@pytest.mark.parametrize(
    ("encoding", "invalid_content"),
    [("utf-8", b"\xff"), ("utf-7", b"+" + b"A" * 16385 + b"!")],
    ids=["single-byte", "clipped-span"],
)
async def test_truncated_decode_error_reconstruction(http_request, operation, encoding, invalid_content):
    content = b"a" * 5000 + invalid_content + b"b" * 5000
    with pytest.raises(UnicodeDecodeError) as local:
        content.decode(encoding)
    local.value.extra_info = {"source": ["read_file"]}
    response = await exception_handler(http_request, local.value)
    transfer = _ExceptionTransfer(**json.loads(response.body)["swerexception"])
    with pytest.raises(TruncatedUnicodeDecodeError) as remote:
        RemoteRuntime(auth_token="")._handle_transfer_exception(transfer)
    error = remote.value
    error.related = error
    assert error.object_offset > 0
    assert error.original_start == 5000
    assert len(error.object) == 4096
    if encoding == "utf-7":
        assert error.original_end - error.object_offset > len(error.object)
        assert error.end == len(error.object)

    if operation == "copy":
        restored = copy.copy(error)
    elif operation == "deepcopy":
        restored = copy.deepcopy(error)
    else:
        restored = pickle.loads(pickle.dumps(error, protocol=operation))

    assert restored is not error
    assert type(restored) is TruncatedUnicodeDecodeError
    assert isinstance(restored, UnicodeDecodeError)
    assert not isinstance(restored, SwerexException)
    assert restored.args == error.args
    assert str(restored) == str(error)
    for attribute in (
        "encoding",
        "object",
        "start",
        "end",
        "reason",
        "original_start",
        "original_end",
        "object_offset",
        "object_length",
    ):
        assert getattr(restored, attribute) == getattr(error, attribute)
    assert restored.extra_info == error.extra_info
    if operation == "copy":
        assert restored.extra_info is error.extra_info
        assert restored.related is error
    else:
        assert restored.extra_info is not error.extra_info
        assert restored.extra_info["source"] is not error.extra_info["source"]
        assert restored.related is restored


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
