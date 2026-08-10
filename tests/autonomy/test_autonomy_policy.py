"""Pruebas unitarias y adversariales de la Política de Autonomía (Etapa 13.0).

REQUISITOS ADVERSARIALES PROBADOS:
1. INVARIANTE ABSOLUTO: scheduled_task != user_authorization.
2. Una tarea programada NUNCA obtiene bypass o mayor autoridad por haber sido previamente configurada.
3. Clasificación estricta de las 5 categorías de riesgo (READ_ONLY, LOW_RISK, MEDIUM_RISK, DANGEROUS, CRITICAL).
4. Acciones DANGEROUS y CRITICAL programadas deniegan su ejecución automática y exigen confirmación en tiempo real.
5. Registro de auditoría libre de datos sensibles.
"""

from __future__ import annotations

import pytest

from core.audit_logger import MemoryAuditSink, get_audit_logger
from core.autonomy_policy import (
    AutonomousTaskRequest,
    AutonomyConfirmationRequiredError,
    AutonomyPermissionDeniedError,
    AutonomyPolicy,
    TaskActionRisk,
    TaskRiskClassifier,
)


def test_task_risk_classifier_all_levels() -> None:
    classifier = TaskRiskClassifier()

    # 1. READ_ONLY
    r_read = classifier.classify_task(tool_name="system.read", operation="read_file")
    assert r_read == TaskActionRisk.READ_ONLY

    # 2. LOW_RISK
    r_low = classifier.classify_task(tool_name="log.write", operation="append")
    assert r_low == TaskActionRisk.LOW_RISK

    # 3. MEDIUM_RISK
    r_med = classifier.classify_task(tool_name="file.write", operation="update_content")
    assert r_med == TaskActionRisk.MEDIUM_RISK

    # 4. DANGEROUS
    r_danger = classifier.classify_task(tool_name="file.delete", operation="remove_file")
    assert r_danger == TaskActionRisk.DANGEROUS

    # 5. CRITICAL
    r_crit = classifier.classify_task(tool_name="cmd.execute", operation="run")
    assert r_crit == TaskActionRisk.CRITICAL


def test_scheduled_task_not_user_authorization_invariant() -> None:
    """Demuestra que scheduled_task != user_authorization. Tareas DANGEROUS/CRITICAL programadas NO se auto-autorizan."""
    policy = AutonomyPolicy()

    # Intentar ejecutar una tarea programada DANGEROUS (borrar archivo)
    req_dangerous = AutonomousTaskRequest(
        task_id="sched-task-1",
        tool_name="file.delete",
        operation="remove",
        is_scheduled=True,
    )

    res_dangerous = policy.evaluate_task(req_dangerous)
    assert res_dangerous.allowed is False
    assert res_dangerous.requires_confirmation is True
    assert "CERO BYPASS" in res_dangerous.reason or "denegada" in res_dangerous.reason

    with pytest.raises(AutonomyConfirmationRequiredError):
        policy.enforce_task_execution(req_dangerous)


def test_bypass_attempt_via_scheduled_flag_fails() -> None:
    """Demuestra que marcar is_scheduled=True sobre una acción CRITICAL NUNCA otorga un bypass."""
    policy = AutonomyPolicy()

    req_critical = AutonomousTaskRequest(
        task_id="sched-bypass-attack",
        tool_name="powershell.execute",
        operation="run_script",
        is_scheduled=True,
        parameters={"script": "Remove-Item -Path C:\\Windows -Recurse"},
    )

    res = policy.evaluate_task(req_critical)
    assert res.allowed is False
    assert res.risk_level == TaskActionRisk.CRITICAL
    assert res.requires_confirmation is True

    with pytest.raises((AutonomyConfirmationRequiredError, AutonomyPermissionDeniedError)):
        policy.enforce_task_execution(req_critical)


def test_scheduled_read_only_task_allowed() -> None:
    """Verifica que una tarea programada READ_ONLY legítima puede proceder autónomamente."""
    policy = AutonomyPolicy()

    req_read = AutonomousTaskRequest(
        task_id="sched-health-check",
        tool_name="system.read",
        operation="get_status",
        is_scheduled=True,
    )

    res = policy.evaluate_task(req_read)
    assert res.allowed is True
    assert res.risk_level == TaskActionRisk.READ_ONLY
    assert res.requires_confirmation is False


def test_autonomy_audit_logging_no_secrets() -> None:
    """Verifica que la auditoría de autonomía registre metadatos y no exponga contenido o secretos crudos."""
    mem_sink = MemoryAuditSink()
    audit_logger = get_audit_logger()
    audit_logger.add_sink(mem_sink)

    policy = AutonomyPolicy()
    req = AutonomousTaskRequest(
        task_id="audit-task-99",
        tool_name="process.list",
        operation="query",
        is_scheduled=True,
        parameters={"password": "SuperSecretPassword123!"},
    )

    res = policy.evaluate_task(req)
    assert res.task_id == "audit-task-99"

    events = mem_sink.get_events()
    autonomy_events = [e for e in events if "autonomy" in e.request_id]
    assert len(autonomy_events) >= 1

    ev_dict = autonomy_events[0].to_dict()
    ev_str = str(ev_dict).lower()
    assert "supersecretpassword123!" not in ev_str
    assert "is_scheduled" in str(ev_dict)
