"""Pruebas del fingerprint determinista SHA-256 de Capabilities (Subetapa 06.1)."""

from __future__ import annotations

from core.capabilities import (
    CapabilityDecision,
    CapabilityRiskLevel,
    compute_capability_fingerprint,
)


def test_fingerprint_determinism() -> None:
    fp1 = compute_capability_fingerprint(
        tool_name="windows.files",
        version="1.0.0",
        operation_id="op_read",
        operation_name="read_file",
        risk_level=CapabilityRiskLevel.SAFE,
        decision=CapabilityDecision.ALLOW,
        requires_confirmation=False,
        requires_elevation=False,
    )

    fp2 = compute_capability_fingerprint(
        tool_name="windows.files",
        version="1.0.0",
        operation_id="op_read",
        operation_name="read_file",
        risk_level=CapabilityRiskLevel.SAFE,
        decision=CapabilityDecision.ALLOW,
        requires_confirmation=False,
        requires_elevation=False,
    )

    assert fp1 == fp2
    assert len(fp1) == 64  # Hex string SHA-256


def test_fingerprint_changes_on_tool_name_tampering() -> None:
    base_params = dict(
        version="1.0.0",
        operation_id="op_read",
        operation_name="read_file",
        risk_level=CapabilityRiskLevel.SAFE,
        decision=CapabilityDecision.ALLOW,
        requires_confirmation=False,
        requires_elevation=False,
    )

    fp1 = compute_capability_fingerprint(tool_name="windows.files", **base_params)
    fp2 = compute_capability_fingerprint(tool_name="windows.process", **base_params)

    assert fp1 != fp2


def test_fingerprint_changes_on_risk_tampering() -> None:
    base_params = dict(
        tool_name="windows.files",
        version="1.0.0",
        operation_id="op_read",
        operation_name="read_file",
        decision=CapabilityDecision.ALLOW,
        requires_confirmation=False,
        requires_elevation=False,
    )

    fp1 = compute_capability_fingerprint(risk_level=CapabilityRiskLevel.SAFE, **base_params)
    fp2 = compute_capability_fingerprint(risk_level=CapabilityRiskLevel.CRITICAL, **base_params)

    assert fp1 != fp2


def test_fingerprint_changes_on_decision_tampering() -> None:
    base_params = dict(
        tool_name="windows.files",
        version="1.0.0",
        operation_id="op_read",
        operation_name="read_file",
        risk_level=CapabilityRiskLevel.SAFE,
        requires_confirmation=False,
        requires_elevation=False,
    )

    fp1 = compute_capability_fingerprint(decision=CapabilityDecision.ALLOW, **base_params)
    fp2 = compute_capability_fingerprint(decision=CapabilityDecision.DENY, **base_params)

    assert fp1 != fp2


def test_fingerprint_changes_on_version_tampering() -> None:
    base_params = dict(
        tool_name="windows.files",
        operation_id="op_read",
        operation_name="read_file",
        risk_level=CapabilityRiskLevel.SAFE,
        decision=CapabilityDecision.ALLOW,
        requires_confirmation=False,
        requires_elevation=False,
    )

    fp1 = compute_capability_fingerprint(version="1.0.0", **base_params)
    fp2 = compute_capability_fingerprint(version="9.9.9", **base_params)

    assert fp1 != fp2
