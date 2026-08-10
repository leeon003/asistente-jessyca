"""Pruebas de integración de auditoría y EventBus para CommandPolicyManager (Subetapa 07.1)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.capability_resolver import CapabilityResolver
from core.command_policy import CommandPolicyManager
from core.permission_manager import PermissionDecision


def test_command_policy_audit_and_eventbus_integration() -> None:
    mem_sink = MemoryAuditSink()
    mgr = CommandPolicyManager()
    mgr.audit_logger.add_sink(mem_sink)

    # Evaluar comando en lista blanca
    res_allow = mgr.evaluate_command("git", ["status"])
    assert res_allow.decision == PermissionDecision.ALLOW

    # Evaluar comando rechazado por inyección
    res_reject = mgr.evaluate_command("echo", ["hello; calc"])
    assert res_reject.decision == PermissionDecision.DENY

    events = mem_sink.get_events(tool_name="windows.shell")
    event_types = [e.event_type for e in events]

    assert AuditEventType.COMMAND_POLICY_ALLOWED in event_types
    assert AuditEventType.COMMAND_POLICY_REJECTED in event_types


def test_capability_resolver_integration_windows_shell() -> None:
    resolver = CapabilityResolver()
    cap = resolver.registry.get("windows.shell")
    assert cap is not None
    op_names = [op.name for op in cap.operations]
    assert "evaluate_command" in op_names
