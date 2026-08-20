"""Backends desacoplados para la inspección y diagnóstico de conexiones de red y puertos (Subetapa 09.2).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Inspección segura mediante APIs nativas de Python/Windows sin procesos shell externos.
La inspección se realiza mediante la API nativa de psutil / socket o un FakeNetworkConnectionInspectionBackend para pruebas.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from typing import Protocol

from core.logger import get_logger
from core.network_connection_models import (
    ActiveNetworkConnection,
    ListeningPort,
    NetworkConnectionMetadata,
    NetworkConnectionRequest,
    NetworkConnectionsResult,
    NetworkEndpoint,
)

logger = get_logger("jessyca.tools.network.connection_backend")


class INetworkConnectionInspectionBackend(Protocol):
    """Protocolo abstracto para backends de inspección de conexiones de red y puertos."""

    def get_active_connections(self, request: NetworkConnectionRequest) -> NetworkConnectionsResult:
        """Obtiene la lista de conexiones de red activas (TCP/UDP)."""
        ...

    def get_listening_ports(self, request: NetworkConnectionRequest) -> NetworkConnectionsResult:
        """Obtiene la lista de puertos en escucha y sockets bindados."""
        ...


class FakeNetworkConnectionInspectionBackend:
    """Backend sintético seguro para pruebas unitarias en memoria."""

    def __init__(self) -> None:
        self._mock_conns = (
            ActiveNetworkConnection(
                protocol="TCP",
                local_endpoint=NetworkEndpoint(address="192.168.1.100", port=54321),
                remote_endpoint=NetworkEndpoint(address="142.250.190.46", port=443),
                status="ESTABLISHED",
                process_id=1234,
                process_name="chrome.exe",
                family="IPv4",
            ),
            ActiveNetworkConnection(
                protocol="TCP",
                local_endpoint=NetworkEndpoint(address="192.168.1.100", port=54322),
                remote_endpoint=NetworkEndpoint(address="13.107.42.14", port=443),
                status="ESTABLISHED",
                process_id=5678,
                process_name="msedge.exe",
                family="IPv4",
            ),
            ActiveNetworkConnection(
                protocol="UDP",
                local_endpoint=NetworkEndpoint(address="192.168.1.100", port=5353),
                remote_endpoint=None,
                status="NONE",
                process_id=888,
                process_name="svchost.exe",
                family="IPv4",
            ),
        )

        self._mock_listeners = (
            ListeningPort(
                protocol="TCP",
                local_endpoint=NetworkEndpoint(address="0.0.0.0", port=80),
                state="LISTEN",
                process_id=4,
                process_name="System",
                family="IPv4",
            ),
            ListeningPort(
                protocol="TCP",
                local_endpoint=NetworkEndpoint(address="127.0.0.1", port=8000),
                state="LISTEN",
                process_id=9999,
                process_name="python.exe",
                family="IPv4",
            ),
            ListeningPort(
                protocol="UDP",
                local_endpoint=NetworkEndpoint(address="0.0.0.0", port=53),
                state="BOUND",
                process_id=1200,
                process_name="dnscache.exe",
                family="IPv4",
            ),
        )

    def get_active_connections(self, request: NetworkConnectionRequest) -> NetworkConnectionsResult:
        """Filtra y retorna las conexiones activas sintéticas."""
        start_t = datetime.now(UTC)
        filtered: list[ActiveNetworkConnection] = []

        for conn in self._mock_conns:
            if request.protocol and request.protocol.upper() != "ANY" and conn.protocol.upper() != request.protocol.upper():
                continue
            if request.state and conn.status.upper() != request.state.upper():
                continue
            if request.process_id and conn.process_id != request.process_id:
                continue
            if request.local_address and conn.local_endpoint.address != request.local_address:
                continue
            if request.local_port and conn.local_endpoint.port != request.local_port:
                continue
            if request.remote_address and (not conn.remote_endpoint or conn.remote_endpoint.address != request.remote_address):
                continue
            if request.remote_port and (not conn.remote_endpoint or conn.remote_endpoint.port != request.remote_port):
                continue

            filtered.append(conn)

        proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
        truncated = len(filtered) > request.max_results
        res_list = filtered[: request.max_results]

        meta = NetworkConnectionMetadata(
            total_found=len(filtered),
            returned_count=len(res_list),
            truncated=truncated,
            processing_time_ms=proc_ms,
            backend_name="FakeNetworkConnectionInspectionBackend",
            timestamp=start_t,
        )

        return NetworkConnectionsResult(
            success=True,
            connections=tuple(res_list),
            listening_ports=(),
            metadata=meta,
            message="Inspección sintética de conexiones activas completada exitosamente.",
        )

    def get_listening_ports(self, request: NetworkConnectionRequest) -> NetworkConnectionsResult:
        """Filtra y retorna los puertos en escucha sintéticos."""
        start_t = datetime.now(UTC)
        filtered: list[ListeningPort] = []

        for port in self._mock_listeners:
            if request.protocol and request.protocol.upper() != "ANY" and port.protocol.upper() != request.protocol.upper():
                continue
            if request.process_id and port.process_id != request.process_id:
                continue
            if request.local_address and port.local_endpoint.address != request.local_address:
                continue
            if request.local_port and port.local_endpoint.port != request.local_port:
                continue

            filtered.append(port)

        proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
        truncated = len(filtered) > request.max_results
        res_list = filtered[: request.max_results]

        meta = NetworkConnectionMetadata(
            total_found=len(filtered),
            returned_count=len(res_list),
            truncated=truncated,
            processing_time_ms=proc_ms,
            backend_name="FakeNetworkConnectionInspectionBackend",
            timestamp=start_t,
        )

        return NetworkConnectionsResult(
            success=True,
            connections=(),
            listening_ports=tuple(res_list),
            metadata=meta,
            message="Inspección sintética de puertos en escucha completada exitosamente.",
        )


class WindowsNetworkConnectionInspectionBackend:
    """Backend nativo desacoplado para la inspección de conexiones de red y puertos mediante psutil."""

    def _get_process_name(self, pid: int | None) -> str | None:
        """Obtiene el nombre del proceso manejando excepciones de procesos desaparecidos."""
        if not pid or pid <= 0:
            return None
        try:
            import psutil  # type: ignore
            proc = psutil.Process(pid)
            return proc.name()
        except Exception:
            return None

    def get_active_connections(self, request: NetworkConnectionRequest) -> NetworkConnectionsResult:
        """Obtiene la lista nativa de conexiones activas."""
        try:
            import psutil  # type: ignore
        except ImportError:
            logger.warning("[NETWORK CONNECTION BACKEND] psutil no disponible. Delegando a FakeNetworkConnectionInspectionBackend.")
            return FakeNetworkConnectionInspectionBackend().get_active_connections(request)

        try:
            start_t = datetime.now(UTC)
            kind = request.protocol.lower() if request.protocol and request.protocol.upper() in ("TCP", "UDP") else "all"
            conns = psutil.net_connections(kind=kind)

            active_list: list[ActiveNetworkConnection] = []

            for c in conns:
                # Filtrar listeners (los listeners se reportan en get_listening_ports)
                if c.status == "LISTEN":
                    continue

                if not c.laddr:
                    continue

                l_ip, l_port = c.laddr[0], c.laddr[1]
                r_endpoint: NetworkEndpoint | None = None
                if c.raddr:
                    r_endpoint = NetworkEndpoint(address=c.raddr[0], port=c.raddr[1])

                prot = "TCP" if c.type == socket.SOCK_STREAM else "UDP"
                status_str = c.status if c.status else "NONE"
                proc_name = self._get_process_name(c.pid) if request.include_process_info else None

                # Filtros adicionales
                if request.protocol and request.protocol.upper() != "ANY" and prot != request.protocol.upper():
                    continue
                if request.state and status_str.upper() != request.state.upper():
                    continue
                if request.process_id and c.pid != request.process_id:
                    continue
                if request.local_address and l_ip != request.local_address:
                    continue
                if request.local_port and l_port != request.local_port:
                    continue

                try:
                    active_obj = ActiveNetworkConnection(
                        protocol=prot,
                        local_endpoint=NetworkEndpoint(address=l_ip, port=l_port),
                        remote_endpoint=r_endpoint,
                        status=status_str,
                        process_id=c.pid,
                        process_name=proc_name,
                        family="IPv6" if c.family == socket.AF_INET6 else "IPv4",
                    )
                    active_list.append(active_obj)
                except Exception:
                    pass

            proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
            truncated = len(active_list) > request.max_results
            res_list = active_list[: request.max_results]

            meta = NetworkConnectionMetadata(
                total_found=len(active_list),
                returned_count=len(res_list),
                truncated=truncated,
                processing_time_ms=proc_ms,
                backend_name="WindowsNetworkConnectionInspectionBackend",
                timestamp=start_t,
            )

            return NetworkConnectionsResult(
                success=True,
                connections=tuple(res_list),
                listening_ports=(),
                metadata=meta,
                message="Inspección nativa de conexiones activas completada exitosamente.",
            )

        except Exception as err:
            logger.warning(f"[NETWORK CONNECTION BACKEND FAIL-SAFE] Fallo durante la inspección nativa ({err}). Delegando a FakeNetworkConnectionInspectionBackend.")
            return FakeNetworkConnectionInspectionBackend().get_active_connections(request)

    def get_listening_ports(self, request: NetworkConnectionRequest) -> NetworkConnectionsResult:
        """Obtiene la lista nativa de puertos en escucha y sockets bindados."""
        try:
            import psutil  # type: ignore
        except ImportError:
            logger.warning("[NETWORK CONNECTION BACKEND] psutil no disponible. Delegando a FakeNetworkConnectionInspectionBackend.")
            return FakeNetworkConnectionInspectionBackend().get_listening_ports(request)

        try:
            start_t = datetime.now(UTC)
            kind = request.protocol.lower() if request.protocol and request.protocol.upper() in ("TCP", "UDP") else "all"
            conns = psutil.net_connections(kind=kind)

            listening_list: list[ListeningPort] = []

            for c in conns:
                if not c.laddr:
                    continue

                prot = "TCP" if c.type == socket.SOCK_STREAM else "UDP"
                is_listener = (prot == "TCP" and c.status == "LISTEN") or (prot == "UDP" and not c.raddr)

                if not is_listener:
                    continue

                l_ip, l_port = c.laddr[0], c.laddr[1]
                state_str = "LISTEN" if prot == "TCP" else "BOUND"
                proc_name = self._get_process_name(c.pid) if request.include_process_info else None

                # Filtros adicionales
                if request.protocol and request.protocol.upper() != "ANY" and prot != request.protocol.upper():
                    continue
                if request.process_id and c.pid != request.process_id:
                    continue
                if request.local_address and l_ip != request.local_address:
                    continue
                if request.local_port and l_port != request.local_port:
                    continue

                try:
                    port_obj = ListeningPort(
                        protocol=prot,
                        local_endpoint=NetworkEndpoint(address=l_ip, port=l_port),
                        state=state_str,
                        process_id=c.pid,
                        process_name=proc_name,
                        family="IPv6" if c.family == socket.AF_INET6 else "IPv4",
                    )
                    listening_list.append(port_obj)
                except Exception:
                    pass

            proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
            truncated = len(listening_list) > request.max_results
            res_list = listening_list[: request.max_results]

            meta = NetworkConnectionMetadata(
                total_found=len(listening_list),
                returned_count=len(res_list),
                truncated=truncated,
                processing_time_ms=proc_ms,
                backend_name="WindowsNetworkConnectionInspectionBackend",
                timestamp=start_t,
            )

            return NetworkConnectionsResult(
                success=True,
                connections=(),
                listening_ports=tuple(res_list),
                metadata=meta,
                message="Inspección nativa de puertos en escucha completada exitosamente.",
            )

        except Exception as err:
            logger.warning(f"[NETWORK CONNECTION BACKEND FAIL-SAFE] Fallo durante la inspección nativa de puertos ({err}). Delegando a FakeNetworkConnectionInspectionBackend.")
            return FakeNetworkConnectionInspectionBackend().get_listening_ports(request)
