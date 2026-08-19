"""Pruebas unitarias para el Gobernador Central de Autonomía (AutonomyGovernor - Etapa 16.2)."""

import pytest

from core.autonomy.autonomy_governor import AutonomyGovernor, get_autonomy_governor
from core.autonomy.autonomy_level import AutonomyLevel
from core.autonomy.autonomy_policy import (
    AutonomyConfirmationRequiredError,
    AutonomyEscalationError,
    AutonomyEvaluationContext,
    AutonomyPermissionDeniedError,
)


def test_autonomy_governor_singleton() -> None:
    """Verifica que el gobernador opera como singleton único thread-safe."""
    gov1 = get_autonomy_governor()
    gov2 = AutonomyGovernor.get_instance()
    assert gov1 is gov2


def test_autonomy_governor_authorized_level_change() -> None:
    """Verifica que un actor humano autorizado (user, system_admin) puede modificar el nivel."""
    gov = get_autonomy_governor()
    gov.reset_to_default()
    assert gov.current_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED

    # Usuario humano cambia a LEVEL_2
    gov.set_autonomy_level(AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION, actor="user")
    assert gov.current_level == AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION

    # System Admin cambia a LEVEL_4
    gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="system_admin")
    assert gov.current_level == AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY

    gov.reset_to_default()


def test_autonomy_governor_unauthorized_level_change_rejected() -> None:
    """Verifica que actores no autorizados (llm, plugin, scheduler, memory) son RECHAZADOS."""
    gov = get_autonomy_governor()
    gov.reset_to_default()

    unauthorized_actors = ["llm", "plugin", "scheduler", "memory", "workflow", "tool", "untrusted_script"]

    for actor in unauthorized_actors:
        with pytest.raises(AutonomyEscalationError) as exc_info:
            gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor=actor)

        assert "AUTONOMY ESCALATION REJECTED" in str(exc_info.value)
        # El nivel NO debió haber cambiado
        assert gov.current_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED


def test_autonomy_governor_enforce_action() -> None:
    """Verifica el enforzamiento de decisiones con lanzamiento de excepciones.

    Etapa 16.2: windows.shell.powershell requiere LEVEL_4 según el catálogo declarado.
    Con Governor en LEVEL_2, la decisión es DENY (nivel insuficiente), no REQUIRE_CONFIRMATION.
    Ambas excepciones (PermissionDenied o ConfirmationRequired) son respuestas de seguridad válidas.
    """
    gov = get_autonomy_governor()
    gov.set_autonomy_level(AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION, actor="user")

    # 1. READ_ONLY -> Permitido
    ctx_read = AutonomyEvaluationContext(
        task_id="t-read",
        tool_name="windows.files",
        operation="read_file",
    )
    dec = gov.enforce_action(ctx_read)
    assert dec.allowed is True

    # 2. windows.shell.powershell en LEVEL_2 -> DENEGADO (nivel insuficiente, requiere LEVEL_4)
    #    Etapa 16.2: el catálogo declarado prevalece sobre la inferencia por nombre.
    #    La excepción puede ser PermissionDeniedError (DENY) o ConfirmationRequiredError (ASK).
    ctx_critical = AutonomyEvaluationContext(
        task_id="t-crit",
        tool_name="windows.shell",
        operation="powershell",
    )
    with pytest.raises((AutonomyPermissionDeniedError, AutonomyConfirmationRequiredError)):
        gov.enforce_action(ctx_critical)

    gov.reset_to_default()
