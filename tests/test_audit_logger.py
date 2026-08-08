"""Pruebas unitarias completas del Audit Logger registrando exactamente los 8 campos clave obligatorios."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from core.audit_logger import AuditLogger
from core.event_bus import EventBus
from core.security import PermissionAction, RiskLevel, SecurityManager, ToolSecurityProfile


def test_log_event_eight_mandatory_fields() -> None:
    audit = AuditLogger()

    entry = audit.log_event(
        usuario="admin_user",
        accion="delete",
        herramienta="delete_file_tool",
        riesgo=RiskLevel.DANGEROUS,
        resultado="SUCCESS",
        duracion_ms=145.5,
        autorizacion=PermissionAction.ALLOW_ONCE,
    )

    # Verificación de los 8 campos obligatorios exactos
    assert entry.usuario == "admin_user"                      # 1. usuario
    assert entry.accion == "delete"                           # 2. acción
    assert entry.herramienta == "delete_file_tool"            # 3. herramienta
    assert entry.riesgo == RiskLevel.DANGEROUS               # 4. riesgo
    assert entry.resultado == "SUCCESS"                      # 5. resultado
    assert isinstance(entry.fecha, datetime)                  # 6. fecha
    assert entry.duracion_ms == 145.5                         # 7. duración (ms)
    assert entry.autorizacion == PermissionAction.ALLOW_ONCE  # 8. autorización


def test_audit_logger_filtering() -> None:
    audit = AuditLogger()
    audit.log_event("u1", "read", "tool1", RiskLevel.SAFE, "SUCCESS", 10.0, PermissionAction.ALLOW)
    audit.log_event("u2", "write", "tool2", RiskLevel.WARNING, "FAILURE", 25.0, PermissionAction.DENY)
    audit.log_event("u1", "delete", "tool1", RiskLevel.DANGEROUS, "SUCCESS", 50.0, PermissionAction.ALLOW_ONCE)

    # Filtrar por usuario
    u1_logs = audit.get_logs(user_filter="u1")
    assert len(u1_logs) == 2

    # Filtrar por herramienta
    t2_logs = audit.get_logs(tool_filter="tool2")
    assert len(t2_logs) == 1
    assert t2_logs[0].herramienta == "tool2"

    # Filtrar por resultado
    fail_logs = audit.get_logs(result_filter="FAILURE")
    assert len(fail_logs) == 1
    assert fail_logs[0].resultado == "FAILURE"


def test_export_logs_json_and_csv() -> None:
    audit = AuditLogger()
    audit.log_event("tester", "execute", "ping_tool", RiskLevel.SAFE, "SUCCESS", 12.3, PermissionAction.ALLOW)

    # Exportar JSON
    json_output = audit.export_logs_json()
    assert isinstance(json_output, str)
    parsed = json.loads(json_output)
    assert len(parsed) == 1
    assert parsed[0]["usuario"] == "tester"
    assert parsed[0]["herramienta"] == "ping_tool"
    assert parsed[0]["autorizacion"] == PermissionAction.ALLOW.value

    # Exportar CSV
    csv_output = audit.export_logs_csv()
    assert isinstance(csv_output, str)
    assert "usuario,accion,herramienta,riesgo,resultado,fecha,duracion_ms,autorizacion" in csv_output
    assert "tester,execute,ping_tool,SAFE,SUCCESS" in csv_output


def test_security_manager_audit_integration() -> None:
    sec = SecurityManager()
    profile = ToolSecurityProfile(name="test_tool", category="filesystem", risk_level=RiskLevel.SAFE)

    sec.evaluate(profile, user="operator")

    audit = sec.get_audit_log()
    assert len(audit) >= 1
    assert audit[-1].tool_name == "test_tool"
    assert audit[-1].user == "operator"


def test_event_bus_audit_notification() -> None:
    bus = EventBus()
    notifications: list[dict[str, Any]] = []

    bus.subscribe("audit:logged", lambda ev: notifications.append(ev.payload))
    audit = AuditLogger(event_bus=bus)

    audit.log_event("auditor", "inspect", "system_health", RiskLevel.READ_ONLY, "SUCCESS", 5.0, PermissionAction.ALLOW)

    assert len(notifications) == 1
    assert notifications[0]["usuario"] == "auditor"
    assert notifications[0]["herramienta"] == "system_health"
