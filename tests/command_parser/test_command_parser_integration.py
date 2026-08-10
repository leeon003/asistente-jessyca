"""Pruebas de integración de auditoría y EventBus para SecureCommandParser (Subetapa 07.2)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.command_parser import SecureCommandParser
from core.command_policy import CommandPolicyManager
from core.permission_manager import PermissionDecision


def test_command_parser_and_policy_integration() -> None:
    mem_sink = MemoryAuditSink()
    parser = SecureCommandParser()
    parser.audit_logger.add_sink(mem_sink)
    policy_mgr = CommandPolicyManager()

    # 1. Parsear comando
    cmd = parser.parse("git status")
    assert cmd.is_valid is True

    # 2. Evaluar política sobre la estructura parseada
    eval_res = policy_mgr.evaluate_command(cmd.executable, list(cmd.arguments))
    assert eval_res.decision == PermissionDecision.ALLOW

    # Verificar eventos de auditoría
    events = mem_sink.get_events(tool_name="windows.shell")
    event_types = [e.event_type for e in events]
    assert AuditEventType.COMMAND_PARSE_SUCCEEDED in event_types
