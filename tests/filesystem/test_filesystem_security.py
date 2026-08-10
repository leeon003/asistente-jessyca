"""Pruebas de seguridad adversariales del sistema de archivos (Subetapa 06.2)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.filesystem.errors import PathSecurityError, SandboxViolationError, UnsafePathError
from tools.filesystem.path_security import PathSecurityManager


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("SUPER SECRET DATA")

    sec = PathSecurityManager(sandbox_root=sandbox)

    # Crear enlace simbólico dentro del sandbox que apunta fuera
    symlink_path = sandbox / "symlink_outside.txt"
    try:
        os.symlink(str(outside_file), str(symlink_path))
    except (OSError, NotImplementedError):
        pytest.skip("Creación de symlinks no soportada sin privilegios de administrador en este entorno OS.")

    # El PathSecurityManager debe detectar que el realpath del symlink está fuera y denegar
    with pytest.raises((SandboxViolationError, UnsafePathError, PathSecurityError)):
        sec.validate_and_canonicalize("symlink_outside.txt")


def test_absolute_system_paths_rejected(tmp_path: Path) -> None:
    sec = PathSecurityManager(sandbox_root=tmp_path)

    for forbidden_path in (
        "C:\\Windows\\System32\\cmd.exe",
        "C:\\Users",
        "C:\\Program Files",
        "\\\\127.0.0.1\\c$\\secret",
    ):
        with pytest.raises(PathSecurityError):
            sec.validate_and_canonicalize(forbidden_path)
