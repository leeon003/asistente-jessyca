"""Pruebas del SecureExecutionPipeline y agregador de decisiones (Subetapa 05.2)."""

from __future__ import annotations

from typing import Any

from core.confirmation import ConfirmationStatus, MockConfirmationProvider
from core.security_architecture import SecurityLevel
from server.app import JessycaMCPServer
from server.boundary import ExecutionStatus
from server.execution_request import create_execution_request
from server.pipeline import SecureExecutionPipeline
from tools.base import BaseTool
from tools.tool_registry import ToolRegistry


class DummyMockTool(BaseTool):
    """Herramienta de pruebas sin ejecución real."""

    def __init__(self, name: str, risk_level: SecurityLevel = SecurityLevel.SAFE) -> None:
        super().__init__(
            name=name,
            description="Herramienta mock de prueba",
            category="test",
        )
        self.risk_level = risk_level

    def _get_input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def _execute_internal(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("CRÍTICO: No debe ejecutarse el método real de la herramienta en 05.2.")


# 1. SAFE + ALLOW -> Pipeline continúa hacia DisabledToolExecutor
def test_pipeline_safe_allow_flow() -> None:
    registry = ToolRegistry()
    registry.register(DummyMockTool("safe_tool", SecurityLevel.SAFE))

    server = JessycaMCPServer(tool_registry=registry)
    server.start()

    res = server.handle_request({"tool_name": "safe_tool", "operation": "read"})
    assert res.status in (ExecutionStatus.EXECUTION_DISABLED, ExecutionStatus.STUB_DISABLED)
    assert res.tool_name == "safe_tool"

    server.shutdown()


# 2. DANGEROUS -> Requiere confirmación
def test_pipeline_dangerous_requires_confirmation_rejected() -> None:
    pipeline = SecureExecutionPipeline()
    req = create_execution_request(tool_name="delete_tool", operation="delete", parameters={"path": "file.txt"})

    # Proporcionar confirmación REJECTED
    provider = MockConfirmationProvider(ConfirmationStatus.REJECTED)
    res = pipeline.execute_request(req, confirmation_provider=provider)

    assert res.status == ExecutionStatus.DENIED
    assert "Denegada" in res.message or "Confirmación no aprobada" in res.message


# 3. DANGEROUS + CONFIRMATION APPROVED -> Continúa hacia DisabledToolExecutor
def test_pipeline_dangerous_requires_confirmation_approved() -> None:
    pipeline = SecureExecutionPipeline()
    req = create_execution_request(tool_name="delete_tool", operation="delete", parameters={"path": "file.txt"})

    # Proporcionar confirmación APPROVED
    provider = MockConfirmationProvider(ConfirmationStatus.APPROVED)
    res = pipeline.execute_request(req, confirmation_provider=provider)

    assert res.status in (ExecutionStatus.EXECUTION_DISABLED, ExecutionStatus.STUB_DISABLED)


# 4. CRITICAL -> DENY final
def test_pipeline_critical_deny() -> None:
    pipeline = SecureExecutionPipeline()
    # Solicitar operación sobre System32 -> Evaluada como CRITICAL por RiskEngine
    req = create_execution_request(
        tool_name="sys_tool",
        operation="modify",
        parameters={"path": "C:\\Windows\\System32\\config"},
    )

    res = pipeline.execute_request(req)
    assert res.status == ExecutionStatus.DENIED
    assert "CRITICAL" in res.message or "Denegada" in res.message


# 5. UNKNOWN -> DENY Fail-Safe
def test_pipeline_unknown_operation_deny() -> None:
    pipeline = SecureExecutionPipeline()
    req = create_execution_request(tool_name="unknown_tool", operation="unknown_op")

    res = pipeline.execute_request(req)
    assert res.status == ExecutionStatus.DENIED


# 6. Verificación explícita: STUB_DISABLED se audita como EXECUTION_DISABLED y NO como EXECUTION_SUCCEEDED
def test_pipeline_stub_disabled_audit_event() -> None:
    from core.audit_logger import AuditEventType, MemoryAuditSink

    mem_sink = MemoryAuditSink()
    pipeline = SecureExecutionPipeline()
    pipeline.audit_logger.add_sink(mem_sink)

    req = create_execution_request(tool_name="safe_tool", operation="read")
    res = pipeline.execute_request(req)

    assert res.status == ExecutionStatus.EXECUTION_DISABLED
    events = mem_sink.get_events(request_id=req.request_id)
    event_types = [e.event_type for e in events]

    assert AuditEventType.EXECUTION_DISABLED in event_types
    assert AuditEventType.EXECUTION_SUCCEEDED not in event_types

