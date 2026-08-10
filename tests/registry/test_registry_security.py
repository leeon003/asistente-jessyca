"""Pruebas de seguridad adversariales del Registro de Windows (Subetapa 06.4)."""

from __future__ import annotations

import pytest

from server.boundary import ExecutionStatus
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest
from tools.registry.backend import FakeRegistryBackend
from tools.registry.errors import InvalidHiveError
from tools.registry.executor import WindowsRegistryToolExecutor
from tools.registry.path_security import RegistryPathSecurityManager
from tools.registry.registry_service import RegistryService


def test_write_and_delete_operations_prohibited_in_executor() -> None:
    fake_service = RegistryService(backend=FakeRegistryBackend())
    executor = WindowsRegistryToolExecutor(registry_service=fake_service)

    req = ExecutionRequest(
        tool_name="windows.registry",
        operation="write_registry_value",  # Operación no soportada
        parameters={"hive": "HKCU", "key_path": "Software", "value_name": "Test"},
    )
    ev = AuthorizationEvidence.create_valid(
        tool_name="windows.registry",
        operation="write_registry_value",
        parameters={"hive": "HKCU", "key_path": "Software", "value_name": "Test"},
        request_id=req.request_id,
    )

    res = executor.execute(req, ev)
    assert res.status == ExecutionStatus.FAILED
    assert "no soportada" in res.message or "prohibida" in res.message


def test_unauthorized_hive_access_security_denial() -> None:
    sec = RegistryPathSecurityManager()
    with pytest.raises(InvalidHiveError):
        sec.validate_and_canonicalize("HKEY_DANGEROUS", "Software")
