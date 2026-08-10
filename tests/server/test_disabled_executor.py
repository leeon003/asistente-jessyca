"""Pruebas de DisabledToolExecutor y garantías de cero ejecución (Subetapa 05.2)."""

from __future__ import annotations

import sys

from core.risk_engine import RiskAssessment
from core.security_architecture import SecurityDecisionType, SecurityLevel
from core.security_policy import PolicyDecision
from server.boundary import ExecutionStatus
from server.evidence import create_authorization_evidence
from server.execution_request import create_execution_request
from server.executor import DisabledToolExecutor


def test_disabled_executor_returns_stub_disabled_result() -> None:
    executor = DisabledToolExecutor()
    req = create_execution_request(tool_name="cmd_tool", operation="execute", parameters={"command": "dir"})

    evidence = create_authorization_evidence(
        request_id=req.request_id,
        correlation_id=req.correlation_id,
        tool_name="cmd_tool",
        operation="execute",
        parameters={"command": "dir"},
        risk_assessment=RiskAssessment(risk_level=SecurityLevel.SAFE),
        policy_result=PolicyDecision(decision_type=SecurityDecisionType.ALLOW, is_allowed=True),
        permission_result=None,
    )

    res = executor.execute(req, evidence)

    assert res.status in (ExecutionStatus.EXECUTION_DISABLED, ExecutionStatus.STUB_DISABLED)
    assert "EXECUTION_DISABLED_IN_05_2" in res.message
    assert res.output is None


def test_zero_os_subprocess_or_powershell_invocation() -> None:
    executor = DisabledToolExecutor()

    # Verificar que DisabledToolExecutor no tenga referencias o métodos para ejecutar comandos del SO
    assert not hasattr(executor, "subprocess")
    assert not hasattr(executor, "powershell")
    assert not hasattr(executor, "cmd")
    assert not hasattr(executor, "ctypes")
    assert not hasattr(executor, "system")
