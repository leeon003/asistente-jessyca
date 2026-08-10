"""Pruebas de consolidación y auditoría de la frontera de seguridad de red (Subetapa 09.4).

Verifica transversalmente que las 5 operaciones de `windows.network`:
- get_network_interfaces
- get_active_connections
- get_listening_ports
- get_routing_table
- get_dns_cache

cumplan las 20 invariantes globales de seguridad de la ETAPA 09.
"""

from __future__ import annotations

import concurrent.futures
import inspect
import re
import pytest

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.network_boundary_security import (
    NetworkBoundaryConsolidator,
    NetworkBoundarySecurityError,
)
from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.network.connection_backend import FakeNetworkConnectionInspectionBackend
from tools.network.connection_service import NetworkConnectionInspectionService
from tools.network.dns_cache_backend import FakeDNSCacheInspectionBackend
from tools.network.dns_cache_service import DNSCacheInspectionService
from tools.network.executor import WindowsNetworkToolExecutor
from tools.network.backend import FakeNetworkInspectionBackend
from tools.network.network_service import NetworkInspectionService
from tools.network.routing_backend import FakeRoutingTableInspectionBackend
from tools.network.routing_service import RoutingTableInspectionService


def test_network_boundary_pipeline_enforcement_all_operations() -> None:
    """Verifica que las 5 operaciones de windows.network atraviesen obligatoriamente el SecureExecutionPipeline."""
    pipeline = SecureExecutionPipeline()

    net_serv = NetworkInspectionService(backend=FakeNetworkInspectionBackend())
    conn_serv = NetworkConnectionInspectionService(backend=FakeNetworkConnectionInspectionBackend())
    route_serv = RoutingTableInspectionService(backend=FakeRoutingTableInspectionBackend())
    dns_serv = DNSCacheInspectionService(backend=FakeDNSCacheInspectionBackend())

    executor = WindowsNetworkToolExecutor(
        network_service=net_serv,
        connection_service=conn_serv,
        routing_service=route_serv,
        dns_cache_service=dns_serv,
    )
    pipeline.boundary.register_executor("windows.network", executor)

    operations = [
        ("get_network_interfaces", {}),
        ("get_active_connections", {"protocol": "TCP"}),
        ("get_listening_ports", {}),
        ("get_routing_table", {"address_family": "IPv4"}),
        ("get_dns_cache", {"record_type": "A"}),
    ]

    for op, params in operations:
        req = ExecutionRequest(
            request_id=f"pipeline-cons-{op}",
            tool_name="windows.network",
            operation=op,
            parameters=params,
            context=RequestContext(user="admin_tester"),
        )
        res = pipeline.execute_request(req)
        assert res.status == ExecutionStatus.SUCCESS, f"La operación '{op}' falló en el pipeline"
        assert res.output["success"] is True


def test_network_boundary_invalid_evidence_rejection() -> None:
    """Verifica que evidencias inválidas sean rechazadas con FAIL-SAFE DENY."""
    consolidator = NetworkBoundaryConsolidator()
    req = ExecutionRequest(
        request_id="req-invalid-ev",
        tool_name="windows.network",
        operation="get_network_interfaces",
        parameters={},
        context=RequestContext(user="tester"),
    )

    invalid_evidence = AuthorizationEvidence(
        evidence_id="ev-invalid",
        request_id="mismatched-req-id",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=(),
        user_confirmed=False,
        evaluation_timestamp=req.timestamp,
        risk_level=SecurityLevel.SAFE,
        action_fingerprint="short_fp",
        is_valid=False,
    )

    assert consolidator.verify_pipeline_authorization(req, invalid_evidence) is False


def test_network_boundary_security_source_audit() -> None:
    """Auditoría de código fuente recursiva verificando ZERO SHELL EXECUTION en core/network_*.py y tools/network/*.py."""
    import core.network_boundary_security as net_bnd
    import core.network_connection_security as net_conn_sec
    import core.network_routing_security as net_rt_sec
    import core.network_security as net_sec
    import tools.network.backend as net_bk
    import tools.network.connection_backend as conn_bk
    import tools.network.dns_cache_backend as dns_bk
    import tools.network.executor as net_ex
    import tools.network.routing_backend as rt_bk

    modules = [
        net_bnd,
        net_conn_sec,
        net_rt_sec,
        net_sec,
        net_bk,
        conn_bk,
        dns_bk,
        net_ex,
        rt_bk,
    ]

    forbidden_patterns = [
        r"\bsubprocess\b",
        r"shell\s*=\s*True",
        r"\bos\.system\b",
        r"\bos\.popen\b",
        r"\bcmd\.exe\b",
        r"\bpowershell\.exe\b",
        r"\bnetsh\b",
        r"\bipconfig\b",
        r"\broute\s+print\b",
        r"\brp\s+nslookup\b",
        r"\bGet-DnsClientCache\b",
        r"\beval\(",
        r"\bexec\(",
    ]

    for mod in modules:
        source_code = inspect.getsource(mod)
        for pattern in forbidden_patterns:
            matches = re.findall(pattern, source_code, flags=re.IGNORECASE)
            assert len(matches) == 0, f"Patrón prohibido '{pattern}' encontrado en módulo {mod.__name__}: {matches}"


def test_network_boundary_transversal_privacy_audit_logging() -> None:
    """Verifica que AuditLogger y EventBus reciban ÚNICAMENTE METADATOS para las 5 operaciones."""
    sink = MemoryAuditSink()

    net_serv = NetworkInspectionService(backend=FakeNetworkInspectionBackend())
    conn_serv = NetworkConnectionInspectionService(backend=FakeNetworkConnectionInspectionBackend())
    route_serv = RoutingTableInspectionService(backend=FakeRoutingTableInspectionBackend())
    dns_serv = DNSCacheInspectionService(backend=FakeDNSCacheInspectionBackend())

    for s in (net_serv, conn_serv, route_serv, dns_serv):
        s.audit_logger.add_sink(sink)

    net_serv.get_network_interfaces(type("Req", (), {"include_disconnected": False, "include_virtual": False, "interface_name_filter": None, "to_dict": lambda s: {}})())  # type: ignore
    conn_serv.get_active_connections(type("Req", (), {"protocol": "TCP", "state": None, "local_address": None, "local_port": None, "remote_address": None, "remote_port": None, "process_id": None, "include_process_info": True, "max_results": 1000, "to_dict": lambda s: {}})())  # type: ignore
    conn_serv.get_listening_ports(type("Req", (), {"protocol": "TCP", "state": None, "local_address": None, "local_port": None, "remote_address": None, "remote_port": None, "process_id": None, "include_process_info": True, "max_results": 1000, "to_dict": lambda s: {}})())  # type: ignore
    route_serv.get_routing_table(type("Req", (), {"address_family": "IPv4", "destination": None, "gateway": None, "interface": None, "metric": None, "protocol": None, "max_results": 2048, "to_dict": lambda s: {}})())  # type: ignore
    dns_serv.get_dns_cache(type("Req", (), {"hostname": None, "record_type": "A", "address_family": None, "value": None, "max_results": 4096, "to_dict": lambda s: {}})())  # type: ignore

    events = sink.get_events(tool_name="windows.network")
    assert len(events) >= 5

    sensitive_tokens = ["192.168.1.100", "54321", "chrome.exe", "google.com", "142.250.190.46", "0.0.0.0"]

    for ev in events:
        meta_str = str(ev.metadata)
        for token in sensitive_tokens:
            assert token not in meta_str, f"Token sensible '{token}' encontrado en metadata de auditoría ({ev.event_type}): {meta_str}"


def test_network_boundary_transversal_concurrency() -> None:
    """Verifica ejecuciones multi-hilo concurrentes simultáneas de las 5 operaciones."""
    net_serv = NetworkInspectionService(backend=FakeNetworkInspectionBackend())
    conn_serv = NetworkConnectionInspectionService(backend=FakeNetworkConnectionInspectionBackend())
    route_serv = RoutingTableInspectionService(backend=FakeRoutingTableInspectionBackend())
    dns_serv = DNSCacheInspectionService(backend=FakeDNSCacheInspectionBackend())

    executor = WindowsNetworkToolExecutor(
        network_service=net_serv,
        connection_service=conn_serv,
        routing_service=route_serv,
        dns_cache_service=dns_serv,
    )

    ops = ["get_network_interfaces", "get_active_connections", "get_listening_ports", "get_routing_table", "get_dns_cache"]

    def run_op(idx: int) -> bool:
        op = ops[idx % len(ops)]
        req = ExecutionRequest(
            request_id=f"concurrent-{idx}",
            tool_name="windows.network",
            operation=op,
            parameters={},
            context=RequestContext(user="concurrent_tester"),
        )
        evidence = AuthorizationEvidence(
            evidence_id=f"ev-{idx}",
            request_id=f"concurrent-{idx}",
            decision=PermissionDecision.ALLOW,
            policy_rules_evaluated=(),
            user_confirmed=False,
            evaluation_timestamp=req.timestamp,
            risk_level=SecurityLevel.SAFE,
            action_fingerprint="valid_fingerprint_hash_string",
            is_valid=True,
        )
        res = executor.execute(req, evidence)
        return res.status == ExecutionStatus.SUCCESS

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as tp:
        futures = [tp.submit(run_op, i) for i in range(30)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)


def test_network_boundary_transversal_fuzzing() -> None:
    """Fuzzing transversal sobre la frontera NetworkBoundaryConsolidator."""
    consolidator = NetworkBoundaryConsolidator()

    invalid_param_sets = [
        {"port": -1},
        {"port": 70000},
        {"local_port": "NaN"},
        {"remote_port": "Infinity"},
        {"process_id": -100},
        {"metric": -5},
        {"max_results": -10},
        {"max_results": 0},
        {"hostname": "google.com\x00evil.com"},
        {"destination": "256.256.256.256"},
    ]

    for params in invalid_param_sets:
        with pytest.raises(NetworkBoundarySecurityError):
            consolidator.validate_request_parameters("get_active_connections", params)
