"""Pruebas unitarias exclusivas de la Subetapa 04.2 — Risk Engine."""

from __future__ import annotations

from core.contracts import IRiskEvaluator
from core.risk_engine import (
    RiskAssessment,
    RiskEngine,
    RiskFactor,
)
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)


def test_risk_engine_implements_interface() -> None:
    """Verifica que RiskEngine cumpla el protocolo IRiskEvaluator."""
    engine = RiskEngine()
    assert isinstance(engine, IRiskEvaluator)


def test_safe_risk_level_identified() -> None:
    """1. Verifica que operaciones seguras (SAFE) sean identificadas correctamente."""
    engine = RiskEngine()
    ctx = SecurityContext(user="user1", tool_name="system_health")
    meta = ToolSecurityMetadata(tool_name="system_health", category="system", risk_level=SecurityLevel.SAFE)
    req = SecurityRequest(context=ctx, metadata=meta, action="read_status")

    assessment = engine.evaluate_risk(req)
    assert assessment.risk_level == SecurityLevel.SAFE
    assert assessment.score == 2
    assert assessment.tool_name == "system_health"


def test_warning_risk_level_identified() -> None:
    """2. Verifica que operaciones de riesgo moderado (WARNING) sean identificadas correctamente."""
    engine = RiskEngine()
    ctx = SecurityContext(user="user1", tool_name="write_file_tool", parameters={"path": "C:\\Temp\\doc.txt"})
    meta = ToolSecurityMetadata(tool_name="write_file_tool", category="filesystem", risk_level=SecurityLevel.SAFE)
    req = SecurityRequest(context=ctx, metadata=meta, action="write_content")

    assessment = engine.evaluate_risk(req)
    assert assessment.risk_level == SecurityLevel.WARNING
    assert assessment.score == 3
    assert RiskFactor.FILE_MODIFICATION in assessment.risk_factors


def test_dangerous_risk_level_identified() -> None:
    """3. Verifica que operaciones peligrosas (DANGEROUS) sean identificadas correctamente."""
    engine = RiskEngine()
    ctx = SecurityContext(user="user1", tool_name="delete_file_tool", parameters={"path": "C:\\Temp\\trash.zip"})
    meta = ToolSecurityMetadata(tool_name="delete_file_tool", category="filesystem", risk_level=SecurityLevel.SAFE)
    req = SecurityRequest(context=ctx, metadata=meta, action="delete_file")

    assessment = engine.evaluate_risk(req)
    assert assessment.risk_level == SecurityLevel.DANGEROUS
    assert assessment.score == 4
    assert RiskFactor.DESTRUCTIVE_OPERATION in assessment.risk_factors


def test_critical_risk_level_identified() -> None:
    """4. Verifica que operaciones críticas (CRITICAL) sean identificadas correctamente."""
    engine = RiskEngine()
    ctx = SecurityContext(user="user1", tool_name="format_disk", parameters={"path": "C:\\Windows\\System32"})
    meta = ToolSecurityMetadata(tool_name="format_disk", category="system", risk_level=SecurityLevel.CRITICAL)
    req = SecurityRequest(context=ctx, metadata=meta, action="format")

    assessment = engine.evaluate_risk(req)
    assert assessment.risk_level == SecurityLevel.CRITICAL
    assert assessment.score == 5
    assert RiskFactor.SYSTEM_CONFIGURATION in assessment.risk_factors


def test_multiple_risk_factors_aggregation() -> None:
    """5 y 6. Verifica la combinación de múltiples factores y la selección del riesgo máximo."""
    engine = RiskEngine()
    ctx = SecurityContext(
        user="admin",
        tool_name="bulk_delete",
        parameters={"path": "C:\\Windows\\System32\\drivers", "recursive": True},
    )
    meta = ToolSecurityMetadata(tool_name="bulk_delete", category="filesystem", risk_level=SecurityLevel.WARNING)
    req = SecurityRequest(context=ctx, metadata=meta, action="delete_recursive")

    assessment = engine.evaluate_risk(req)
    # Debe elevar a CRITICAL por la ruta C:\Windows\System32 aunque sea una operación de archivo
    assert assessment.risk_level == SecurityLevel.CRITICAL
    assert assessment.score == 5
    assert RiskFactor.SYSTEM_CONFIGURATION in assessment.risk_factors
    assert RiskFactor.BULK_OPERATION in assessment.risk_factors
    assert RiskFactor.DESTRUCTIVE_OPERATION in assessment.risk_factors


def test_unknown_operation_fail_safe_strategy() -> None:
    """7. Estrategia Fail-Safe: Operación desconocida no asume SAFE a ciegas."""
    engine = RiskEngine()
    ctx = SecurityContext(user="user1", tool_name="custom_unknown_tool")
    meta = ToolSecurityMetadata(tool_name="custom_unknown_tool", category="general", risk_level=SecurityLevel.SAFE)
    req = SecurityRequest(context=ctx, metadata=meta, action="unknown")

    assessment = engine.evaluate_risk(req)
    assert assessment.risk_level >= SecurityLevel.WARNING
    assert RiskFactor.UNKNOWN_OPERATION in assessment.risk_factors


def test_incomplete_metadata_handling() -> None:
    """8. Manejo seguro de metadatos incompletos."""
    engine = RiskEngine()
    ctx = SecurityContext(user="user1", tool_name="")
    meta = ToolSecurityMetadata(tool_name="unnamed_tool", category="", risk_level=SecurityLevel.SAFE)
    req = SecurityRequest(context=ctx, metadata=meta, action="")

    assessment = engine.evaluate_risk(req)
    assert assessment.risk_level >= SecurityLevel.WARNING


def test_elevation_requirement_handling() -> None:
    """9. Manejo de requerimientos de elevación UAC (CRITICAL + ELEVATED_PRIVILEGES)."""
    engine = RiskEngine()
    ctx = SecurityContext(user="operator", tool_name="registry_editor")
    meta = ToolSecurityMetadata(
        tool_name="registry_editor",
        category="system",
        risk_level=SecurityLevel.SAFE,
        requires_elevation=True,
    )
    req = SecurityRequest(context=ctx, metadata=meta, action="edit_reg")

    assessment = engine.evaluate_risk(req)
    assert assessment.risk_level == SecurityLevel.CRITICAL
    assert RiskFactor.ELEVATED_PRIVILEGES in assessment.risk_factors


def test_risk_assessment_separation_from_decisions() -> None:
    """10. Separación entre RiskAssessment y decisiones (no retorna ALLOW, DENY ni ASK)."""
    engine = RiskEngine()
    ctx = SecurityContext(user="user1", tool_name="delete_files")
    meta = ToolSecurityMetadata(tool_name="delete_files", risk_level=SecurityLevel.DANGEROUS)
    req = SecurityRequest(context=ctx, metadata=meta, action="delete")

    assessment = engine.evaluate_risk(req)
    assert isinstance(assessment, RiskAssessment)
    assert hasattr(assessment, "risk_level")
    assert hasattr(assessment, "risk_factors")
    # No contiene métodos de decisión ni ejecuciones
    assert not hasattr(assessment, "decision_type")
    assert not hasattr(assessment, "execute")


def test_risk_engine_has_zero_side_effects() -> None:
    """11. El RiskEngine es una pieza pura de evaluación sin efectos secundarios ni ejecución."""
    engine = RiskEngine()
    ctx = SecurityContext(user="test_user", tool_name="mock_tool", parameters={"cmd": "echo 1"})
    meta = ToolSecurityMetadata(tool_name="mock_tool", risk_level=SecurityLevel.SAFE)
    req = SecurityRequest(context=ctx, metadata=meta, action="run")

    res1 = engine.evaluate_risk(req)
    res2 = engine.evaluate_risk(req)

    # Evaluación pura y determinista
    assert res1.risk_level == res2.risk_level
    assert res1.risk_factors == res2.risk_factors
