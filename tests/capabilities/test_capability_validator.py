"""Pruebas de validación estricta de seguridad CapabilityValidator (Subetapa 06.1)."""

from __future__ import annotations

import pytest

from core.capabilities import (
    CapabilityDecision,
    CapabilityOperation,
    CapabilityRiskLevel,
    CapabilitySource,
    ToolCapability,
)
from core.capability_validator import check_and_assert_capability, validate_capability
from core.exceptions import SecurityValidationError


def test_validator_rejects_critical_risk_with_allow_decision() -> None:
    op = CapabilityOperation(
        operation_id="op_crit",
        name="critical_op",
        description="Operación crítica",
        risk_level=CapabilityRiskLevel.CRITICAL,
        decision=CapabilityDecision.ALLOW,  # Violación: CRITICAL jamás ALLOW
    )

    cap = ToolCapability(
        capability_id="cap_invalid_v1",
        tool_name="invalid_tool",
        display_name="Invalid",
        description="Descr",
        version="1.0.0",
        source=CapabilitySource.SYSTEM,
        operations=(op,),
    )

    errors = validate_capability(cap)
    assert any("CRITICAL jamás puede configurarse como ALLOW" in e for e in errors)

    with pytest.raises(SecurityValidationError):
        check_and_assert_capability(cap)


def test_validator_rejects_unknown_risk_without_deny_decision() -> None:
    op = CapabilityOperation(
        operation_id="op_unk",
        name="unknown_op",
        description="Operación desmesurada",
        risk_level=CapabilityRiskLevel.UNKNOWN,
        decision=CapabilityDecision.ALLOW,  # Violación: UNKNOWN debe ser DENY
    )

    cap = ToolCapability(
        capability_id="cap_invalid_v2",
        tool_name="invalid_tool_2",
        display_name="Invalid 2",
        description="Descr",
        version="1.0.0",
        source=CapabilitySource.SYSTEM,
        operations=(op,),
    )

    errors = validate_capability(cap)
    assert any("Risk UNKNOWN exige decisión DENY" in e for e in errors)


def test_validator_rejects_untrusted_sources() -> None:
    cap = ToolCapability(
        capability_id="cap_forged_v1",
        tool_name="forged_tool",
        display_name="Forged Tool",
        description="Forged",
        version="1.0.0",
        source="LLM",  # type: ignore[arg-type]
    )

    errors = validate_capability(cap)
    assert any("Fuente No Confiable Rechazada" in e for e in errors)
