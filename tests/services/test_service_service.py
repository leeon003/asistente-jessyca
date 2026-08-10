"""Pruebas de ServicesService con FakeServicesBackend (Subetapa 06.5)."""

from __future__ import annotations

import pytest

from tools.services.backend import FakeServicesBackend
from tools.services.errors import ServiceNotFoundError
from tools.services.services_service import ServicesService


def test_services_service_queries() -> None:
    fake = FakeServicesBackend()
    service = ServicesService(backend=fake)

    # Listar servicios
    res = service.list_services(limit=10)
    assert res.count >= 2

    # Obtener servicio
    info = service.get_service("wuauserv")
    assert info.service_name == "wuauserv"

    # Obtener estado
    status = service.get_service_status("Spooler")
    assert status.status_str == "running"

    # Obtener configuración
    cfg = service.get_service_configuration("wuauserv")
    assert cfg["service_name"] == "wuauserv"


def test_services_service_not_found() -> None:
    fake = FakeServicesBackend()
    service = ServicesService(backend=fake)

    with pytest.raises(ServiceNotFoundError):
        service.get_service("MissingService")
