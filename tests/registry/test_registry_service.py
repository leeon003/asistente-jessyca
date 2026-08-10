"""Pruebas del RegistryService con FakeRegistryBackend (Subetapa 06.4)."""

from __future__ import annotations

import pytest

from tools.registry.backend import FakeRegistryBackend
from tools.registry.errors import RegistryNotFoundError
from tools.registry.registry_service import RegistryService


def test_registry_service_fake_backend_operations() -> None:
    fake = FakeRegistryBackend()
    service = RegistryService(backend=fake)

    # 1. Obtener información de clave
    key_info = service.get_key_info("HKCU", "Software\\JessycaMCP")
    assert key_info.subkeys_count == 2
    assert key_info.values_count == 3

    # 2. Listar subclaves
    subkeys = service.list_subkeys("HKCU", "Software\\JessycaMCP")
    names = [s.name for s in subkeys]
    assert "Settings" in names
    assert "Plugins" in names

    # 3. Listar valores
    values = service.list_values("HKCU", "Software\\JessycaMCP")
    val_names = [v.name for v in values]
    assert "Version" in val_names
    assert "Debug" in val_names

    # 4. Obtener valor específico
    val_info = service.get_value("HKCU", "Software\\JessycaMCP", "Version")
    assert val_info.value_data == "0.6.4"
    assert val_info.value_type == "REG_SZ"


def test_registry_service_not_found_raises_error() -> None:
    fake = FakeRegistryBackend()
    service = RegistryService(backend=fake)

    with pytest.raises(RegistryNotFoundError):
        service.get_key_info("HKCU", "Software\\NonExistentKey")

    with pytest.raises(RegistryNotFoundError):
        service.get_value("HKCU", "Software\\JessycaMCP", "MissingValue")
