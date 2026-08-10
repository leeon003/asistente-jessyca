"""Herramienta MCP de inspección de adaptadores de red (Subetapa 09.1).

Implementa WindowsGetNetworkInterfacesTool integrada con BaseMCPTool y ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from core.network_connection_models import NetworkConnectionRequest
from core.network_models import NetworkInterfaceRequest
from core.network_routing_models import DNSCacheRequest, RoutingTableRequest
from core.security_architecture import SecurityLevel
from tools.base import BaseMCPTool, ToolMetadata
from tools.network.connection_service import NetworkConnectionInspectionService
from tools.network.dns_cache_service import DNSCacheInspectionService
from tools.network.network_service import NetworkInspectionService
from tools.network.routing_service import RoutingTableInspectionService


class WindowsGetNetworkInterfacesTool(BaseMCPTool):
    """Herramienta MCP para realizar inspección de diagnóstico de adaptadores de red (`windows.network`)."""

    def __init__(self, service: NetworkInspectionService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.network",
                description="Inspección de diagnóstico de adaptadores, IPs, pasarelas y DNS de red en Windows.",
                category="system",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.network_service = service or NetworkInspectionService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        # Las herramientas MCP de red ejecutan a través de WindowsNetworkToolExecutor dentro del pipeline
        inc_disc = bool(parameters.get("include_disconnected", False))
        inc_virt = bool(parameters.get("include_virtual", False))
        flt_name = str(parameters["interface_name_filter"]) if "interface_name_filter" in parameters and parameters["interface_name_filter"] is not None else None

        req = NetworkInterfaceRequest(
            include_disconnected=inc_disc,
            include_virtual=inc_virt,
            interface_name_filter=flt_name,
        )
        return self.network_service.get_network_interfaces(req).to_dict()


class WindowsGetActiveConnectionsTool(BaseMCPTool):
    """Herramienta MCP para realizar inspección de diagnóstico de conexiones de red activas (`windows.network`)."""

    def __init__(self, service: NetworkConnectionInspectionService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.network",
                description="Inspección de diagnóstico de conexiones de red activas (TCP/UDP) en Windows.",
                category="system",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.connection_service = service or NetworkConnectionInspectionService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        prot = str(parameters["protocol"]) if "protocol" in parameters and parameters["protocol"] is not None else None
        st = str(parameters["state"]) if "state" in parameters and parameters["state"] is not None else None
        l_addr = str(parameters["local_address"]) if "local_address" in parameters and parameters["local_address"] is not None else None
        l_port = int(parameters["local_port"]) if "local_port" in parameters and parameters["local_port"] is not None else None
        r_addr = str(parameters["remote_address"]) if "remote_address" in parameters and parameters["remote_address"] is not None else None
        r_port = int(parameters["remote_port"]) if "remote_port" in parameters and parameters["remote_port"] is not None else None
        pid = int(parameters["process_id"]) if "process_id" in parameters and parameters["process_id"] is not None else None
        inc_proc = bool(parameters.get("include_process_info", True))
        max_res = int(parameters.get("max_results", 1000))

        req = NetworkConnectionRequest(
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
        return self.connection_service.get_active_connections(req).to_dict()


class WindowsGetListeningPortsTool(BaseMCPTool):
    """Herramienta MCP para realizar inspección de diagnóstico de puertos en escucha (`windows.network`)."""

    def __init__(self, service: NetworkConnectionInspectionService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.network",
                description="Inspección de diagnóstico de puertos en escucha y sockets bindados en Windows.",
                category="system",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.connection_service = service or NetworkConnectionInspectionService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        prot = str(parameters["protocol"]) if "protocol" in parameters and parameters["protocol"] is not None else None
        l_addr = str(parameters["local_address"]) if "local_address" in parameters and parameters["local_address"] is not None else None
        l_port = int(parameters["local_port"]) if "local_port" in parameters and parameters["local_port"] is not None else None
        pid = int(parameters["process_id"]) if "process_id" in parameters and parameters["process_id"] is not None else None
        inc_proc = bool(parameters.get("include_process_info", True))
        max_res = int(parameters.get("max_results", 1000))

        req = NetworkConnectionRequest(
            protocol=prot,
            local_address=l_addr,
            local_port=l_port,
            process_id=pid,
            include_process_info=inc_proc,
            max_results=max_res,
        )
        return self.connection_service.get_listening_ports(req).to_dict()


class WindowsGetRoutingTableTool(BaseMCPTool):
    """Herramienta MCP para realizar inspección de diagnóstico de la tabla de ruteo IP (`windows.network`)."""

    def __init__(self, service: RoutingTableInspectionService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.network",
                description="Inspección de diagnóstico de la tabla de ruteo IP en Windows.",
                category="system",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.routing_service = service or RoutingTableInspectionService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        af = str(parameters["address_family"]) if "address_family" in parameters and parameters["address_family"] is not None else None
        dest = str(parameters["destination"]) if "destination" in parameters and parameters["destination"] is not None else None
        gw = str(parameters["gateway"]) if "gateway" in parameters and parameters["gateway"] is not None else None
        iface = str(parameters["interface"]) if "interface" in parameters and parameters["interface"] is not None else None
        met = int(parameters["metric"]) if "metric" in parameters and parameters["metric"] is not None else None
        prot = str(parameters["protocol"]) if "protocol" in parameters and parameters["protocol"] is not None else None
        max_res = int(parameters.get("max_results", 2048))

        req = RoutingTableRequest(
            address_family=af,
            destination=dest,
            gateway=gw,
            interface=iface,
            metric=met,
            protocol=prot,
            max_results=max_res,
        )
        return self.routing_service.get_routing_table(req).to_dict()


class WindowsGetDNSCacheTool(BaseMCPTool):
    """Herramienta MCP para realizar inspección de diagnóstico de la caché DNS local (`windows.network`)."""

    def __init__(self, service: DNSCacheInspectionService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.network",
                description="Inspección de diagnóstico de la caché DNS local en Windows.",
                category="system",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.dns_cache_service = service or DNSCacheInspectionService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        host = str(parameters["hostname"]) if "hostname" in parameters and parameters["hostname"] is not None else None
        rec_type = str(parameters["record_type"]) if "record_type" in parameters and parameters["record_type"] is not None else None
        af = str(parameters["address_family"]) if "address_family" in parameters and parameters["address_family"] is not None else None
        val = str(parameters["value"]) if "value" in parameters and parameters["value"] is not None else None
        max_res = int(parameters.get("max_results", 4096))

        req = DNSCacheRequest(
            hostname=host,
            record_type=rec_type,
            address_family=af,
            value=val,
            max_results=max_res,
        )
        return self.dns_cache_service.get_dns_cache(req).to_dict()
