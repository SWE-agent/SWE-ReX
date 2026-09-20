from pathlib import Path

import pytest

from swerex.exceptions import TruncatedUnicodeDecodeError
from swerex.runtime.abstract import ReadFileRequest
from swerex.runtime.local import LocalRuntime
from swerex.runtime.remote import RemoteRuntime


@pytest.fixture(params=["local", "remote"])
async def file_runtime(request, remote_runtime: RemoteRuntime):
    runtime = LocalRuntime() if request.param == "local" else remote_runtime
    yield runtime
    if request.param == "local":
        await runtime.close()


@pytest.mark.parametrize("errors", [None, "strict"])
@pytest.mark.parametrize(
    ("encoding", "content"),
    [("utf-8", b"before \xde after"), ("utf-16-le", b"a\x00b")],
)
async def test_read_file_decode_error(file_runtime, tmp_path: Path, encoding: str, content: bytes, errors: str | None):
    path = tmp_path / "invalid.txt"
    path.write_bytes(content)
    with pytest.raises(UnicodeDecodeError) as expected:
        path.read_text(encoding=encoding, errors=errors)
    with pytest.raises(UnicodeDecodeError) as actual:
        await file_runtime.read_file(ReadFileRequest(path=str(path), encoding=encoding, errors=errors))
    assert actual.value.args == expected.value.args
    assert str(actual.value) == str(expected.value)


@pytest.mark.parametrize(
    ("encoding", "errors", "content"),
    [
        (None, None, b"plain text"),
        ("utf-8", None, "calf\u00e9".encode()),
        ("latin-1", None, b"calf\xe9"),
        ("utf-8", "replace", b"before \xde after"),
        ("utf-8", "backslashreplace", b"before \xde after"),
        ("utf-8", "ignore", b"before \xde after"),
    ],
)
async def test_read_file_encoding_and_errors(
    file_runtime, tmp_path: Path, encoding: str | None, errors: str | None, content: bytes
):
    path = tmp_path / "test.txt"
    path.write_bytes(content)
    expected = path.read_text(encoding=encoding, errors=errors)
    response = await file_runtime.read_file(ReadFileRequest(path=str(path), encoding=encoding, errors=errors))
    assert response.content == expected


@pytest.mark.parametrize("position", ["first", "middle", "last"])
async def test_large_file_decode_error_is_bounded(remote_runtime: RemoteRuntime, tmp_path: Path, monkeypatch, position):
    length = 16 * 1024 * 1024
    start = {"first": 0, "middle": length // 2, "last": length - 1}[position]
    path = tmp_path / "large-invalid.txt"
    path.write_bytes(b"a" * length)
    with path.open("r+b") as file:
        file.seek(start)
        file.write(b"\xff")

    wire_sizes = []
    handle_response = remote_runtime._handle_response_errors

    async def check_response(response):
        if response.status == 511:
            wire_sizes.append(len(await response.read()))
        await handle_response(response)

    monkeypatch.setattr(remote_runtime, "_handle_response_errors", check_response)
    with pytest.raises(UnicodeDecodeError) as actual:
        await remote_runtime.read_file(ReadFileRequest(path=str(path), encoding="utf-8", errors="strict"))

    error = actual.value
    assert isinstance(error, TruncatedUnicodeDecodeError)
    assert len(wire_sizes) == 1
    assert wire_sizes[0] < 32768
    assert len(error.object) <= 4096
    assert error.object_length == length
    assert error.original_start == start
    assert error.original_end == start + 1
    assert error.encoding == "utf-8"
    assert error.reason == "invalid start byte"
    assert error.object[error.start : error.end] == b"\xff"
    with path.open("rb") as file:
        file.seek(error.object_offset)
        assert error.object == file.read(len(error.object))
    assert "truncated byte context" in str(error)
    assert f"[{start}, {start + 1})" in str(error)
