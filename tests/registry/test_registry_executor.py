"""Pruebas del ejecutor real WindowsRegistryToolExecutor (Subetapa 06.4)."""

from __future__ import annotations

from server.boundary import ExecutionStatus
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest
from tools.registry.backend import FakeRegistryBackend
from tools.registry.executor import WindowsRegistryToolExecutor
from tools.registry.registry_service import RegistryService


def test_executor_list_registry_subkeys() -> None:
    fake_service = RegistryService(backend=FakeRegistryBackend())
    executor = WindowsRegistryToolExecutor(registry_service=fake_service)

    req = ExecutionRequest(
        tool_name="windows.registry",
        operation="list_registry_subkeys",
        parameters={"hive": "HKCU", "key_path": "Software\\JessycaMCP"},
    )
    ev = AuthorizationEvidence.create_valid(
        tool_name="windows.registry",
        operation="list_registry_subkeys",
        parameters={"hive": "HKCU", "key_path": "Software\\JessycaMCP"},
        request_id=req.request_id,
    )

    res = executor.execute(req, ev)
    assert res.status == ExecutionStatus.SUCCESS
    assert len(res.output["subkeys"]) == 2


def test_executor_get_registry_value() -> None:
    fake_service = RegistryService(backend=FakeRegistryBackend())
    executor = WindowsRegistryToolExecutor(registry_service=fake_service)

    req = ExecutionRequest(
        tool_name="windows.registry",
        operation="get_registry_value",
        parameters={"hive": "HKCU", "key_path": "Software\\JessycaMCP", "value_name": "Version"},
    )
    ev = AuthorizationEvidence.create_valid(
        tool_name="windows.registry",
        operation="get_registry_value",
        parameters={"hive": "HKCU", "key_path": "Software\\JessycaMCP", "value_name": "Version"},
        request_id=req.request_id,
    )

    res = executor.execute(req, ev)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.output["value_data"] == "0.6.4"
