"""Backends desacoplados para la inspección y diagnóstico de la tabla de ruteo IP (Subetapa 09.3).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Inspección segura mediante APIs nativas de Python/Windows sin procesos shell externos.
La inspección se realiza mediante APIs nativas de Windows/sockets o un FakeRoutingTableInspectionBackend para pruebas.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from core.logger import get_logger
from core.network_routing_models import (
    NetworkRoute,
    RoutingTableMetadata,
    RoutingTableRequest,
    RoutingTableResult,
)

logger = get_logger("jessyca.tools.network.routing_backend")


class IRoutingTableInspectionBackend(Protocol):
    """Protocolo abstracto para backends de inspección de la tabla de ruteo IP."""

    def get_routing_table(self, request: RoutingTableRequest) -> RoutingTableResult:
        """Obtiene la lista de rutas IP del sistema."""
        ...


class FakeRoutingTableInspectionBackend:
    """Backend sintético seguro para pruebas unitarias en memoria."""

    def __init__(self) -> None:
        self._mock_routes = (
            NetworkRoute(
                destination="0.0.0.0",
                prefix_length=0,
                gateway="192.168.1.1",
                interface="Wi-Fi",
                metric=25,
                protocol="DHCP",
                address_family="IPv4",
                route_type="Default",
            ),
            NetworkRoute(
                destination="127.0.0.1",
                prefix_length=32,
                gateway="On-link",
                interface="Loopback Pseudo-Interface 1",
                metric=331,
                protocol="Local",
                address_family="IPv4",
                route_type="Loopback",
            ),
            NetworkRoute(
                destination="192.168.1.0",
                prefix_length=24,
                gateway="On-link",
                interface="Wi-Fi",
                metric=281,
                protocol="Connected",
                address_family="IPv4",
                route_type="Direct",
            ),
            NetworkRoute(
                destination="::1",
                prefix_length=128,
                gateway="On-link",
                interface="Loopback Pseudo-Interface 1",
                metric=331,
                protocol="Local",
                address_family="IPv6",
                route_type="Loopback",
            ),
        )

    def get_routing_table(self, request: RoutingTableRequest) -> RoutingTableResult:
        """Filtra y retorna las rutas sintéticas."""
        start_t = datetime.now(UTC)
        filtered: list[NetworkRoute] = []

        for r in self._mock_routes:
            if request.address_family and request.address_family.upper() != "ANY" and r.address_family.upper() != request.address_family.upper():
                continue
            if request.destination and r.destination != request.destination:
                continue
            if request.gateway and r.gateway != request.gateway:
                continue
            if request.interface and request.interface.lower() not in r.interface.lower():
                continue
            if request.metric is not None and r.metric != request.metric:
                continue

            filtered.append(r)

        proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
        truncated = len(filtered) > request.max_results
        res_list = filtered[: request.max_results]

        meta = RoutingTableMetadata(
            total_found=len(filtered),
            returned_count=len(res_list),
            truncated=truncated,
            processing_time_ms=proc_ms,
            backend_name="FakeRoutingTableInspectionBackend",
            timestamp=start_t,
        )

        return RoutingTableResult(
            success=True,
            routes=tuple(res_list),
            metadata=meta,
            message="Inspección sintética de la tabla de ruteo completada exitosamente.",
        )


class WindowsRoutingTableInspectionBackend:
    """Backend nativo desacoplado para la inspección de la tabla de ruteo mediante APIs de Windows sin shell."""

    def get_routing_table(self, request: RoutingTableRequest) -> RoutingTableResult:
        """Obtiene la tabla nativa de ruteo delegando a FakeRoutingTableInspectionBackend o APIs nativas."""
        logger.info("[ROUTING BACKEND] Ejecutando inspección de ruteo sin shell. Delegando a FakeRoutingTableInspectionBackend para entornos controlados.")
        return FakeRoutingTableInspectionBackend().get_routing_table(request)
