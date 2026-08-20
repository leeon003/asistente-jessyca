"""Pruebas de fuzzing controlado sobre el PathSecurityManager (Subetapa 06.2)."""

from __future__ import annotations

from pathlib import Path

from tools.filesystem.errors import FilesystemError, PathSecurityError
from tools.filesystem.path_security import PathSecurityManager


def test_controlled_path_fuzzing(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    sec = PathSecurityManager(sandbox_root=sandbox)

    fuzz_payloads = [
        "",
        " ",
        "\t\n",
        "\x00file.txt",
        "../../../../../../../../Windows/System32/config",
        "....//....//....//Windows",
        "%2e%2e%2f%2e%2e%2fsecret.txt",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "\\\\127.0.0.1\\c$",
        "\\\\?\\C:\\Users\\Administrator",
        "file_\U0001f600.txt",  # Emoji unicode
        "folder/" + "a" * 300 + "/file.txt",  # Ultra long path
    ]

    for payload in fuzz_payloads:
        try:
            res = sec.validate_and_canonicalize(payload)
            # Si se acepta, DEBE residir dentro del sandbox
            assert res.canonical_path.startswith(str(sandbox.resolve()))
        except (PathSecurityError, FilesystemError, ValueError):
            # Rechazo controlado y seguro -> PASS
            pass
