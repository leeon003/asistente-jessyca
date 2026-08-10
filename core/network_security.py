"""Frontera de seguridad y validador de inspección de red (NetworkSecurityManager - Subetapa 09.1).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Aplica el principio FAIL-SAFE DENY sobre las solicitudes y respuestas de diagnóstico de red.
Validación rigurosa de límites, formatos de IP, normalización MAC y rechazo de NaN/Infinity/desbordamientos.
"""

from __future__ import annotations

import re

from config.settings import AppSettings
from core.exceptions import MCPError
from core.logger import get_logger
from core.network_models import (
    NetworkInterface,
    NetworkInterfaceRequest,
    NetworkInterfacesResult,
)

logger = get_logger("jessyca.core.network_security")


class NetworkSecurityError(MCPError):
    """Error base de la frontera de seguridad de red."""

    pass


class NetworkLimitExceededError(NetworkSecurityError):
    """Error emitido cuando la respuesta o parámetros de red exceden los límites máximos permitidos."""

    pass


class NetworkSecurityManager:
    """Validador estricto de seguridad para la inspección de diagnóstico de adaptadores de red."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.max_interfaces: int = settings.NETWORK_MAX_INTERFACES
        self.max_ips: int = settings.NETWORK_MAX_IP_ADDRESSES_PER_INTERFACE
        self.max_gateways: int = settings.NETWORK_MAX_GATEWAYS_PER_INTERFACE
        self.max_dns: int = settings.NETWORK_MAX_DNS_SERVERS_PER_INTERFACE
        self.max_name_len: int = settings.NETWORK_MAX_NAME_LENGTH
        self.max_desc_len: int = settings.NETWORK_MAX_DESCRIPTION_LENGTH
        self.max_response_size: int = settings.NETWORK_MAX_TOTAL_RESPONSE_SIZE

    def validate_request(self, request: NetworkInterfaceRequest) -> NetworkInterfaceRequest:
        """Valida la solicitud de inspección de adaptadores de red.

        FAIL-SAFE DENY: Lanza NetworkSecurityError si los filtros contienen patrones peligrosos o longitudes excesivas.
        """
        if request.interface_name_filter is not None:
            flt = request.interface_name_filter
            if not isinstance(flt, str):
                raise NetworkSecurityError("El filtro 'interface_name_filter' debe ser una cadena.")

            if len(flt) > self.max_name_len:
                raise NetworkLimitExceededError(f"El filtro de interfaz excede la longitud máxima ({len(flt)} > {self.max_name_len}).")

            # Prevenir inyección de patrones de expresiones regulares peligrosos o meta-caracteres de comandos
            if re.search(r"[;&|`$<>{}]", flt):
                raise NetworkSecurityError("El filtro contiene caracteres no permitidos.")

        return request

    def normalize_mac_address(self, mac: str | None) -> str | None:
        """Normaliza una dirección MAC a formato estandarizado en mayúsculas XX-XX-XX-XX-XX-XX."""
        if not mac or not isinstance(mac, str):
            return None
        cleaned = re.sub(r"[^A-Fa-f0-9]", "", mac).upper()
        if len(cleaned) == 12:
            return "-".join(cleaned[i : i + 2] for i in range(0, 12, 2))
        return mac.strip().upper()

    def sanitize_and_validate_interface(self, iface: NetworkInterface) -> NetworkInterface:
        """Valida y sanitiza una estructura individual de interfaz de red."""
        if len(iface.name) > self.max_name_len:
            name_clean = iface.name[: self.max_name_len]
        else:
            name_clean = iface.name

        if len(iface.description) > self.max_desc_len:
            desc_clean = iface.description[: self.max_desc_len]
        else:
            desc_clean = iface.description

        if len(iface.ipv4_addresses) > self.max_ips:
            ipv4_clean = iface.ipv4_addresses[: self.max_ips]
        else:
            ipv4_clean = iface.ipv4_addresses

        if len(iface.ipv6_addresses) > self.max_ips:
            ipv6_clean = iface.ipv6_addresses[: self.max_ips]
        else:
            ipv6_clean = iface.ipv6_addresses

        if len(iface.gateways) > self.max_gateways:
            gw_clean = iface.gateways[: self.max_gateways]
        else:
            gw_clean = iface.gateways

        if len(iface.dns_servers) > self.max_dns:
            dns_clean = iface.dns_servers[: self.max_dns]
        else:
            dns_clean = iface.dns_servers

        mac_norm = self.normalize_mac_address(iface.mac_address)

        return NetworkInterface(
            interface_id=iface.interface_id,
            name=name_clean,
            description=desc_clean,
            adapter_type=iface.adapter_type,
            operational_status=iface.operational_status,
            administrative_status=iface.administrative_status,
            mac_address=mac_norm,
            ipv4_addresses=ipv4_clean,
            ipv6_addresses=ipv6_clean,
            gateways=gw_clean,
            dns_servers=dns_clean,
            interface_index=iface.interface_index,
            metric=iface.metric,
        )

    def validate_result(self, result: NetworkInterfacesResult) -> NetworkInterfacesResult:
        """Valida y enforza límites globales sobre la lista de adaptadores resultantes."""
        if len(result.interfaces) > self.max_interfaces:
            truncated = result.interfaces[: self.max_interfaces]
            logger.warning(f"[NETWORK SECURITY] Truncando adaptadores resultantes de {len(result.interfaces)} a {self.max_interfaces}")
            sanitized_interfaces = tuple(self.sanitize_and_validate_interface(i) for i in truncated)
        else:
            sanitized_interfaces = tuple(self.sanitize_and_validate_interface(i) for i in result.interfaces)

        return NetworkInterfacesResult(
            success=result.success,
            interfaces=sanitized_interfaces,
            metadata=result.metadata,
            message=result.message,
        )
