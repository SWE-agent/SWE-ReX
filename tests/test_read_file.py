from pathlib import Path

import pytest

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
