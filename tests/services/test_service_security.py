"""Pruebas de seguridad adversariales de Servicios de Windows (Subetapa 06.5)."""

from __future__ import annotations

import pytest

from server.boundary import ExecutionStatus
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest
from tools.services.backend import FakeServicesBackend
from tools.services.errors import ServiceNameError
from tools.services.executor import WindowsServicesToolExecutor
from tools.services.name_security import ServiceNameSecurityManager
from tools.services.services_service import ServicesService


def test_modification_operations_prohibited_in_executor() -> None:
    fake_service = ServicesService(backend=FakeServicesBackend())
    executor = WindowsServicesToolExecutor(services_service=fake_service)

    prohibited_ops = ["start_service", "stop_service", "restart_service", "delete_service"]

    for op in prohibited_ops:
        req = ExecutionRequest(
            tool_name="windows.services",
            operation=op,
            parameters={"service_name": "wuauserv"},
        )
        ev = AuthorizationEvidence.create_valid(
            tool_name="windows.services",
            operation=op,
            parameters={"service_name": "wuauserv"},
            request_id=req.request_id,
        )

        res = executor.execute(req, ev)
        assert res.status == ExecutionStatus.FAILED
        assert "prohibida" in res.message or "no soportada" in res.message


def test_command_injection_service_name_rejected_by_security_manager() -> None:
    sec = ServiceNameSecurityManager()

    with pytest.raises(ServiceNameError):
        sec.validate_and_sanitize_name("wuauserv & net stop wuauserv")
