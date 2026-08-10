"""Pruebas de los modelos inmutables del Registro (Subetapa 06.4)."""

from __future__ import annotations

import pytest

from tools.registry.models import (
    RegistryKeyInfo,
    RegistryKeyPath,
    RegistrySubKey,
    RegistryValue,
    RegistryValueInfo,
)


def test_registry_key_path_immutability() -> None:
    kp = RegistryKeyPath(hive="HKEY_CURRENT_USER", sub_key_path="Software\\JessycaMCP")
    assert kp.hive == "HKEY_CURRENT_USER"
    assert kp.full_path() == "HKEY_CURRENT_USER\\Software\\JessycaMCP"

    with pytest.raises(AttributeError):
        kp.hive = "HKLM"  # type: ignore


def test_registry_models_dict_formatting() -> None:
    val = RegistryValue(name="Version", value_type="REG_SZ", value_data="1.0.0")
    assert val.to_dict()["name"] == "Version"

    sk = RegistrySubKey(name="Settings", sub_key_path="Software\\JessycaMCP\\Settings")
    assert sk.to_dict()["name"] == "Settings"

    ki = RegistryKeyInfo(hive="HKCU", key_path="Software", subkeys_count=2, values_count=5)
    assert ki.to_dict()["subkeys_count"] == 2

    vi = RegistryValueInfo(hive="HKCU", key_path="Software", value_name="Version", value_type="REG_SZ", value_data="1.0")
    assert vi.to_dict()["value_name"] == "Version"
