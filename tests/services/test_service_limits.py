"""Pruebas de límites de consulta de Servicios (Subetapa 06.5)."""

from __future__ import annotations

from tools.services.backend import FakeServicesBackend
from tools.services.models import WindowsServiceInfo
from tools.services.services_service import ServicesService


def test_services_list_limit_enforcement() -> None:
    fake = FakeServicesBackend()
    # Insertar 20 servicios
    for i in range(20):
        fake.set_service(
            WindowsServiceInfo(
                service_name=f"Service_{i}",
                display_name=f"Test Service {i}",
                status="running",
                start_type="automatic",
                service_type="own_process",
            )
        )

    service = ServicesService(backend=fake)
    service.max_list_entries = 5

    res = service.list_services(limit=5)
    assert res.count == 5
    assert res.truncated is True
