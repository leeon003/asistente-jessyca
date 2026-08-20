"""Pruebas de eliminación segura de archivos (Subetapa 06.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.filesystem.errors import FileNotFoundToolError, FileOperationError
from tools.filesystem.filesystem_service import FilesystemService
from tools.filesystem.path_security import PathSecurityManager


def test_delete_file_success(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    sec = PathSecurityManager(sandbox_root=sandbox)
    service = FilesystemService(path_security_manager=sec)

    service.write_file("temp.txt", "data to delete")
    assert (sandbox / "temp.txt").exists()

    res = service.delete_file("temp.txt")
    assert res.deleted is True
    assert not (sandbox / "temp.txt").exists()


def test_delete_directory_rejected(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    sec = PathSecurityManager(sandbox_root=sandbox)
    service = FilesystemService(path_security_manager=sec)

    service.create_directory("my_dir")

    # Intentar eliminar un directorio debe ser rechazado
    with pytest.raises(FileOperationError):
        service.delete_file("my_dir")


def test_delete_non_existent_file_raises_not_found(tmp_path: Path) -> None:
    sec = PathSecurityManager(sandbox_root=tmp_path)
    service = FilesystemService(path_security_manager=sec)

    with pytest.raises(FileNotFoundToolError):
        service.delete_file("non_existent.txt")
