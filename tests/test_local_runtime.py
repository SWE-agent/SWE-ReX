from pathlib import Path

import pytest

from swerex.runtime.abstract import ReadFileRequest, UploadRequest
from swerex.runtime.local import Runtime


@pytest.fixture
def local_runtime():
    return Runtime()


async def test_upload_file(local_runtime: Runtime, tmp_path: Path):
    file_path = tmp_path / "source.txt"
    file_path.write_text("test")
    tmp_target = tmp_path / "target.txt"
    await local_runtime.upload(UploadRequest(source_path=str(file_path), target_path=str(tmp_target)))
    assert (await local_runtime.read_file(ReadFileRequest(path=str(tmp_target)))).content == "test"


async def test_upload_directory(local_runtime: Runtime, tmp_path: Path):
    dir_path = tmp_path / "source_dir"
    dir_path.mkdir()
    (dir_path / "file1.txt").write_text("test1")
    (dir_path / "file2.txt").write_text("test2")
    tmp_target = tmp_path / "target_dir"
    await local_runtime.upload(UploadRequest(source_path=str(dir_path), target_path=str(tmp_target)))
    assert (await local_runtime.read_file(ReadFileRequest(path=str(tmp_target / "file1.txt")))).content == "test1"
    assert (await local_runtime.read_file(ReadFileRequest(path=str(tmp_target / "file2.txt")))).content == "test2"
