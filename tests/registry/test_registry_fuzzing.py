"""Pruebas de fuzzing controlado para parámetros de rutas del Registro (Subetapa 06.4)."""

from __future__ import annotations

import pytest

from tools.registry.errors import RegistryError, RegistryPathError
from tools.registry.path_security import RegistryPathSecurityManager


def test_controlled_registry_path_fuzzing() -> None:
    sec = RegistryPathSecurityManager()

    fuzz_payloads = [
        ("", ""),
        (" ", " "),
        ("\x00HKCU", "Software"),
        ("HKCU", "Software\x00\\Secret"),
        ("HKCU", "../../../System"),
        ("INVALID_HIVE", "Software"),
        ("HKCU", "\\".join(["a"] * 50)),  # Deep path
        (None, "Software"),
        ("HKCU", None),
    ]

    for hive, path in fuzz_payloads:
        with pytest.raises((RegistryError, RegistryPathError, ValueError)):
            sec.validate_and_canonicalize(hive, path)
