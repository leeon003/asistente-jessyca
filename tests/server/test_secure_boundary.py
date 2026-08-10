"""Pruebas de la frontera de ejecución SecureExecutionBoundary (Subetapa 05.2)."""

from __future__ import annotations

import pytest

from core.risk_engine import RiskAssessment
from core.security_architecture import SecurityDecisionType, SecurityLevel
from core.security_policy import PolicyDecision
from server.boundary import ExecutionStatus, SecureExecutionBoundary
from server.errors import InvalidAuthorizationEvidenceError
from server.evidence import create_authorization_evidence
from server.execution_request import create_execution_request
from server.executor import DisabledToolExecutor


def test_secure_boundary_requires_valid_evidence() -> None:
    boundary = SecureExecutionBoundary(executor=DisabledToolExecutor())
    req = create_execution_request(tool_name="test_tool", operation="run")

    # Invocación sin evidencia -> Lanza InvalidAuthorizationEvidenceError
    with pytest.raises(InvalidAuthorizationEvidenceError):
        boundary.execute_with_evidence(req, None)  # type: ignore[arg-type]


def test_secure_boundary_validates_evidence_fingerprint() -> None:
    boundary = SecureExecutionBoundary(executor=DisabledToolExecutor())
    req = create_execution_request(tool_name="test_tool", operation="run", parameters={"key": "val"})

    evidence = create_authorization_evidence(
        request_id=req.request_id,
        correlation_id=req.correlation_id,
        tool_name="test_tool",
        operation="run",
        parameters={"key": "val"},
        risk_assessment=RiskAssessment(risk_level=SecurityLevel.SAFE),
        policy_result=PolicyDecision(decision_type=SecurityDecisionType.ALLOW, is_allowed=True),
        permission_result=None,
    )

    res = boundary.execute_with_evidence(req, evidence)
    assert res.status in (ExecutionStatus.EXECUTION_DISABLED, ExecutionStatus.STUB_DISABLED)
    assert res.tool_name == "test_tool"


def test_secure_boundary_rejects_tampered_request_parameters() -> None:
    boundary = SecureExecutionBoundary(executor=DisabledToolExecutor())
    req_original = create_execution_request(tool_name="test_tool", operation="run", parameters={"path": "file.txt"})

    evidence = create_authorization_evidence(
        request_id=req_original.request_id,
        correlation_id=req_original.correlation_id,
        tool_name="test_tool",
        operation="run",
        parameters={"path": "file.txt"},
        risk_assessment=RiskAssessment(risk_level=SecurityLevel.SAFE),
        policy_result=PolicyDecision(decision_type=SecurityDecisionType.ALLOW, is_allowed=True),
        permission_result=None,
    )

    # Crear una solicitud modificada después de la autorización
    req_tampered = create_execution_request(
        tool_name="test_tool",
        operation="run",
        parameters={"path": "C:\\Windows\\System32\\cmd.exe"},
        context=req_original.context,
    )

    with pytest.raises(InvalidAuthorizationEvidenceError):
        boundary.execute_with_evidence(req_tampered, evidence)
