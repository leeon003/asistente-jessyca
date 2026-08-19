"""Pruebas para verificar la regla de inmutabilidad: Workflow -> SEQUENCE (Subetapa 16.2).

Demuestra rigurosamente que:
1. Los workflows y secuencias de tareas solo representan ordenamiento temporal.
2. Un workflow no puede elevar el nivel de autonomía.
3. El hecho de que una acción anterior de un workflow fuera aprobada NO otorga autorización automática a las siguientes acciones.
"""

import pytest

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.autonomy.autonomy_level import AutonomyLevel
from core.autonomy.autonomy_policy import (
    AutonomyEscalationError,
    AutonomyEvaluationContext,
    AutonomyPolicy,
)


def test_workflow_cannot_change_autonomy_level() -> None:
    """Verifica que un workflow no puede cambiar el nivel de autonomía."""
    gov = get_autonomy_governor()
    gov.reset_to_default()

    with pytest.raises(AutonomyEscalationError) as exc_info:
        gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="workflow")

    assert "AUTONOMY ESCALATION REJECTED" in str(exc_info.value)
    assert gov.current_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED


def test_workflow_step_sequence_does_not_grant_authority() -> None:
    """Verifica que cada paso de un workflow se evalúa independientemente sin heredar permisos excesivos."""
    policy = AutonomyPolicy()

    # Paso 1 del workflow: Lectura (READ_ONLY) -> Permitido
    wf_step1 = AutonomyEvaluationContext(
        task_id="wf-1-step1",
        tool_name="windows.files",
        operation="read_file",
        workflow_id="wf-100",
        task_source="workflow_step",
    )
    dec1 = policy.evaluate(wf_step1, AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION)
    assert dec1.allowed is True

    # Paso 2 del workflow: Modificación de Registro (DANGEROUS) -> Exige confirmación
    wf_step2 = AutonomyEvaluationContext(
        task_id="wf-1-step2",
        tool_name="windows.registry",
        operation="write",
        workflow_id="wf-100",
        task_source="workflow_step",
    )
    dec2 = policy.evaluate(wf_step2, AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION)
    assert dec2.allowed is False
    assert dec2.requires_confirmation is True
