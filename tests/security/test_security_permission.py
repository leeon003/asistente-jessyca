"""Pruebas adversariales para PermissionManager y estrategias Fail-Safe (Subetapa 04.7)."""

from __future__ import annotations

from core.permission_manager import (
    PermissionDecision,
    PermissionManager,
    PermissionRequest,
    PermissionSource,
)
from core.risk_engine import RiskAssessment
from core.security_architecture import SecurityContext, SecurityLevel, ToolSecurityMetadata


def test_permission_manager_null_context_failsafe() -> None:
    perm_mgr = PermissionManager()
    meta = ToolSecurityMetadata(tool_name="tool_a", risk_level=SecurityLevel.SAFE)
    risk = RiskAssessment(risk_level=SecurityLevel.SAFE)

    # Invocación con contexto nulo -> FAIL-SAFE DENY
    req = PermissionRequest(
        context=None,  # type: ignore[arg-type]
        metadata=meta,
        risk_assessment=risk,
        tool_name="tool_a",
        operation="read",
    )
    res = perm_mgr.evaluate_permission(req)
    assert res.is_allowed is False
    assert res.decision == PermissionDecision.DENY
    assert "Fail-Safe" in res.reason


def test_permission_manager_null_metadata_failsafe() -> None:
    perm_mgr = PermissionManager()
    ctx = SecurityContext(user="user", tool_name="tool_a")
    risk = RiskAssessment(risk_level=SecurityLevel.SAFE)

    # Invocación con metadatos nulos -> FAIL-SAFE DENY
    req = PermissionRequest(
        context=ctx,
        metadata=None,  # type: ignore[arg-type]
        risk_assessment=risk,
        tool_name="tool_a",
        operation="read",
    )
    res = perm_mgr.evaluate_permission(req)
    assert res.is_allowed is False
    assert res.decision == PermissionDecision.DENY


def test_permission_manager_unknown_risk_level_failsafe() -> None:
    perm_mgr = PermissionManager()
    ctx = SecurityContext(user="user", tool_name="tool_a")
    meta = ToolSecurityMetadata(tool_name="tool_a", risk_level=SecurityLevel.SAFE)
    # Nivel de riesgo totalmente irreconocible
    risk = RiskAssessment(risk_level="INVALID_RISK_STRING_XYZ")

    req = PermissionRequest(
        context=ctx,
        metadata=meta,
        risk_assessment=risk,
        tool_name="tool_a",
        operation="read",
    )
    res = perm_mgr.evaluate_permission(req)
    assert res.is_allowed is False
    assert res.decision == PermissionDecision.DENY
    assert "Fail-Safe" in res.reason


def test_permission_source_integrity() -> None:
    sources = list(PermissionSource)
    assert PermissionSource.DEFAULT in sources
    assert PermissionSource.TOOL in sources
    assert PermissionSource.OPERATION in sources
    assert PermissionSource.SESSION in sources
    assert PermissionSource.USER in sources
    assert PermissionSource.SYSTEM in sources

    # Verificar que el LLM no sea una fuente legítima de permisos
    assert not hasattr(PermissionSource, "LLM")
    assert not hasattr(PermissionSource, "PROMPT")
