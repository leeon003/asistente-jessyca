"""Pruebas del PathSecurityManager y frontera de Sandbox (Subetapa 06.2)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.filesystem.errors import (
    PathSecurityError,
    PathTraversalError,
    SandboxViolationError,
    UnsupportedPathError,
)
from tools.filesystem.path_security import PathSecurityManager


def test_sandbox_valid_relative_path(tmp_path: Path) -> None:
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    sec = PathSecurityManager(sandbox_root=sandbox_dir)

    res = sec.validate_and_canonicalize("subfolder/file.txt")
    assert res.is_valid is True
    assert res.canonical_path.startswith(str(sandbox_dir.resolve()))


def test_sandbox_violation_absolute_path_outside(tmp_path: Path) -> None:
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    sec = PathSecurityManager(sandbox_root=sandbox_dir)

    with pytest.raises(SandboxViolationError):
        sec.validate_and_canonicalize(str(outside_dir / "secret.txt"))


def test_path_traversal_rejection(tmp_path: Path) -> None:
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    sec = PathSecurityManager(sandbox_root=sandbox_dir)

    with pytest.raises((SandboxViolationError, PathTraversalError)):
        sec.validate_and_canonicalize("../outside.txt")

    with pytest.raises((SandboxViolationError, PathTraversalError)):
        sec.validate_and_canonicalize("folder/../../secret.txt")


def test_null_bytes_rejection(tmp_path: Path) -> None:
    sec = PathSecurityManager(sandbox_root=tmp_path)

    with pytest.raises(UnsupportedPathError):
        sec.validate_and_canonicalize("file.txt\x00.png")


def test_unc_and_extended_paths_rejection(tmp_path: Path) -> None:
    sec = PathSecurityManager(sandbox_root=tmp_path)

    with pytest.raises(UnsupportedPathError):
        sec.validate_and_canonicalize("\\\\server\\share\\file.txt")

    with pytest.raises(UnsupportedPathError):
        sec.validate_and_canonicalize("\\\\?\\C:\\Windows\\System32")
