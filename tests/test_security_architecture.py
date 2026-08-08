"""Pruebas unitarias exclusivas para la Subetapa 04.1 — Security Architecture Foundation."""

from __future__ import annotations

from datetime import datetime

import pytest

from core.contracts import ISecurityEvaluator
from core.security_architecture import (
    BaseSecurityManager,
    SecurityContext,
    SecurityDecision,
    SecurityDecisionType,
    SecurityLevel,
    SecurityRequest,
    SecurityResult,
    ToolSecurityMetadata,
)


def test_security_enums_and_levels() -> None:
    """Verifica que los Enums de niveles y decisiones de seguridad se creen correctamente."""
    assert SecurityLevel.SAFE.value == "SAFE"
    assert SecurityLevel.WARNING.value == "WARNING"
    assert SecurityLevel.DANGEROUS.value == "DANGEROUS"
    assert SecurityLevel.CRITICAL.value == "CRITICAL"

    assert SecurityDecisionType.ALLOW.value == "ALLOW"
    assert SecurityDecisionType.DENY.value == "DENY"
    assert SecurityDecisionType.REQUIRE_CONFIRMATION.value == "REQUIRE_CONFIRMATION"
    assert SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION.value == "REQUIRE_ELEVATED_AUTHORIZATION"


def test_security_context_creation_and_fields() -> None:
    """Verifica el correcto funcionamiento y valores por defecto de SecurityContext."""
    ctx = SecurityContext(user="operator", tool_name="read_file", parameters={"path": "C:\\Temp"})

    assert ctx.user == "operator"
    assert ctx.tool_name == "read_file"
    assert ctx.parameters == {"path": "C:\\Temp"}
    assert isinstance(ctx.timestamp, datetime)
    assert ctx.correlation_id is not None
    assert ctx.environment == "windows"


def test_tool_security_metadata() -> None:
    """Verifica el modelo de metadatos de seguridad de herramientas MCP."""
    meta = ToolSecurityMetadata(
        tool_name="delete_directory",
        category="filesystem",
        risk_level=SecurityLevel.DANGEROUS,
        requires_confirmation=True,
        allowed_operations=["delete"],
    )

    assert meta.tool_name == "delete_directory"
    assert meta.category == "filesystem"
    assert meta.risk_level == SecurityLevel.DANGEROUS
    assert meta.requires_confirmation is True
    assert meta.requires_elevation is False
    assert meta.allowed_operations == ["delete"]


def test_security_request_and_decision() -> None:
    """Verifica la composición de SecurityRequest y SecurityDecision."""
    ctx = SecurityContext(user="admin")
    meta = ToolSecurityMetadata(tool_name="system_reboot", risk_level=SecurityLevel.CRITICAL)
    req = SecurityRequest(context=ctx, metadata=meta, action="reboot")

    assert req.context.user == "admin"
    assert req.metadata.tool_name == "system_reboot"
    assert req.action == "reboot"
    assert req.request_id is not None

    decision = SecurityDecision(
        decision_type=SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION,
        reason="Requiere UAC",
        requires_elevation=True,
    )
    assert bool(decision) is False
    assert decision.requires_elevation is True


def test_security_evaluator_interface_contract() -> None:
    """Verifica que BaseSecurityManager cumpla el protocolo ISecurityEvaluator."""
    manager = BaseSecurityManager()
    assert isinstance(manager, ISecurityEvaluator)

    # 1. Herramienta segura -> ALLOW
    ctx1 = SecurityContext(user="user1", tool_name="read_file")
    meta1 = ToolSecurityMetadata(tool_name="read_file", risk_level=SecurityLevel.SAFE)
    req1 = SecurityRequest(context=ctx1, metadata=meta1)

    res1 = manager.evaluate(req1)
    assert isinstance(res1, SecurityResult)
    assert res1.is_allowed is True
    assert res1.decision.decision_type == SecurityDecisionType.ALLOW

    # 2. Herramienta peligrosa -> REQUIRE_CONFIRMATION
    ctx2 = SecurityContext(user="user1", tool_name="delete_files")
    meta2 = ToolSecurityMetadata(tool_name="delete_files", risk_level=SecurityLevel.DANGEROUS)
    req2 = SecurityRequest(context=ctx2, metadata=meta2)

    res2 = manager.evaluate(req2)
    assert res2.is_allowed is False
    assert res2.decision.decision_type == SecurityDecisionType.REQUIRE_CONFIRMATION

    # 3. Herramienta crítica -> REQUIRE_ELEVATED_AUTHORIZATION
    ctx3 = SecurityContext(user="user1", tool_name="format_disk")
    meta3 = ToolSecurityMetadata(tool_name="format_disk", risk_level=SecurityLevel.CRITICAL)
    req3 = SecurityRequest(context=ctx3, metadata=meta3)

    res3 = manager.evaluate(req3)
    assert res3.is_allowed is False
    assert res3.decision.decision_type == SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION


def test_invalid_security_model_values_rejected() -> None:
    """Verifica que valores inválidos sean rechazados en los modelos de seguridad."""
    with pytest.raises(ValueError, match="user"):
        SecurityContext(user="   ")

    with pytest.raises(ValueError, match="tool_name"):
        ToolSecurityMetadata(tool_name="")
