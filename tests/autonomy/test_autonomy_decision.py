"""Pruebas unitarias para la clase inmutable AutonomyDecision (Subetapa 16.2)."""

import pytest

from core.autonomy.autonomy_decision import AutonomyDecision, AutonomyDecisionValue
from core.autonomy.autonomy_level import AutonomyLevel
from core.autonomy_policy import TaskActionRisk


def test_autonomy_decision_immutability() -> None:
    """Verifica que la decisión de autonomía es estrictamente inmutable."""
    dec = AutonomyDecision(
        decision=AutonomyDecisionValue.ALLOW,
        autonomy_level=AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
        risk_level=TaskActionRisk.READ_ONLY,
        allowed=True,
        requires_confirmation=False,
        reason="Test allow",
    )

    assert dec.decision == AutonomyDecisionValue.ALLOW
    assert dec.allowed is True
    assert dec.requires_confirmation is False

    with pytest.raises(AttributeError):
        dec.allowed = False  # type: ignore[misc]


def test_autonomy_decision_is_allowed_without_confirmation() -> None:
    """Verifica el método helper de ejecución inmediata."""
    allow_dec = AutonomyDecision(
        decision=AutonomyDecisionValue.ALLOW,
        autonomy_level=AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
        risk_level=TaskActionRisk.LOW_RISK,
        allowed=True,
        requires_confirmation=False,
        reason="Allow test",
    )
    assert allow_dec.is_allowed_without_confirmation() is True

    conf_dec = AutonomyDecision(
        decision=AutonomyDecisionValue.REQUIRE_CONFIRMATION,
        autonomy_level=AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
        risk_level=TaskActionRisk.DANGEROUS,
        allowed=False,
        requires_confirmation=True,
        reason="Confirmation required",
    )
    assert conf_dec.is_allowed_without_confirmation() is False


def test_autonomy_decision_to_dict() -> None:
    """Verifica la serialización limpia para auditoría."""
    dec = AutonomyDecision(
        decision=AutonomyDecisionValue.DENY,
        autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
        risk_level=TaskActionRisk.CRITICAL,
        allowed=False,
        requires_confirmation=True,
        reason="Observed mode denies critical action",
        task_id="t-12345",
        tool_name="windows.shell",
        operation="powershell",
    )
    data = dec.to_dict()
    assert data["decision"] == "DENY"
    assert data["autonomy_level"] == "LEVEL_0_OBSERVE"
    assert data["risk_level"] == "CRITICAL"
    assert data["task_id"] == "t-12345"
