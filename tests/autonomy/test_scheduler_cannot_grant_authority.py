"""Pruebas para verificar la regla de inmutabilidad: Scheduler -> TRIGGER (Subetapa 16.2).

Demuestra rigurosamente que:
1. El programador de tareas opera únicamente como disparador (TRIGGER).
2. Estar programado en JSON local NO otorga autoridad previa ni exime de comprobaciones de seguridad.
3. El scheduler no puede elevar el nivel de autonomía.
4. Tareas programadas con acciones DANGEROUS/CRITICAL son denegadas de ejecución autónoma.
"""

import pytest

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.autonomy.autonomy_level import AutonomyLevel
from core.autonomy.autonomy_policy import (
    AutonomyEscalationError,
    AutonomyEvaluationContext,
    AutonomyPolicy,
)


def test_scheduler_cannot_change_autonomy_level() -> None:
    """Verifica que el scheduler no puede modificar el Nivel de Autonomía."""
    gov = get_autonomy_governor()
    gov.reset_to_default()

    with pytest.raises(AutonomyEscalationError) as exc_info:
        gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="scheduler")

    assert "AUTONOMY ESCALATION REJECTED" in str(exc_info.value)
    assert gov.current_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED


def test_scheduled_task_dangerous_action_denied_auto_execution() -> None:
    """Verifica que una tarea programada no puede auto-ejecutar acciones DANGEROUS ni CRITICAL."""
    policy = AutonomyPolicy()

    sched_ctx = AutonomyEvaluationContext(
        task_id="t-sched-crit",
        tool_name="windows.shell",
        operation="powershell",
        is_scheduled=True,
        task_source="scheduled_task",
    )

    dec = policy.evaluate(sched_ctx, AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY)
    assert dec.allowed is False
    assert dec.requires_confirmation is True
    assert "SCHEDULED TASK DENIED" in dec.reason
