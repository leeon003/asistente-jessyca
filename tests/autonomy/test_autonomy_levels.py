"""Pruebas unitarias para el modelo de Niveles de Autonomía (AutonomyLevel - Subetapa 16.2)."""

from core.autonomy.autonomy_level import AutonomyLevel
from core.autonomy_policy import TaskActionRisk


def test_autonomy_level_values() -> None:
    """Verifica que los 5 niveles de autonomía tienen los valores e identidades correctos."""
    assert AutonomyLevel.LEVEL_0_OBSERVE == 0
    assert AutonomyLevel.LEVEL_1_SUGGEST == 1
    assert AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION == 2
    assert AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED == 3
    assert AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY == 4


def test_autonomy_level_tool_execution_permissions() -> None:
    """Verifica la permisividad de ejecución de herramientas por nivel."""
    assert not AutonomyLevel.LEVEL_0_OBSERVE.allows_tool_execution()
    assert not AutonomyLevel.LEVEL_1_SUGGEST.allows_tool_execution()
    assert AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION.allows_tool_execution()
    assert AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED.allows_tool_execution()
    assert AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY.allows_tool_execution()


def test_autonomy_level_risk_auto_execution() -> None:
    """Verifica qué niveles de riesgo se permiten de forma automática por nivel de autonomía."""
    # LEVEL_0 y LEVEL_1: CERO ejecución automática
    assert not AutonomyLevel.LEVEL_0_OBSERVE.is_risk_allowed_auto(TaskActionRisk.READ_ONLY)
    assert not AutonomyLevel.LEVEL_1_SUGGEST.is_risk_allowed_auto(TaskActionRisk.READ_ONLY)

    # LEVEL_2: READ_ONLY y LOW_RISK
    assert AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION.is_risk_allowed_auto(TaskActionRisk.READ_ONLY)
    assert AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION.is_risk_allowed_auto(TaskActionRisk.LOW_RISK)
    assert not AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION.is_risk_allowed_auto(TaskActionRisk.MEDIUM_RISK)
    assert not AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION.is_risk_allowed_auto(TaskActionRisk.CRITICAL)

    # LEVEL_4: READ_ONLY, LOW_RISK, MEDIUM_RISK. DANGEROUS/CRITICAL NUNCA se auto-ejecutan
    assert AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY.is_risk_allowed_auto(TaskActionRisk.MEDIUM_RISK)
    assert not AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY.is_risk_allowed_auto(TaskActionRisk.DANGEROUS)
    assert not AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY.is_risk_allowed_auto(TaskActionRisk.CRITICAL)


def test_autonomy_level_critical_requires_confirmation_always() -> None:
    """Verifica la invariante de que las acciones CRITICAL y DANGEROUS siempre exigen confirmación en todos los niveles."""
    for level in AutonomyLevel:
        assert level.requires_confirmation_for_risk(TaskActionRisk.CRITICAL)
        assert level.requires_confirmation_for_risk(TaskActionRisk.DANGEROUS)
