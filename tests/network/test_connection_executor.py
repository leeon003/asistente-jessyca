"""Pruebas de la integración de operaciones de conexiones en WindowsNetworkToolExecutor (Subetapa 09.2)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from tools.network.connection_backend import FakeNetworkConnectionInspectionBackend
from tools.network.connection_service import NetworkConnectionInspectionService
from tools.network.executor import WindowsNetworkToolExecutor


def test_windows_network_tool_executor_executes_connections_operations() -> None:
    conn_service = NetworkConnectionInspectionService(backend=FakeNetworkConnectionInspectionBackend())
    executor = WindowsNetworkToolExecutor(connection_service=conn_service)

    req1 = ExecutionRequest(
        request_id="net-conn-exec-1",
        tool_name="windows.network",
        operation="get_active_connections",
        parameters={"protocol": "TCP"},
        context=RequestContext(user="tester"),
    )

    evidence1 = AuthorizationEvidence(
        evidence_id="ev-conn-1",
        request_id="net-conn-exec-1",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=(),
        user_confirmed=False,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.SAFE,
        action_fingerprint="dummy_fp",
        is_valid=True,
    )

    result1 = executor.execute(req1, evidence1)
    assert result1.status == ExecutionStatus.SUCCESS
    assert result1.output["success"] is True

    req2 = ExecutionRequest(
        request_id="net-port-exec-1",
        tool_name="windows.network",
        operation="get_listening_ports",
        parameters={},
        context=RequestContext(user="tester"),
    )

    result2 = executor.execute(req2, evidence1)
    assert result2.status == ExecutionStatus.SUCCESS
    assert result2.output["success"] is True
