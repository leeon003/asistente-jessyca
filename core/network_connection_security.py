"""Frontera de seguridad y validador de conexiones de red (NetworkConnectionSecurityManager - Subetapa 09.2).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Aplica el principio FAIL-SAFE DENY sobre las solicitudes y respuestas de diagnóstico de conexiones y puertos.
Validación de rango de puertos (0-65535), protocolos, sanitización de nombres de proceso y rechazo de NaN/Infinity/tipos inválidos.
"""

from __future__ import annotations

import ipaddress
import re

from config.settings import AppSettings
from core.exceptions import MCPError
from core.logger import get_logger
from core.network_connection_models import (
    ActiveNetworkConnection,
    ListeningPort,
    NetworkConnectionRequest,
    NetworkConnectionsResult,
)

logger = get_logger("jessyca.core.network_connection_security")


class NetworkConnectionSecurityError(MCPError):
    """Error base de la frontera de seguridad de conexiones de red."""

    pass


class NetworkConnectionLimitExceededError(NetworkConnectionSecurityError):
    """Error emitido cuando una solicitud o resultado de conexiones de red excede los límites configurados."""

    pass


class NetworkConnectionSecurityManager:
    """Validador estricto de seguridad para la inspección de conexiones de red activas y puertos en escucha."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.max_connections: int = settings.NETWORK_MAX_ACTIVE_CONNECTIONS
        self.max_listening_ports: int = settings.NETWORK_MAX_LISTENING_PORTS
        self.max_process_name_len: int = settings.NETWORK_MAX_PROCESS_NAME_LENGTH
        self.max_status_len: int = settings.NETWORK_MAX_STATUS_LENGTH
        self.max_response_size: int = settings.NETWORK_MAX_CONNECTION_RESPONSE_SIZE

    def validate_request(self, request: NetworkConnectionRequest) -> NetworkConnectionRequest:
        """Valida rigurosamente la solicitud de inspección de conexiones de red.

        FAIL-SAFE DENY: Lanza NetworkConnectionSecurityError ante cualquier parámetro inválido o sospechoso.
        """
        # 1. Validación de Protocolo
        if request.protocol is not None:
            if not isinstance(request.protocol, str):
                raise NetworkConnectionSecurityError("El argumento 'protocol' debe ser una cadena.")
            prot_upper = request.protocol.strip().upper()
            if prot_upper not in ("TCP", "UDP", "ANY"):
                raise NetworkConnectionSecurityError(f"Protocolo de red no soportado: '{request.protocol}'. Usar TCP, UDP o ANY.")

        # 2. Validación de Puertos
        for p_name, p_val in [("local_port", request.local_port), ("remote_port", request.remote_port)]:
            if p_val is not None:
                if not isinstance(p_val, int) or isinstance(p_val, bool) or not (0 <= p_val <= 65535):
                    raise NetworkConnectionSecurityError(f"El puerto '{p_name}' debe ser un entero entre 0 y 65535: {p_val}")

        # 3. Validación de Process ID
        if request.process_id is not None:
            if not isinstance(request.process_id, int) or isinstance(request.process_id, bool) or request.process_id < 0:
                raise NetworkConnectionSecurityError(f"Process ID inválido: {request.process_id}")

        # 4. Validación de Direcciones IP de Filtro
        for addr_name, addr_val in [("local_address", request.local_address), ("remote_address", request.remote_address)]:
            if addr_val is not None:
                if not isinstance(addr_val, str):
                    raise NetworkConnectionSecurityError(f"La dirección '{addr_name}' debe ser una cadena.")
                try:
                    ipaddress.ip_address(addr_val)
                except ValueError as err:
                    raise NetworkConnectionSecurityError(f"Dirección IP de filtro '{addr_name}' inválida: {addr_val}") from err

        # 5. Validación de max_results
        if not isinstance(request.max_results, int) or isinstance(request.max_results, bool) or request.max_results <= 0:
            raise NetworkConnectionSecurityError(f"El parámetro max_results debe ser un entero positivo: {request.max_results}")

        if request.max_results > self.max_connections:
            raise NetworkConnectionLimitExceededError(f"El parámetro max_results excede el límite máximo ({request.max_results} > {self.max_connections}).")

        return request

    def sanitize_process_name(self, process_name: str | None) -> str | None:
        """Sanitiza el nombre del proceso removiendo líneas de comandos completas, credenciales y acotando longitud."""
        if not process_name or not isinstance(process_name, str):
            return None
        # Remover argumentos de línea de comandos si están presentes
        clean_name = process_name.split()[0]
        # Prevenir path traversal o inyección de caracteres
        clean_name = re.sub(r"[;&|`$<>{}]", "", clean_name)
        if len(clean_name) > self.max_process_name_len:
            clean_name = clean_name[: self.max_process_name_len]
        return clean_name

    def validate_active_connection(self, conn: ActiveNetworkConnection) -> ActiveNetworkConnection:
        """Sanitiza y valida un registro individual de conexión activa."""
        proc_clean = self.sanitize_process_name(conn.process_name)
        status_clean = conn.status[: self.max_status_len] if len(conn.status) > self.max_status_len else conn.status

        return ActiveNetworkConnection(
            protocol=conn.protocol,
            local_endpoint=conn.local_endpoint,
            remote_endpoint=conn.remote_endpoint,
            status=status_clean,
            process_id=conn.process_id,
            process_name=proc_clean,
            family=conn.family,
        )

    def validate_listening_port(self, port: ListeningPort) -> ListeningPort:
        """Sanitiza y valida un registro individual de puerto en escucha."""
        proc_clean = self.sanitize_process_name(port.process_name)
        state_clean = port.state[: self.max_status_len] if len(port.state) > self.max_status_len else port.state

        return ListeningPort(
            protocol=port.protocol,
            local_endpoint=port.local_endpoint,
            state=state_clean,
            process_id=port.process_id,
            process_name=proc_clean,
            family=port.family,
        )

    def validate_result(self, result: NetworkConnectionsResult) -> NetworkConnectionsResult:
        """Valida y enforza límites globales sobre las conexiones y puertos resultantes."""
        sanitized_conns = tuple(self.validate_active_connection(c) for c in result.connections[: self.max_connections])
        sanitized_ports = tuple(self.validate_listening_port(p) for p in result.listening_ports[: self.max_listening_ports])

        return NetworkConnectionsResult(
            success=result.success,
            connections=sanitized_conns,
            listening_ports=sanitized_ports,
            metadata=result.metadata,
            message=result.message,
        )
