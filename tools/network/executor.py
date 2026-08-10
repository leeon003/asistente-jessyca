"""Ejecutor real seguro para herramientas de diagnóstico de red (WindowsNetworkToolExecutor - Subetapa 09.1).

Ejecuta la operación get_network_interfaces únicamente tras recibir una ExecutionRequest y AuthorizationEvidence
válidas y verificadas por la frontera de seguridad.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.audit_logger import get_audit_logger
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.network_connection_models import NetworkConnectionRequest
from core.network_models import NetworkInterfaceRequest
from core.network_routing_models import DNSCacheRequest, RoutingTableRequest
from server.boundary import ExecutionResult, ExecutionStatus
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest
from core.network_boundary_security import NetworkBoundaryConsolidator
from server.executor import IToolExecutor
from tools.network.connection_service import NetworkConnectionInspectionService
from tools.network.dns_cache_service import DNSCacheInspectionService
from tools.network.network_service import NetworkInspectionService
from tools.network.routing_service import RoutingTableInspectionService

logger = get_logger("jessyca.tools.network.executor")


class WindowsNetworkToolExecutor(IToolExecutor):
    """Ejecutor real seguro para la herramienta de diagnóstico de red (`windows.network`)."""

    def __init__(
        self,
        network_service: NetworkInspectionService | None = None,
        connection_service: NetworkConnectionInspectionService | None = None,
        routing_service: RoutingTableInspectionService | None = None,
        dns_cache_service: DNSCacheInspectionService | None = None,
        boundary_consolidator: NetworkBoundaryConsolidator | None = None,
    ) -> None:
        self.network_service = network_service or NetworkInspectionService()
        self.connection_service = connection_service or NetworkConnectionInspectionService()
        self.routing_service = routing_service or RoutingTableInspectionService()
        self.dns_cache_service = dns_cache_service or DNSCacheInspectionService()
        self.boundary_consolidator = boundary_consolidator or NetworkBoundaryConsolidator()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def execute(
        self,
        request: ExecutionRequest,
        evidence: AuthorizationEvidence,
    ) -> ExecutionResult:
        """Ejecuta la operación de inspección de adaptadores, conexiones, puertos, ruteo o caché DNS autorizada por el pipeline."""
        start_time = datetime.now(UTC)
        op = request.operation.lower()
        params = request.parameters
        req_id = request.request_id

        # 1. Verificación de evidencia y frontera de autorización (FAIL-SAFE DENY)
        if not self.boundary_consolidator.verify_pipeline_authorization(request, evidence):
            raise PermissionError(f"Evidencia de autorización rechazada por la frontera de seguridad para la operación '{op}'")

        # 2. Validación transversal de parámetros de entrada
        self.boundary_consolidator.validate_request_parameters(op, params)

        logger.info(f"[NETWORK EXECUTOR] Ejecutando '{request.tool_name}.{op}' para request [{req_id[:8]}]")

        if op in ("get_network_interfaces", "get_interfaces", "list_interfaces"):
            inc_disc = bool(params.get("include_disconnected", False))
            inc_virt = bool(params.get("include_virtual", False))
            flt_name = str(params["interface_name_filter"]) if "interface_name_filter" in params and params["interface_name_filter"] is not None else None

            net_req = NetworkInterfaceRequest(
                include_disconnected=inc_disc,
                include_virtual=inc_virt,
                interface_name_filter=flt_name,
            )

            res_dict = self.network_service.get_network_interfaces(net_req, request_id=req_id).to_dict()
            msg = "Inspección de diagnóstico de adaptadores de red realizada exitosamente."

        elif op in ("get_active_connections", "active_connections", "list_connections"):
            prot = str(params["protocol"]) if "protocol" in params and params["protocol"] is not None else None
            st = str(params["state"]) if "state" in params and params["state"] is not None else None
            l_addr = str(params["local_address"]) if "local_address" in params and params["local_address"] is not None else None
            l_port = int(params["local_port"]) if "local_port" in params and params["local_port"] is not None else None
            r_addr = str(params["remote_address"]) if "remote_address" in params and params["remote_address"] is not None else None
            r_port = int(params["remote_port"]) if "remote_port" in params and params["remote_port"] is not None else None
            pid = int(params["process_id"]) if "process_id" in params and params["process_id"] is not None else None
            inc_proc = bool(params.get("include_process_info", True))
            max_res = int(params.get("max_results", 1000))

            conn_req = NetworkConnectionRequest(
                protocol=prot,
                state=st,
                local_address=l_addr,
                local_port=l_port,
                remote_address=r_addr,
                remote_port=r_port,
                process_id=pid,
                include_process_info=inc_proc,
                max_results=max_res,
            )

            res_dict = self.connection_service.get_active_connections(conn_req, request_id=req_id).to_dict()
            msg = "Inspección de diagnóstico de conexiones de red activas realizada exitosamente."

        elif op in ("get_listening_ports", "listening_ports", "list_ports"):
            prot = str(params["protocol"]) if "protocol" in params and params["protocol"] is not None else None
            l_addr = str(params["local_address"]) if "local_address" in params and params["local_address"] is not None else None
            l_port = int(params["local_port"]) if "local_port" in params and params["local_port"] is not None else None
            pid = int(params["process_id"]) if "process_id" in params and params["process_id"] is not None else None
            inc_proc = bool(params.get("include_process_info", True))
            max_res = int(params.get("max_results", 1000))

            conn_req = NetworkConnectionRequest(
                protocol=prot,
                local_address=l_addr,
                local_port=l_port,
                process_id=pid,
                include_process_info=inc_proc,
                max_results=max_res,
            )

            res_dict = self.connection_service.get_listening_ports(conn_req, request_id=req_id).to_dict()
            msg = "Inspección de diagnóstico de puertos en escucha realizada exitosamente."

        elif op in ("get_routing_table", "routing_table", "list_routes"):
            af = str(params["address_family"]) if "address_family" in params and params["address_family"] is not None else None
            dest = str(params["destination"]) if "destination" in params and params["destination"] is not None else None
            gw = str(params["gateway"]) if "gateway" in params and params["gateway"] is not None else None
            iface = str(params["interface"]) if "interface" in params and params["interface"] is not None else None
            met = int(params["metric"]) if "metric" in params and params["metric"] is not None else None
            prot = str(params["protocol"]) if "protocol" in params and params["protocol"] is not None else None
            max_res = int(params.get("max_results", 2048))

            route_req = RoutingTableRequest(
                address_family=af,
                destination=dest,
                gateway=gw,
                interface=iface,
                metric=met,
                protocol=prot,
                max_results=max_res,
            )

            res_dict = self.routing_service.get_routing_table(route_req, request_id=req_id).to_dict()
            msg = "Inspección de diagnóstico de la tabla de ruteo realizada exitosamente."

        elif op in ("get_dns_cache", "dns_cache", "list_dns_cache"):
            host = str(params["hostname"]) if "hostname" in params and params["hostname"] is not None else None
            rec_type = str(params["record_type"]) if "record_type" in params and params["record_type"] is not None else None
            af = str(params["address_family"]) if "address_family" in params and params["address_family"] is not None else None
            val = str(params["value"]) if "value" in params and params["value"] is not None else None
            max_res = int(params.get("max_results", 4096))

            dns_req = DNSCacheRequest(
                hostname=host,
                record_type=rec_type,
                address_family=af,
                value=val,
                max_results=max_res,
            )

            res_dict = self.dns_cache_service.get_dns_cache(dns_req, request_id=req_id).to_dict()
            msg = "Inspección de diagnóstico de la caché DNS realizada exitosamente."

        else:
            raise ValueError(f"Operación de red no soportada: '{op}'")

        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        return ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            request_id=req_id,
            tool_name=request.tool_name,
            operation=op,
            output=res_dict,
            message=msg,
            duration_ms=duration,
            timestamp=datetime.now(UTC),
        )
