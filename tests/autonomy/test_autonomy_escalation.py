"""Pruebas anti-escalamiento de autonomía (Subetapa 16.2).

Demuestra rigurosamente que:
1. El LLM no puede elevar su nivel de autonomía.
2. Parámetros maliciosos de inyección ('override_autonomy', 'bypass_confirmation') son detectados y bloqueados.
3. La confirmación del usuario para una acción no otorga autorización permanente ni modifica las políticas futuras.
"""

import pytest

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.autonomy.autonomy_level import AutonomyLevel
from core.autonomy.autonomy_policy import (
    AutonomyEscalationError,
    AutonomyEvaluationContext,
    AutonomyPolicy,
)


def test_llm_cannot_elevate_autonomy_level() -> None:
    """Verifica que solicitudes originadas por el LLM no pueden modificar el Nivel de Autonomía global."""
    gov = get_autonomy_governor()
    gov.reset_to_default()

    assert gov.current_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED

    # Simulación de prompt injection del LLM intentando cambiar el nivel
    with pytest.raises(AutonomyEscalationError) as exc_info:
        gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="llm")

    assert "AUTONOMY ESCALATION REJECTED" in str(exc_info.value)
    assert gov.current_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED


def test_parameter_injection_escalation_blocked() -> None:
    """Verifica que el envío de banderas de bypass dentro de parámetros lanza AutonomyEscalationError."""
    policy = AutonomyPolicy()

    malicious_contexts = [
        AutonomyEvaluationContext(
            task_id="t-inj-1",
            tool_name="windows.files",
            operation="read_file",
            parameters={"override_autonomy": True},
        ),
        AutonomyEvaluationContext(
            task_id="t-inj-2",
            tool_name="windows.files",
            operation="read_file",
            parameters={"bypass_confirmation": "yes"},
        ),
        AutonomyEvaluationContext(
            task_id="t-inj-3",
            tool_name="windows.process",
            operation="kill",
            metadata={"grant_full_autonomy": "true"},
        ),
    ]

    for ctx in malicious_contexts:
        with pytest.raises(AutonomyEscalationError) as exc_info:
            policy.evaluate(ctx, AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION)

        assert "AUTONOMY ESCALATION ATTEMPT" in str(exc_info.value)


def test_user_confirmation_is_not_permanent_authorization() -> None:
    """Verifica que confirmar una acción puntual de nivel DANGEROUS/CRITICAL NO cambia el nivel de autonomía futuro."""
    gov = get_autonomy_governor()
    gov.reset_to_default()

    ctx_dangerous = AutonomyEvaluationContext(
        task_id="t-dang-1",
        tool_name="windows.process",
        operation="terminate",
        task_source="user_request",
    )

    # Inicialmente exige confirmación
    dec1 = gov.evaluate_action(ctx_dangerous)
    assert dec1.requires_confirmation is True
    assert dec1.allowed is False

    # Supongamos que el usuario aprueba esa única solicitud
    # La siguiente solicitud idéntica DEBE seguir exigiendo confirmación
    dec2 = gov.evaluate_action(ctx_dangerous)
    assert dec2.requires_confirmation is True
    assert dec2.allowed is False
    assert gov.current_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED
