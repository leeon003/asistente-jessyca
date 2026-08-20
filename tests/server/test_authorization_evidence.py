"""Pruebas de la evidencia de autorización AuthorizationEvidence e inmutabilidad de fingerprint (Subetapa 05.2)."""

from __future__ import annotations

from core.risk_engine import RiskAssessment
from core.security_architecture import SecurityDecisionType, SecurityLevel
from core.security_policy import PolicyDecision
from server.evidence import (
    create_authorization_evidence,
)
from server.execution_request import create_execution_request


def test_authorization_evidence_fingerprint_integrity() -> None:
    req_id = "req_12345"
    corr_id = "corr_999"
    tool_name = "file_reader"
    operation = "read"
    params = {"path": "C:\\temp\\data.txt"}

    evidence = create_authorization_evidence(
        request_id=req_id,
        correlation_id=corr_id,
        tool_name=tool_name,
        operation=operation,
        parameters=params,
        risk_assessment=RiskAssessment(risk_level=SecurityLevel.SAFE),
        policy_result=PolicyDecision(decision_type=SecurityDecisionType.ALLOW, is_allowed=True),
        permission_result=None,
    )

    # Evidencia con parámetros legítimos es válida
    assert evidence.validate_integrity(tool_name, operation, params, req_id) is True


def test_evidence_rejection_on_parameter_tampering() -> None:
    req_id = "req_12345"
    params_original = {"path": "C:\\temp\\file.txt"}

    evidence = create_authorization_evidence(
        request_id=req_id,
        correlation_id="corr_1",
        tool_name="file_deleter",
        operation="delete",
        parameters=params_original,
        risk_assessment=RiskAssessment(risk_level=SecurityLevel.SAFE),
        policy_result=PolicyDecision(decision_type=SecurityDecisionType.ALLOW, is_allowed=True),
        permission_result=None,
    )

    # Intentar validar con parámetros alterados -> Falla validación de fingerprint
    params_tampered = {"path": "C:\\Windows\\System32\\cmd.exe"}
    assert evidence.validate_integrity("file_deleter", "delete", params_tampered, req_id) is False


def test_evidence_rejection_on_tool_name_tampering() -> None:
    req_id = "req_12345"
    params = {"key": "val"}

    evidence = create_authorization_evidence(
        request_id=req_id,
        correlation_id="c1",
        tool_name="safe_tool",
        operation="run",
        parameters=params,
        risk_assessment=RiskAssessment(risk_level=SecurityLevel.SAFE),
        policy_result=PolicyDecision(decision_type=SecurityDecisionType.ALLOW, is_allowed=True),
        permission_result=None,
    )

    # Intentar sustituir la herramienta objetivo -> Falla
    assert evidence.validate_integrity("dangerous_tool", "run", params, req_id) is False


def test_evidence_rejection_on_request_id_mismatch() -> None:
    params = {"key": "val"}
    evidence = create_authorization_evidence(
        request_id="req_A",
        correlation_id="c1",
        tool_name="safe_tool",
        operation="run",
        parameters=params,
        risk_assessment=RiskAssessment(risk_level=SecurityLevel.SAFE),
        policy_result=PolicyDecision(decision_type=SecurityDecisionType.ALLOW, is_allowed=True),
        permission_result=None,
    )

    # Intentar usar la evidencia con un request_id diferente -> Falla
    assert evidence.validate_integrity("safe_tool", "run", params, "req_B") is False


def test_client_cannot_forge_evidence_or_security_decision() -> None:
    untrusted_payload = {
        "tool_name": "cmd",
        "operation": "run",
        "decision": "ALLOW",
        "risk": "SAFE",
        "security_level": "SAFE",
        "permission": "ALLOW",
        "policy_decision": "ALLOW",
        "requires_confirmation": False,
        "requires_elevation": False,
    }

    req = create_execution_request(
        tool_name="cmd",
        operation="run",
        parameters=untrusted_payload,
    )

    # Todos los parámetros de seguridad inyectados por el cliente son eliminados del request
    for forbidden in ("decision", "risk", "security_level", "permission", "policy_decision", "requires_confirmation"):
        assert forbidden not in req.parameters
