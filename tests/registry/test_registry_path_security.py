"""Pruebas de validación de seguridad de rutas del Registro (Subetapa 06.4)."""

from __future__ import annotations

import pytest

from tools.registry.errors import InvalidHiveError, RegistryDepthLimitError, RegistryPathError
from tools.registry.path_security import RegistryPathSecurityManager


def test_registry_path_hive_canonicalization() -> None:
    sec = RegistryPathSecurityManager()

    res1 = sec.validate_and_canonicalize("HKCU", "Software\\Test")
    assert res1.hive == "HKEY_CURRENT_USER"
    assert res1.sub_key_path == "Software\\Test"

    res2 = sec.validate_and_canonicalize("HKLM", "SOFTWARE/Microsoft")
    assert res2.hive == "HKEY_LOCAL_MACHINE"
    assert res2.sub_key_path == "SOFTWARE\\Microsoft"


def test_unauthorized_hive_rejected() -> None:
    sec = RegistryPathSecurityManager()

    with pytest.raises(InvalidHiveError):
        sec.validate_and_canonicalize("HKEY_USERS", "Software")

    with pytest.raises(InvalidHiveError):
        sec.validate_and_canonicalize("HKEY_CLASSES_ROOT", ".txt")


def test_null_bytes_and_depth_limits_rejected() -> None:
    sec = RegistryPathSecurityManager()

    with pytest.raises(RegistryPathError):
        sec.validate_and_canonicalize("HKCU", "Software\x00\\Test")

    deep_path = "\\".join([f"level_{i}" for i in range(15)])
    with pytest.raises(RegistryDepthLimitError):
        sec.validate_and_canonicalize("HKCU", deep_path)
