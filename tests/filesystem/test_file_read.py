"""Pruebas de lectura de archivos y límites de tamaño (Subetapa 06.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.filesystem.errors import FileNotFoundToolError, FileSizeLimitError
from tools.filesystem.filesystem_service import FilesystemService
from tools.filesystem.path_security import PathSecurityManager


def test_file_read_success(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    file_path = sandbox / "test.txt"
    file_path.write_text("Hello Jessyca MCP", encoding="utf-8")

    sec = PathSecurityManager(sandbox_root=sandbox)
    service = FilesystemService(path_security_manager=sec)

    res = service.read_file("test.txt")
    assert res.content == "Hello Jessyca MCP"
    assert res.size_bytes == 17


def test_file_read_not_found(tmp_path: Path) -> None:
    sec = PathSecurityManager(sandbox_root=tmp_path)
    service = FilesystemService(path_security_manager=sec)

    with pytest.raises(FileNotFoundToolError):
        service.read_file("missing.txt")


def test_file_read_size_limit_exceeded(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    large_file = sandbox / "large.bin"
    # Escribir 100 KB
    large_file.write_bytes(b"A" * 100 * 1024)

    sec = PathSecurityManager(sandbox_root=sandbox)
    service = FilesystemService(path_security_manager=sec)
    service.max_read_size = 10 * 1024  # 10 KB limit for test

    with pytest.raises(FileSizeLimitError):
        service.read_file("large.bin")
