"""Pruebas para verificar la regla de inmutabilidad: Plugin -> CAPABILITY (Subetapa 16.2).

Demuestra rigurosamente que:
1. Los plugins declaran capacidades (CAPABILITY) pero NUNCA otorgan ni elevan la autoridad.
2. Un plugin no puede cambiar el nivel de autonomía del sistema.
3. Las acciones DANGEROUS o CRITICAL invocadas por un plugin exigen confirmación interactiva humana sin excepción.
"""

import pytest

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.autonomy.autonomy_level import AutonomyLevel
from core.autonomy.autonomy_policy import (
    AutonomyEscalationError,
    AutonomyEvaluationContext,
    AutonomyPolicy,
)


def test_plugin_cannot_change_autonomy_level() -> None:
    """Verifica que un plugin no puede invocar set_autonomy_level."""
    gov = get_autonomy_governor()
    gov.reset_to_default()

    with pytest.raises(AutonomyEscalationError) as exc_info:
        gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="plugin")

    assert "AUTONOMY ESCALATION REJECTED" in str(exc_info.value)
    assert gov.current_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED


def test_plugin_dangerous_action_denied_auto_execution() -> None:
    """Verifica que una acción DANGEROUS invocada por un plugin es denegada para ejecución automática."""
    policy = AutonomyPolicy()

    plugin_ctx = AutonomyEvaluationContext(
        task_id="t-plug-1",
        tool_name="windows.process",
        operation="kill",
        is_plugin=True,
        task_source="plugin_action",
    )

    dec = policy.evaluate(plugin_ctx, AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY)
    assert dec.allowed is False
    assert dec.requires_confirmation is True
    assert "PLUGIN ACTION DENIED" in dec.reason
