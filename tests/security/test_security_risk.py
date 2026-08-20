"""Pruebas adversariales de inspección de riesgo y ataques a rutas del sistema (Subetapa 04.7)."""

from __future__ import annotations

from core.risk_engine import RiskEngine, RiskFactor
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)


def test_path_traversal_detection_dot_dot_slash() -> None:
    engine = RiskEngine()
    ctx = SecurityContext(
        user="test_user",
        tool_name="file_reader",
        parameters={"path": "../../../Windows/System32/config/SAM"},
    )
    meta = ToolSecurityMetadata(tool_name="file_reader", risk_level=SecurityLevel.SAFE)
    req = SecurityRequest(context=ctx, metadata=meta, action="read")

    assessment = engine.evaluate_risk(req)
    assert assessment.risk_level == SecurityLevel.CRITICAL
    assert RiskFactor.SYSTEM_CONFIGURATION in assessment.risk_factors


def test_path_traversal_detection_dot_dot_backslash() -> None:
    engine = RiskEngine()
    ctx = SecurityContext(
        user="test_user",
        tool_name="file_reader",
        parameters={"path": "..\\..\\..\\Windows\\System32\\cmd.exe"},
    )
    meta = ToolSecurityMetadata(tool_name="file_reader", risk_level=SecurityLevel.SAFE)
    req = SecurityRequest(context=ctx, metadata=meta, action="read")

    assessment = engine.evaluate_risk(req)
    assert assessment.risk_level == SecurityLevel.CRITICAL


test_paths = [
    "C:\\Windows\\System32\\drivers\\etc\\hosts",
    "c:/windows/system32",
    "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft",
    "\\\\localhost\\c$\\Windows\\System32",
]


def test_critical_system_paths_matrix() -> None:
    engine = RiskEngine()
    for path in test_paths:
        ctx = SecurityContext(
            user="test",
            tool_name="sys_tool",
            parameters={"target": path},
        )
        meta = ToolSecurityMetadata(tool_name="sys_tool", risk_level=SecurityLevel.SAFE)
        assessment = engine.evaluate_risk(SecurityRequest(context=ctx, metadata=meta))
        assert assessment.risk_level == SecurityLevel.CRITICAL, f"Fallo al detectar ruta crítica: {path}"


def test_unknown_operation_failsafe() -> None:
    engine = RiskEngine()
    ctx = SecurityContext(user="test", tool_name="unknown_tool", parameters={"operation": ""})
    meta = ToolSecurityMetadata(tool_name="unknown_tool", risk_level=SecurityLevel.SAFE)
    req = SecurityRequest(context=ctx, metadata=meta, action="")

    assessment = engine.evaluate_risk(req)
    assert assessment.risk_level in (SecurityLevel.WARNING, SecurityLevel.DANGEROUS, SecurityLevel.CRITICAL)
    assert RiskFactor.UNKNOWN_OPERATION in assessment.risk_factors


def test_unicode_and_special_character_inputs() -> None:
    engine = RiskEngine()
    ctx = SecurityContext(
        user="👤_admin_ユーザー",
        tool_name="tool_🔥",
        parameters={"file": "C:\\Windows\\System32\\test_🚀.dll", "cmd": "del /f /s /q *"},
    )
    meta = ToolSecurityMetadata(tool_name="tool_🔥", risk_level=SecurityLevel.SAFE)

    assessment = engine.evaluate_risk(SecurityRequest(context=ctx, metadata=meta))
    assert assessment.risk_level == SecurityLevel.CRITICAL  # Detecta C:\Windows\System32
