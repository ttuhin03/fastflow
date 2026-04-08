"""Tests für Speicher-Statistik und UV-Cache-Hilfsfunktionen."""

from app.api.settings import _directory_size_bytes


def test_directory_size_bytes_missing_dir(tmp_path):
    assert _directory_size_bytes(tmp_path / "does_not_exist") == 0


def test_directory_size_bytes_empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert _directory_size_bytes(d) == 0


def test_directory_size_bytes_sums_files(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    (d / "a.txt").write_bytes(b"hello")
    sub = d / "sub"
    sub.mkdir()
    (sub / "b.txt").write_bytes(b"xx")
    assert _directory_size_bytes(d) == 5 + 2
