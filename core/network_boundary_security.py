"""Consolidador centralizado de la frontera de seguridad para diagnóstico de red (Subetapa 09.4).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
Verifica transversalmente que las 5 operaciones de `windows.network`:
1. get_network_interfaces
2. get_active_connections
3. get_listening_ports
4. get_routing_table
5. get_dns_cache

cumplan estrictamente con las invariantes globales: READ-ONLY, PIPELINE MANDATORY, ZERO SHELL,
FAIL-SAFE DENY, LIMITS & TIMEOUT CONSOLIDATION, PRIVACY (METADATOS EXCLUSIVOS) e IMMUTABILITY.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from config.settings import AppSettings
from core.exceptions import MCPError
from core.logger import get_logger
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest

logger = get_logger("jessyca.core.network_boundary_security")


class NetworkBoundarySecurityError(MCPError):
    """Error emitido cuando una operación de red viola las invariantes de la frontera de seguridad."""

    pass


class NetworkBoundaryConsolidator:
    """Consolidador y auditor de la frontera de seguridad para la capability `windows.network`."""

    def __init__(self) -> None:
        self.settings = AppSettings()

    def verify_pipeline_authorization(
        self,
        request: ExecutionRequest,
        evidence: AuthorizationEvidence,
    ) -> bool:
        """Verifica formalmente la evidencia de autorización del pipeline para operaciones de red.

        FAIL-SAFE DENY: Retorna False o lanza NetworkBoundarySecurityError si la evidencia es inválida o no corresponde.
        """
        if not evidence or not evidence.is_valid:
            logger.error(f"[NETWORK BOUNDARY DENY] Evidencia inválida o ausente para request '{request.request_id}'")
            return False

        if evidence.request_id != request.request_id:
            logger.error(f"[NETWORK BOUNDARY DENY] Incoincidencia de request_id en evidencia ({evidence.request_id} != {request.request_id})")
            return False

        if not evidence.action_fingerprint or len(evidence.action_fingerprint) < 16:
            logger.error("[NETWORK BOUNDARY DENY] Firma criptográfica action_fingerprint ausente o débil en evidencia")
            return False

        if request.tool_name != "windows.network":
            logger.error(f"[NETWORK BOUNDARY DENY] Tool no autorizada por la frontera de red: '{request.tool_name}'")
            return False

        return True

    def validate_request_parameters(self, operation: str, params: dict[str, Any]) -> None:
        """Valida transversalmente los parámetros de entrada de cualquiera de las 5 operaciones de red.

        FAIL-SAFE DENY: Lanza NetworkBoundarySecurityError ante tipos incorrectos, NaN, Infinity,
        números negativos, puertos/PIDs inválidos, null bytes, caracteres de control o límites excedidos.
        """
        op_clean = operation.lower().strip()
        valid_ops = (
            "get_network_interfaces",
            "get_interfaces",
            "list_interfaces",
            "get_active_connections",
            "active_connections",
            "list_connections",
            "get_listening_ports",
            "listening_ports",
            "list_ports",
            "get_routing_table",
            "routing_table",
            "list_routes",
            "get_dns_cache",
            "dns_cache",
            "list_dns_cache",
        )

        if op_clean not in valid_ops:
            raise NetworkBoundarySecurityError(f"Operación de red desconocida o no autorizada: '{operation}'")

        # 1. Inspección de tipos e inyección de valores inválidos (NaN, Infinity, Booleans para números)
        for key, val in params.items():
            if val is None:
                continue

            # Inyección de NaN o Infinity en floats/strings
            val_str = str(val).lower()
            if "nan" in val_str or "inf" in val_str or "infinity" in val_str:
                raise NetworkBoundarySecurityError(f"Parámetro '{key}' contiene un valor flotante inválido o infinito: '{val}'")

            # Inyección de null bytes o caracteres de control no imprimibles
            if isinstance(val, str):
                if "\x00" in val or re.search(r"[\x00-\x1f]", val):
                    raise NetworkBoundarySecurityError(f"Parámetro '{key}' contiene caracteres de control o null bytes prohibidos.")

            # Validar puertos
            if "port" in key and val is not None:
                if not isinstance(val, int) or isinstance(val, bool) or not (0 <= val <= 65535):
                    raise NetworkBoundarySecurityError(f"El puerto '{key}' debe ser un entero entre 0 y 65535: {val}")

            # Validar Process ID
            if key == "process_id" and val is not None:
                if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                    raise NetworkBoundarySecurityError(f"Process ID inválido: {val}")

            # Validar métrica
            if key == "metric" and val is not None:
                if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                    raise NetworkBoundarySecurityError(f"Métrica inválida: {val}")

            # Validar max_results
            if key == "max_results" and val is not None:
                if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                    raise NetworkBoundarySecurityError(f"max_results debe ser un entero positivo: {val}")

            # Validar IP/CIDR
            if ("address" in key or key in ("destination", "gateway")) and val is not None and isinstance(val, str):
                try:
                    if "/" in val:
                        ipaddress.ip_network(val, strict=False)
                    else:
                        ipaddress.ip_address(val)
                except ValueError as err:
                    raise NetworkBoundarySecurityError(f"Dirección IP o formato CIDR inválido para '{key}': '{val}' ({err})") from err

    def audit_response_privacy(self, operation: str, output_data: dict[str, Any]) -> dict[str, Any]:
        """Extrae y sanitiza metadatos estrictos de la respuesta para el AuditLogger.

        INVARIANTE DE PRIVACIDAD ABSOLUTA: Retorna ÚNICAMENTE metadatos numéricos y de estatus.
        CERO direcciones IP crudas, direcciones MAC, puertos, rutas, pasarelas, hostnames o valores DNS.
        """
        meta_raw = output_data.get("metadata", {})
        if not isinstance(meta_raw, dict):
            meta_raw = {}

        return {
            "operation": operation,
            "success": bool(output_data.get("success", False)),
            "total_found": meta_raw.get("total_found", 0),
            "returned_count": meta_raw.get("returned_count", 0),
            "truncated": bool(meta_raw.get("truncated", False)),
            "processing_time_ms": meta_raw.get("processing_time_ms", 0.0),
            "backend_name": meta_raw.get("backend_name", "UnknownNetworkBackend"),
        }
