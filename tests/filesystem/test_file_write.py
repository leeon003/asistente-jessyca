"""Pruebas de escritura atómica de archivos (Subetapa 06.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.filesystem.errors import FileSizeLimitError
from tools.filesystem.filesystem_service import FilesystemService
from tools.filesystem.path_security import PathSecurityManager


def test_file_write_success_and_atomic_replace(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    sec = PathSecurityManager(sandbox_root=sandbox)
    service = FilesystemService(path_security_manager=sec)

    # 1. Escritura en archivo nuevo con subdirectorio automático
    res1 = service.write_file("sub/output.txt", "Contenido inicial")
    assert res1.is_new_file is True
    assert res1.bytes_written > 0
    assert (sandbox / "sub" / "output.txt").read_text(encoding="utf-8") == "Contenido inicial"

    # 2. Actualización atómica en archivo existente
    res2 = service.write_file("sub/output.txt", "Contenido actualizado")
    assert res2.is_new_file is False
    assert (sandbox / "sub" / "output.txt").read_text(encoding="utf-8") == "Contenido actualizado"


def test_file_write_size_limit_exceeded(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    sec = PathSecurityManager(sandbox_root=sandbox)
    service = FilesystemService(path_security_manager=sec)
    service.max_write_size = 5 * 1024  # 5 KB limit for test

    large_content = "X" * (10 * 1024)

    with pytest.raises(FileSizeLimitError):
        service.write_file("large.txt", large_content)
