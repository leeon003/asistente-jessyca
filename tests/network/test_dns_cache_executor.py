"""Pruebas de la integración de get_dns_cache en WindowsNetworkToolExecutor (Subetapa 09.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from tools.network.dns_cache_backend import FakeDNSCacheInspectionBackend
from tools.network.dns_cache_service import DNSCacheInspectionService
from tools.network.executor import WindowsNetworkToolExecutor


def test_windows_network_tool_executor_executes_dns_cache() -> None:
    dns_service = DNSCacheInspectionService(backend=FakeDNSCacheInspectionBackend())
    executor = WindowsNetworkToolExecutor(dns_cache_service=dns_service)

    req = ExecutionRequest(
        request_id="net-dns-exec-1",
        tool_name="windows.network",
        operation="get_dns_cache",
        parameters={"record_type": "A"},
        context=RequestContext(user="tester"),
    )

    evidence = AuthorizationEvidence(
        evidence_id="ev-dns-1",
        request_id="net-dns-exec-1",
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
