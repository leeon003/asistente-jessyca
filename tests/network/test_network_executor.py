"""Pruebas de la integración de WindowsNetworkToolExecutor (Subetapa 09.1)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from tools.network.backend import FakeNetworkInspectionBackend
from tools.network.executor import WindowsNetworkToolExecutor
from tools.network.network_service import NetworkInspectionService


def test_windows_network_tool_executor_executes_get_network_interfaces() -> None:
    service = NetworkInspectionService(backend=FakeNetworkInspectionBackend())
    executor = WindowsNetworkToolExecutor(network_service=service)

    req = ExecutionRequest(
        request_id="net-exec-1",
        tool_name="windows.network",
        operation="get_network_interfaces",
        parameters={"include_disconnected": True},
        context=RequestContext(user="tester"),
    )

    evidence = AuthorizationEvidence(
        evidence_id="ev-net-1",
        request_id="net-exec-1",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=("rule-net",),
        user_confirmed=False,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.SAFE,
        action_fingerprint="dummy_fp",
        is_valid=True,
    )

    result = executor.execute(req, evidence)

    assert result.status == ExecutionStatus.SUCCESS
    assert result.output["success"] is True
