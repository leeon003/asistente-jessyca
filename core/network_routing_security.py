"""Frontera de seguridad y validador de ruteo IP y caché DNS (NetworkRoutingSecurityManager - Subetapa 09.3).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Aplica el principio FAIL-SAFE DENY sobre las solicitudes y respuestas de diagnóstico de ruteo y caché DNS.
Validación de formato IP/CIDR, métricas, sanitización de hostnames (remoción de caracteres de control y null bytes).
"""

from __future__ import annotations

import ipaddress
import re

from config.settings import AppSettings
from core.exceptions import MCPError
from core.logger import get_logger
from core.network_routing_models import (
    DNSCacheEntry,
    DNSCacheRequest,
    DNSCacheResult,
    NetworkRoute,
    RoutingTableRequest,
    RoutingTableResult,
)

logger = get_logger("jessyca.core.network_routing_security")


class NetworkRoutingSecurityError(MCPError):
    """Error base de la frontera de seguridad de ruteo y caché DNS."""

    pass


class NetworkRoutingLimitExceededError(NetworkRoutingSecurityError):
    """Error emitido cuando una solicitud o resultado de ruteo/DNS excede los límites configurados."""

    pass


class NetworkRoutingSecurityManager:
    """Validador estricto de seguridad para la inspección de ruteo IP y caché DNS."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.max_routes: int = settings.NETWORK_MAX_ROUTES
        self.max_prefix_len: int = settings.NETWORK_MAX_ROUTE_PREFIX_LENGTH
        self.max_interface_len: int = settings.NETWORK_MAX_ROUTE_INTERFACE_LENGTH
        self.max_dns_entries: int = settings.NETWORK_MAX_DNS_CACHE_ENTRIES
        self.max_hostname_len: int = settings.NETWORK_MAX_DNS_HOSTNAME_LENGTH
        self.max_value_len: int = settings.NETWORK_MAX_DNS_VALUE_LENGTH

    def validate_routing_request(self, request: RoutingTableRequest) -> RoutingTableRequest:
        """Valida la solicitud de inspección de la tabla de ruteo. FAIL-SAFE DENY."""
        if request.address_family is not None:
            if not isinstance(request.address_family, str):
                raise NetworkRoutingSecurityError("El argumento 'address_family' debe ser una cadena.")
            af_upper = request.address_family.strip().upper()
            if af_upper not in ("IPV4", "IPV6", "ANY"):
                raise NetworkRoutingSecurityError(f"Familia de direcciones no soportada: '{request.address_family}'. Usar IPv4, IPv6 o ANY.")

        if request.metric is not None:
            if not isinstance(request.metric, int) or isinstance(request.metric, bool) or request.metric < 0:
                raise NetworkRoutingSecurityError(f"Métrica de ruteo inválida: {request.metric}")

        for addr_name, addr_val in [("destination", request.destination), ("gateway", request.gateway)]:
            if addr_val is not None:
                if not isinstance(addr_val, str):
                    raise NetworkRoutingSecurityError(f"La dirección '{addr_name}' debe ser una cadena.")
                try:
                    if "/" in addr_val:
                        ipaddress.ip_network(addr_val, strict=False)
                    else:
                        ipaddress.ip_address(addr_val)
                except ValueError as err:
                    raise NetworkRoutingSecurityError(f"Formato IP/CIDR inválido para '{addr_name}': '{addr_val}' ({err})") from err

        if not isinstance(request.max_results, int) or isinstance(request.max_results, bool) or request.max_results <= 0:
            raise NetworkRoutingSecurityError(f"El parámetro max_results debe ser un entero positivo: {request.max_results}")

        if request.max_results > self.max_routes:
            raise NetworkRoutingLimitExceededError(f"max_results excede el límite máximo de rutas ({request.max_results} > {self.max_routes}).")

        return request

    def validate_dns_cache_request(self, request: DNSCacheRequest) -> DNSCacheRequest:
        """Valida la solicitud de inspección de la caché DNS. FAIL-SAFE DENY."""
        if request.hostname is not None:
            if not isinstance(request.hostname, str):
                raise NetworkRoutingSecurityError("El argumento 'hostname' debe ser una cadena.")
            if len(request.hostname) > self.max_hostname_len:
                raise NetworkRoutingSecurityError(f"Longitud de hostname excede el máximo permitido ({len(request.hostname)} > {self.max_hostname_len}).")
            if "\x00" in request.hostname or re.search(r"[\x00-\x1f]", request.hostname):
                raise NetworkRoutingSecurityError("El hostname contiene caracteres de control o null bytes prohibidos.")

        if not isinstance(request.max_results, int) or isinstance(request.max_results, bool) or request.max_results <= 0:
            raise NetworkRoutingSecurityError(f"El parámetro max_results debe ser un entero positivo: {request.max_results}")

        if request.max_results > self.max_dns_entries:
            raise NetworkRoutingLimitExceededError(f"max_results excede el límite máximo de entradas DNS ({request.max_results} > {self.max_dns_entries}).")

        return request

    def sanitize_hostname(self, hostname: str | None) -> str | None:
        """Sanitiza nombres de host removiendo null bytes y caracteres de control no imprimibles."""
        if not hostname or not isinstance(hostname, str):
            return None
        clean = re.sub(r"[\x00-\x1f]", "", hostname).strip()
        if len(clean) > self.max_hostname_len:
            clean = clean[: self.max_hostname_len]
        return clean

    def sanitize_dns_value(self, value: str | None) -> str | None:
        """Sanitiza valores o direcciones de registros DNS."""
        if not value or not isinstance(value, str):
            return None
        clean = re.sub(r"[\x00-\x1f]", "", value).strip()
        if len(clean) > self.max_value_len:
            clean = clean[: self.max_value_len]
        return clean

    def validate_route(self, route: NetworkRoute) -> NetworkRoute:
        """Sanitiza y valida una ruta de red individual."""
        iface_clean = route.interface[: self.max_interface_len] if len(route.interface) > self.max_interface_len else route.interface
        return NetworkRoute(
            destination=route.destination,
            prefix_length=route.prefix_length,
            gateway=route.gateway,
            interface=iface_clean,
            metric=route.metric,
            protocol=route.protocol,
            address_family=route.address_family,
            route_type=route.route_type,
        )

    def validate_dns_entry(self, entry: DNSCacheEntry) -> DNSCacheEntry:
        """Sanitiza y valida una entrada de caché DNS individual."""
        host_clean = self.sanitize_hostname(entry.hostname) or "unknown.domain"
        val_clean = self.sanitize_dns_value(entry.value) or ""
        return DNSCacheEntry(
            hostname=host_clean,
            record_type=entry.record_type,
            value=val_clean,
            ttl=entry.ttl,
            address_family=entry.address_family,
            status=entry.status,
        )

    def validate_routing_result(self, result: RoutingTableResult) -> RoutingTableResult:
        """Valida y enforza límites globales sobre las rutas resultantes."""
        sanitized_routes = tuple(self.validate_route(r) for r in result.routes[: self.max_routes])
        return RoutingTableResult(
            success=result.success,
            routes=sanitized_routes,
            metadata=result.metadata,
            message=result.message,
        )

    def validate_dns_cache_result(self, result: DNSCacheResult) -> DNSCacheResult:
        """Valida y enforza límites globales sobre la caché DNS resultante."""
        sanitized_entries = tuple(self.validate_dns_entry(e) for e in result.entries[: self.max_dns_entries])
        return DNSCacheResult(
            success=result.success,
            entries=sanitized_entries,
            metadata=result.metadata,
            message=result.message,
        )
