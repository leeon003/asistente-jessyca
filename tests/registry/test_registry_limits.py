"""Pruebas de límites de subclaves, valores y tamaño en el Registro (Subetapa 06.4)."""

from __future__ import annotations

from tools.registry.backend import FakeRegistryBackend
from tools.registry.registry_service import RegistryService


def test_registry_subkeys_and_values_limit_enforcement() -> None:
    fake = FakeRegistryBackend()
    # Insertar 20 subclaves y 20 valores
    fake.set_key(
        "HKEY_CURRENT_USER",
        "Software\\LargeKey",
        subkeys=[f"Sub_{i}" for i in range(20)],
        values={f"Val_{i}": ("REG_SZ", f"data_{i}") for i in range(20)},
    )

    service = RegistryService(backend=fake)
    service.max_subkeys = 5
    service.max_values = 5

    subkeys = service.list_subkeys("HKCU", "Software\\LargeKey")
    assert len(subkeys) == 5

    values = service.list_values("HKCU", "Software\\LargeKey")
    assert len(values) == 5
