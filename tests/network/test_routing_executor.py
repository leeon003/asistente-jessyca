"""Pruebas de la integración de get_routing_table en WindowsNetworkToolExecutor (Subetapa 09.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from tools.network.executor import WindowsNetworkToolExecutor
from tools.network.routing_backend import FakeRoutingTableInspectionBackend
from tools.network.routing_service import RoutingTableInspectionService


def test_windows_network_tool_executor_executes_routing_table() -> None:
    r_service = RoutingTableInspectionService(backend=FakeRoutingTableInspectionBackend())
    executor = WindowsNetworkToolExecutor(routing_service=r_service)

    req = ExecutionRequest(
        request_id="net-route-exec-1",
        tool_name="windows.network",
        operation="get_routing_table",
        parameters={"address_family": "IPv4"},
        context=RequestContext(user="tester"),
    )

    evidence = AuthorizationEvidence(
        evidence_id="ev-route-1",
        request_id="net-route-exec-1",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=(),
        user_confirmed=False,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.SAFE,
        action_fingerprint="dummy_fp",
        is_valid=True,
    )

    result = executor.execute(req, evidence)
    assert result.status == ExecutionStatus.SUCCESS
    assert result.output["success"] is True
