"""Modelo fuertemente tipado e inmutable para solicitudes de ejecución (Subetapa 05.2).

Representa formalmente una solicitud de ejecución procesada internamente por el pipeline.
Garantiza que ningún parámetro de seguridad enviado por el cliente MCP sea aceptado como confiable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.types import JSONDict
from server.context import FORBIDDEN_CLIENT_OVERRIDE_KEYS, RequestContext, create_request_context


@dataclass(frozen=True)
class ExecutionRequest:
    """Modelo estructurado inmutable para representar una solicitud de ejecución."""

    tool_name: str
    operation: str
    context: RequestContext
    parameters: JSONDict = field(default_factory=dict)
    metadata: JSONDict = field(default_factory=dict)
    session_id: str = "default_session"
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: str = "PENDING"

    def __post_init__(self) -> None:
        if not self.request_id or not str(self.request_id).strip():
            object.__setattr__(self, "request_id", self.context.request_id)
        if not self.correlation_id or not str(self.correlation_id).strip():
            object.__setattr__(self, "correlation_id", self.context.correlation_id)
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", datetime.now(UTC))


def create_execution_request(
    tool_name: str,
    operation: str = "execute",
    parameters: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    context: RequestContext | None = None,
) -> ExecutionRequest:
    """Crea una ExecutionRequest sanitizada aislando entradas no confiables del cliente.

    DESICIÓN ARQUITECTÓNICA DE SEGURIDAD:
    Filtra cualquier parámetro recibido que pretenda suplantar decisiones o estados de seguridad
    (ej. decision='ALLOW', risk_level='SAFE', policy_source='ADMINISTRATOR').
    """
    raw_params = parameters or {}
    raw_meta = metadata or {}

    sanitized_params = {k: v for k, v in raw_params.items() if k.lower() not in FORBIDDEN_CLIENT_OVERRIDE_KEYS}
    sanitized_meta = {k: v for k, v in raw_meta.items() if k.lower() not in FORBIDDEN_CLIENT_OVERRIDE_KEYS}

    req_context = context or create_request_context(
        tool_name=tool_name,
        operation=operation,
        parameters=sanitized_params,
        metadata=sanitized_meta,
    )

    return ExecutionRequest(
        tool_name=tool_name,
        operation=operation,
        context=req_context,
        parameters=sanitized_params,
        metadata=sanitized_meta,
        session_id=req_context.session_id,
        correlation_id=req_context.correlation_id,
        request_id=req_context.request_id,
        timestamp=req_context.timestamp,
        status="PENDING",
    )
