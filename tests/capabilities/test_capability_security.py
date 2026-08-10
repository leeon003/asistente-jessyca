"""Pruebas adversariales de seguridad del Capability System (Subetapa 06.1)."""

from __future__ import annotations

import pytest

from core.capabilities import (
    CapabilityDecision,
    CapabilityOperation,
    CapabilityRiskLevel,
    CapabilitySource,
    ToolCapability,
    compute_capability_fingerprint,
)
from core.capability_registry import CapabilityRegistry
from core.capability_validator import validate_capability
from core.exceptions import SecurityValidationError


def test_tool_substitution_rejected_by_fingerprint() -> None:
    fp_files = compute_capability_fingerprint(
        tool_name="windows.files",
        version="1.0.0",
        operation_id="op_read",
        operation_name="read_file",
        risk_level=CapabilityRiskLevel.SAFE,
        decision=CapabilityDecision.ALLOW,
        requires_confirmation=False,
        requires_elevation=False,
    )

    fp_proc = compute_capability_fingerprint(
        tool_name="windows.process",
        version="1.0.0",
        operation_id="op_read",
        operation_name="read_file",
        risk_level=CapabilityRiskLevel.SAFE,
        decision=CapabilityDecision.ALLOW,
        requires_confirmation=False,
        requires_elevation=False,
    )

    assert fp_files != fp_proc


def test_operation_substitution_rejected_by_fingerprint() -> None:
    fp_read = compute_capability_fingerprint(
        tool_name="windows.files",
        version="1.0.0",
        operation_id="op_read",
        operation_name="read_file",
        risk_level=CapabilityRiskLevel.SAFE,
        decision=CapabilityDecision.ALLOW,
        requires_confirmation=False,
        requires_elevation=False,
    )

    fp_delete = compute_capability_fingerprint(
        tool_name="windows.files",
        version="1.0.0",
        operation_id="op_delete",
        operation_name="delete_file",
        risk_level=CapabilityRiskLevel.DANGEROUS,
        decision=CapabilityDecision.REQUIRE_CONFIRMATION,
        requires_confirmation=True,
        requires_elevation=False,
    )

    assert fp_read != fp_delete


def test_llm_and_client_capability_injection_rejected() -> None:
    for forbidden_source in ("LLM", "USER_PROMPT", "CLIENT", "ASSISTANT"):
        cap = ToolCapability(
            capability_id=f"cap_injected_{forbidden_source}",
            tool_name="hacked_tool",
            display_name="Hacked Tool",
            description="Injected",
            version="1.0.0",
            source=forbidden_source,  # type: ignore[arg-type]
        )

        errors = validate_capability(cap)
        assert any("Fuente No Confiable Rechazada" in e for e in errors)

        registry = CapabilityRegistry()
        with pytest.raises(SecurityValidationError):
            registry.register(cap)
