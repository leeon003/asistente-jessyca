"""Contexto de solicitud para el servidor MCP (Subetapa 05.1).

Proporciona trazabilidad mediante request_id, correlation_id, session_id y timestamp.
Garantiza el aislamiento entre entradas no confiables del cliente MCP y los parámetros
internos de seguridad (Aislamiento de Entradas No Confiables).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.types import JSONDict

# Claves de seguridad protegidas que NUNCA se aceptan desde la carga útil no confiable del cliente
FORBIDDEN_CLIENT_OVERRIDE_KEYS: set[str] = {
    "decision",
    "security_decision",
    "risk",
    "risk_level",
    "security_level",
    "risk_factors",
    "permission",
    "permission_decision",
    "requires_confirmation",
    "confirmation_status",
    "confirmation",
    "policy_source",
    "policy_decision",
    "is_allowed",
    "requires_elevation",
}


@dataclass(frozen=True)
class RequestContext:
    """Contexto estructurado inmutable para solicitudes MCP."""

    tool_name: str
    operation: str = "execute"
    user: str = "mcp_client"
    parameters: JSONDict = field(default_factory=dict)
    metadata: JSONDict = field(default_factory=dict)
    session_id: str = "default_session"
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.request_id or not str(self.request_id).strip():
            object.__setattr__(self, "request_id", str(uuid.uuid4()))
        if not self.correlation_id or not str(self.correlation_id).strip():
            object.__setattr__(self, "correlation_id", self.request_id)
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", datetime.now(UTC))


def create_request_context(
    tool_name: str,
    operation: str = "execute",
    user: str = "mcp_client",
    parameters: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str = "default_session",
    correlation_id: str | None = None,
    request_id: str | None = None,
) -> RequestContext:
    """Crea un RequestContext sanitizado aislando entradas no confiables del cliente.

    DESICIÓN ARQUITECTÓNICA DE SEGURIDAD:
    Esta función filtra cualquier clave que intente suplantar o forzar decisiones de seguridad
    (ej. decision='ALLOW', risk_level='SAFE', policy_source='ADMINISTRATOR') enviadas por el cliente MCP.
    Dichas evaluaciones sólo pueden realizarse en las capas internas del sistema de seguridad.
    """
    raw_params = parameters or {}
    raw_meta = metadata or {}

    # Filtrar parámetros y metadatos no confiables que intenten inyectar estados de seguridad
    sanitized_params = {k: v for k, v in raw_params.items() if k.lower() not in FORBIDDEN_CLIENT_OVERRIDE_KEYS}
    sanitized_meta = {k: v for k, v in raw_meta.items() if k.lower() not in FORBIDDEN_CLIENT_OVERRIDE_KEYS}

    req_id = request_id or str(uuid.uuid4())
    corr_id = correlation_id or req_id

    return RequestContext(
        tool_name=tool_name,
        operation=operation,
        user=user,
        parameters=sanitized_params,
        metadata=sanitized_meta,
        session_id=session_id,
        correlation_id=corr_id,
        request_id=req_id,
        timestamp=datetime.now(UTC),
    )
