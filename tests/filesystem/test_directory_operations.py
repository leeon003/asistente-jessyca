"""Pruebas de operaciones con directorios (Subetapa 06.2)."""

from __future__ import annotations

from pathlib import Path

from tools.filesystem.filesystem_service import FilesystemService
from tools.filesystem.path_security import PathSecurityManager


def test_directory_operations_list_and_create(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    sec = PathSecurityManager(sandbox_root=sandbox)
    service = FilesystemService(path_security_manager=sec)

    # Crear directorios y archivos
    service.create_directory("folder_a/nested")
    service.write_file("folder_a/file1.txt", "data 1")
    service.write_file("folder_a/file2.txt", "data 2")

    listing = service.list_directory("folder_a")
    assert listing.total_entries == 3
    entry_names = [e.name for e in listing.entries]
    assert "nested" in entry_names
    assert "file1.txt" in entry_names
    assert "file2.txt" in entry_names


def test_directory_list_max_entries_limit(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    sec = PathSecurityManager(sandbox_root=sandbox)
    service = FilesystemService(path_security_manager=sec)
    service.max_list_entries = 5

    # Crear 10 archivos
    for i in range(10):
        service.write_file(f"file_{i}.txt", f"data {i}")

    listing = service.list_directory(".")
    assert listing.total_entries == 5  # Bounded to max_list_entries
