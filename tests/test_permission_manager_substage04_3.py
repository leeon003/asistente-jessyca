"""Pruebas unitarias exclusivas de la Subetapa 04.3 — Permission Manager."""

from __future__ import annotations

from core.contracts import IPermissionManager
from core.permission_manager import (
    PermissionDecision,
    PermissionManager,
    PermissionRequest,
    PermissionResult,
    PermissionSource,
)
from core.risk_engine import RiskAssessment, RiskFactor
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    ToolSecurityMetadata,
)


def test_permission_manager_implements_interface() -> None:
    """Verifica que PermissionManager cumpla el protocolo IPermissionManager."""
    mgr = PermissionManager()
    assert isinstance(mgr, IPermissionManager)


def test_safe_risk_level_authorization() -> None:
    """1. SAFE -> Autorización esperada (PermissionDecision.ALLOW por defecto)."""
    mgr = PermissionManager()
    ctx = SecurityContext(user="user1", tool_name="system_health")
    meta = ToolSecurityMetadata(tool_name="system_health", risk_level=SecurityLevel.SAFE)
    risk = RiskAssessment(risk_level=SecurityLevel.SAFE, score=2)
    req = PermissionRequest(
        context=ctx, metadata=meta, risk_assessment=risk, tool_name="system_health", operation="read"
    )

    res = mgr.evaluate_permission(req)
    assert isinstance(res, PermissionResult)
    assert res.decision == PermissionDecision.ALLOW
    assert res.is_allowed is True
    assert res.source == PermissionSource.DEFAULT


def test_warning_risk_level_authorization() -> None:
    """2 y 7. WARNING -> Autorización temporal ALLOW_ONCE para escrituras/modificaciones."""
    mgr = PermissionManager()
    ctx = SecurityContext(user="user1", tool_name="write_tool")
    meta = ToolSecurityMetadata(tool_name="write_tool", risk_level=SecurityLevel.WARNING)
    risk = RiskAssessment(risk_level=SecurityLevel.WARNING, score=3, risk_factors={RiskFactor.FILE_MODIFICATION})
    req = PermissionRequest(
        context=ctx, metadata=meta, risk_assessment=risk, tool_name="write_tool", operation="write_content"
    )

    res = mgr.evaluate_permission(req)
    assert res.decision == PermissionDecision.ALLOW_ONCE
    assert res.is_allowed is True
    assert res.source == PermissionSource.OPERATION
    assert res.expiration_ms == 60000.0


def test_dangerous_risk_level_requires_confirmation() -> None:
    """3 y 6. DANGEROUS -> REQUIRE_CONFIRMATION (sin desplegar UI o solicitar interactividad)."""
    mgr = PermissionManager()
    ctx = SecurityContext(user="user1", tool_name="delete_files")
    meta = ToolSecurityMetadata(tool_name="delete_files", risk_level=SecurityLevel.DANGEROUS)
    risk = RiskAssessment(risk_level=SecurityLevel.DANGEROUS, score=4, risk_factors={RiskFactor.DESTRUCTIVE_OPERATION})
    req = PermissionRequest(
        context=ctx, metadata=meta, risk_assessment=risk, tool_name="delete_files", operation="delete"
    )

    res = mgr.evaluate_permission(req)
    assert res.decision == PermissionDecision.REQUIRE_CONFIRMATION
    assert res.is_allowed is False
    assert res.source == PermissionSource.SYSTEM
    # Garantizar que no ejecute interacción ni UI alguna


def test_critical_risk_level_denied() -> None:
    """4 y 5. CRITICAL -> Estrategia segura DENY produciendo un reason explicativo no vacío."""
    mgr = PermissionManager()
    ctx = SecurityContext(user="user1", tool_name="registry_edit")
    meta = ToolSecurityMetadata(tool_name="registry_edit", risk_level=SecurityLevel.CRITICAL, requires_elevation=True)
    risk = RiskAssessment(risk_level=SecurityLevel.CRITICAL, score=5, risk_factors={RiskFactor.ELEVATED_PRIVILEGES})
    req = PermissionRequest(
        context=ctx, metadata=meta, risk_assessment=risk, tool_name="registry_edit", operation="edit_hklm"
    )

    res = mgr.evaluate_permission(req)
    assert res.decision == PermissionDecision.DENY
    assert res.is_allowed is False
    assert len(res.reason) > 0
    assert "elevación de privilegios" in res.reason or "UAC" in res.reason


def test_always_allow_representation() -> None:
    """8. ALWAYS_ALLOW se representa correctamente en el resultado de permisos."""
    res = PermissionResult(
        decision=PermissionDecision.ALWAYS_ALLOW,
        is_allowed=True,
        reason="Herramienta en lista blanca permanente.",
        source=PermissionSource.USER,
    )
    assert res.decision == PermissionDecision.ALWAYS_ALLOW
    assert res.is_allowed is True
    assert res.source == PermissionSource.USER


def test_valid_context_evaluated() -> None:
    """9. Contexto válido evaluado correctamente preservando correlation_id."""
    mgr = PermissionManager()
    ctx = SecurityContext(user="operator", correlation_id="test-corr-123")
    meta = ToolSecurityMetadata(tool_name="safe_tool", risk_level=SecurityLevel.SAFE)
    risk = RiskAssessment(risk_level=SecurityLevel.SAFE, score=2)
    req = PermissionRequest(
        context=ctx, metadata=meta, risk_assessment=risk, tool_name="safe_tool", operation="execute"
    )

    res = mgr.evaluate_permission(req)
    assert res.correlation_id == "test-corr-123"


def test_incomplete_context_failsafe_deny() -> None:
    """10, 11 y 13. Fail-Safe: Contexto incompleto, metadatos nulos o RiskAssessment inválido -> DENY."""
    mgr = PermissionManager()

    # Contexto None (se castea explícitamente para test de robustez)
    bad_req = PermissionRequest(
        context=None,  # type: ignore[arg-type]
        metadata=None,  # type: ignore[arg-type]
        risk_assessment=None,  # type: ignore[arg-type]
        tool_name="bad_tool",
        operation="run",
    )

    res = mgr.evaluate_permission(bad_req)
    assert res.decision == PermissionDecision.DENY
    assert res.is_allowed is False
    assert "Fail-Safe" in res.reason


def test_unknown_risk_level_failsafe_deny() -> None:
    """13. RiskAssessment con nivel desconocido -> Fail-Safe DENY."""
    mgr = PermissionManager()
    ctx = SecurityContext(user="user1")
    meta = ToolSecurityMetadata(tool_name="unknown_tool", risk_level=SecurityLevel.SAFE)
    risk = RiskAssessment(risk_level="INVALID_RISK_STRING", score=99)  # type: ignore[arg-type]
    req = PermissionRequest(
        context=ctx, metadata=meta, risk_assessment=risk, tool_name="unknown_tool", operation="unknown"
    )

    res = mgr.evaluate_permission(req)
    assert res.decision == PermissionDecision.DENY
    assert res.is_allowed is False
    assert "Fail-Safe" in res.reason


def test_strict_separation_risk_vs_permission() -> None:
    """14. Separación estricta entre evaluación de riesgo (RiskEngine) y decisión de autorización (PermissionManager)."""
    # 1. El RiskEngine calcula el riesgo puro
    risk = RiskAssessment(
        risk_level=SecurityLevel.DANGEROUS,
        score=4,
        reason="Operación destructiva",
        risk_factors={RiskFactor.DESTRUCTIVE_OPERATION},
    )

    # 2. El PermissionManager traduce el riesgo a una decisión de autorización
    mgr = PermissionManager()
    ctx = SecurityContext(user="user1")
    meta = ToolSecurityMetadata(tool_name="delete_tool", risk_level=SecurityLevel.DANGEROUS)
    req = PermissionRequest(context=ctx, metadata=meta, risk_assessment=risk, tool_name="delete_tool", operation="delete")

    perm = mgr.evaluate_permission(req)

    # El objeto de autorización es distinto y específico para el PermissionManager
    assert isinstance(perm, PermissionResult)
    assert perm.decision == PermissionDecision.REQUIRE_CONFIRMATION
    assert perm.source == PermissionSource.SYSTEM
    assert not hasattr(risk, "decision")
