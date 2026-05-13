"""
Tests for openwandb.storage — file save / read / append / list operations.
"""
import hashlib
import pytest
from openwandb import storage


class TestSaveAndReadFile:
    def test_save_and_read_roundtrip(self, tmp_data_dir):
        content = b"Hello, World!"
        info = storage.save_file("entity1", "proj1", "run1", "hello.txt", content)
        assert info["size"] == len(content)
        assert info["md5"] == hashlib.md5(content).hexdigest()

        result = storage.read_file("entity1", "proj1", "run1", "hello.txt")
        assert result == content

    def test_save_binary_file(self, tmp_data_dir):
        content = bytes(range(256))
        info = storage.save_file("e", "p", "r", "binary.bin", content)
        assert info["size"] == 256
        result = storage.read_file("e", "p", "r", "binary.bin")
        assert result == content

    def test_read_nonexistent_file(self, tmp_data_dir):
        result = storage.read_file("no", "such", "run", "missing.txt")
        assert result is None

    def test_save_file_md5_correct(self, tmp_data_dir):
        content = b"compute my hash"
        expected_md5 = hashlib.md5(content).hexdigest()
        info = storage.save_file("e", "p", "r", "hash.txt", content)
        assert info["md5"] == expected_md5

    def test_save_file_nested_path(self, tmp_data_dir):
        """Filenames with subdirectories should work."""
        content = b"nested content"
        info = storage.save_file("e", "p", "r", "sub/dir/file.txt", content)
        assert info["size"] == len(content)
        result = storage.read_file("e", "p", "r", "sub/dir/file.txt")
        assert result == content


class TestAppendFile:
    def test_append_creates_and_appends(self, tmp_data_dir):
        storage.append_file("e", "p", "r", "log.txt", "line 1\n")
        storage.append_file("e", "p", "r", "log.txt", "line 2\n")
        content = storage.read_file("e", "p", "r", "log.txt")
        assert content is not None
        text = content.decode("utf-8")
        assert "line 1" in text
        assert "line 2" in text


class TestListRunFiles:
    def test_list_files(self, tmp_data_dir):
        storage.save_file("e", "p", "r", "a.txt", b"aaa")
        storage.save_file("e", "p", "r", "b.txt", b"bbbbb")
        files = storage.list_run_files("e", "p", "r")
        assert len(files) == 2
        names = [f["name"] for f in files]
        assert "a.txt" in names
        assert "b.txt" in names
        # Check sizes
        sizes = {f["name"]: f["size"] for f in files}
        assert sizes["a.txt"] == 3
        assert sizes["b.txt"] == 5

    def test_list_files_empty_run(self, tmp_data_dir):
        files = storage.list_run_files("no", "such", "run")
        assert files == []


class TestDirectoryCreation:
    def test_get_run_files_dir_creates_dir(self, tmp_data_dir):
        d = storage.get_run_files_dir("ent", "proj", "run99")
        assert d.exists()
        assert d.is_dir()

    def test_get_artifact_dir_creates_dir(self, tmp_data_dir):
        d = storage.get_artifact_dir("ent", "proj", "my-artifact")
        assert d.exists()
        assert d.is_dir()
