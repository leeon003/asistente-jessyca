"""Pruebas del backend de Servicios (Subetapa 06.5)."""

from __future__ import annotations

import pytest

from tools.services.backend import FakeServicesBackend
from tools.services.errors import ServiceNotFoundError


def test_fake_services_backend_enumeration_and_lookup() -> None:
    backend = FakeServicesBackend()

    services = backend.enumerate_services(max_services=10)
    assert len(services) >= 2

    info = backend.get_service("wuauserv")
    assert info.display_name == "Windows Update"

    status = backend.get_service_status("Spooler")
    assert status.status_str == "running"

    config = backend.get_service_configuration("wuauserv")
    assert config["service_name"] == "wuauserv"


def test_fake_services_backend_not_found() -> None:
    backend = FakeServicesBackend()

    with pytest.raises(ServiceNotFoundError):
        backend.get_service("NonExistentService")
