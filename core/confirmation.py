"""Mecanismo estructurado de solicitudes de confirmación para Jessyca Windows MCP (Subetapa 04.4).

Proporciona la administración, binding de acción (ActionFingerprint SHA-256), expiración,
consumo único (ALLOW_ONCE), protección Replay y sanitización de parámetros sensibles.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from core.event_bus import EventBus, get_event_bus
from core.logger import get_logger
from core.security import (
    PermissionAction,
    RiskLevel,
    SecurityDecision,
    SecurityManager,
    ToolSecurityProfile,
)
from core.security_architecture import SecurityLevel
from core.types import JSONDict

logger = get_logger("jessyca.confirmation")

# Claves de parámetros cuyo contenido debe ser sanitizado en representaciones de diagnóstico
SENSITIVE_PARAM_KEYS: set[str] = {
    "password",
    "pass",
    "token",
    "api_key",
    "apikey",
    "secret",
    "credential",
    "private_key",
    "auth",
}


class ConfirmationStatus(StrEnum):
    """Estados del ciclo de vida de una solicitud de confirmación."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


def compute_action_fingerprint(tool_name: str, operation: str, parameters: JSONDict) -> str:
    """Calcula deterministamente un hash SHA-256 para vincular una confirmación a una acción específica."""
    t_clean = tool_name.strip().lower()
    o_clean = operation.strip().lower()
    canonical_params = json.dumps(parameters or {}, sort_keys=True, ensure_ascii=True)
    raw_payload = f"{t_clean}:{o_clean}:{canonical_params}"
    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


def sanitize_sensitive_parameters(parameters: JSONDict) -> JSONDict:
    """Sanitiza recursivamente claves sensibles reemplazando sus valores por '[REDACTED]'."""
    if not isinstance(parameters, dict):
        return parameters

    sanitized: JSONDict = {}
    for key, value in parameters.items():
        key_str = str(key).lower()
        if any(s in key_str for s in SENSITIVE_PARAM_KEYS):
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_sensitive_parameters(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_sensitive_parameters(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitized


@dataclass
class ConfirmationRequest:
    """Solicitud estructurada de confirmación vinculada a una acción específica."""

    request_id: str
    tool_name: str
    message: str = ""
    risk_level: SecurityLevel | RiskLevel = SecurityLevel.DANGEROUS
    operation: str = "execute"
    parameters: JSONDict = field(default_factory=dict)
    sanitized_parameters: JSONDict = field(default_factory=dict)
    correlation_id: str = ""
    session_id: str = ""
    impact_summary: dict[str, Any] = field(default_factory=dict)
    risk_factors: set[Any] = field(default_factory=set)
    reason: str = ""
    fingerprint: str = ""
    available_actions: list[PermissionAction] = field(
        default_factory=lambda: [
            PermissionAction.ALLOW_ONCE,
            PermissionAction.ALWAYS_ALLOW,
            PermissionAction.DENY,
        ]
    )
    status: ConfirmationStatus | str = ConfirmationStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(seconds=300)
    )

    def __post_init__(self) -> None:
        if not self.request_id or not self.request_id.strip():
            raise ValueError("El campo 'request_id' no puede estar vacío.")
        if not self.tool_name or not self.tool_name.strip():
            raise ValueError("El campo 'tool_name' no puede estar vacío.")
        if self.expires_at <= self.created_at:
            raise ValueError("El tiempo de expiración 'expires_at' debe ser posterior a 'created_at'.")

        if not self.fingerprint:
            self.fingerprint = compute_action_fingerprint(self.tool_name, self.operation, self.parameters)
        if not self.sanitized_parameters and self.parameters:
            self.sanitized_parameters = sanitize_sensitive_parameters(self.parameters)


@dataclass
class ConfirmationResponse:
    """Respuesta del usuario a una solicitud de confirmación estructurada (compatibilidad)."""

    request_id: str
    selected_action: PermissionAction
    user_id: str = "user"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ConfirmationResult:
    """Resultado del estado de la confirmación entregado al sistema."""

    status: ConfirmationStatus | str
    request_id: str
    correlation_id: str = ""
    fingerprint: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    reason: str = ""
    approved_by: str = "user"
    is_consumed: bool = False
    expires_at: datetime | None = None

    @property
    def is_approved(self) -> bool:
        """Determina si la confirmación fue aprobada."""
        st_str = getattr(self.status, "value", str(self.status)).upper()
        return st_str == "APPROVED"


@runtime_checkable
class IConfirmationProvider(Protocol):
    """Protocolo/Interfaz abstracta para proveedores de confirmación (DIP)."""

    def request_confirmation(self, request: ConfirmationRequest) -> ConfirmationStatus | str:
        """Solicita la respuesta del proveedor de confirmación."""
        ...


class MockConfirmationProvider:
    """Proveedor desacoplado para pruebas unitarias que simula respuestas de confirmación."""

    def __init__(self, default_response: ConfirmationStatus | str = ConfirmationStatus.APPROVED) -> None:
        self.default_response = default_response

    def request_confirmation(self, request: ConfirmationRequest) -> ConfirmationStatus | str:
        return self.default_response


class ConfirmationManager:
    """Gestor central e inmutable de confirmaciones estructuradas con cerrojo de concurrencia."""

    def __init__(
        self,
        security_manager: SecurityManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.security_manager = security_manager or SecurityManager()
        self.event_bus = event_bus or get_event_bus()
        self._pending_requests: dict[str, ConfirmationRequest] = {}
        self._resolved_requests: dict[str, ConfirmationRequest] = {}
        self._consumed_requests: set[str] = set()
        self._lock = threading.Lock()

    def create_request(
        self,
        tool_name: str,
        message: str = "",
        risk_level: SecurityLevel | RiskLevel = SecurityLevel.DANGEROUS,
        operation: str = "execute",
        parameters: JSONDict | None = None,
        correlation_id: str = "",
        session_id: str = "",
        impact_summary: dict[str, Any] | None = None,
        risk_factors: set[Any] | None = None,
        reason: str = "",
        ttl_seconds: float = 300.0,
        available_actions: list[PermissionAction] | None = None,
    ) -> ConfirmationRequest:
        """Crea, valida y registra una nueva solicitud de confirmación estructurada."""
        params = parameters or {}
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        req_id = str(uuid.uuid4())

        actions = available_actions or [
            PermissionAction.ALLOW_ONCE,
            PermissionAction.ALWAYS_ALLOW,
            PermissionAction.DENY,
        ]

        req = ConfirmationRequest(
            request_id=req_id,
            tool_name=tool_name,
            message=message or f"Confirmación requerida para '{tool_name}'",
            risk_level=risk_level,
            operation=operation,
            parameters=params,
            sanitized_parameters=sanitize_sensitive_parameters(params),
            correlation_id=correlation_id,
            session_id=session_id,
            impact_summary=impact_summary or {},
            risk_factors=risk_factors or set(),
            reason=reason,
            available_actions=actions,
            status=ConfirmationStatus.PENDING,
            created_at=now,
            expires_at=expires_at,
        )

        with self._lock:
            self._pending_requests[req_id] = req

        logger.info(f"Solicitud de confirmación [{req_id}] creada para '{tool_name}' [Fingerprint: {req.fingerprint[:8]}]")

        self.event_bus.publish(
            "confirmation:requested",
            {
                "request_id": req_id,
                "tool_name": tool_name,
                "message": req.message,
                "risk_level": getattr(risk_level, "value", str(risk_level)),
                "impact_summary": req.impact_summary,
                "fingerprint": req.fingerprint,
            },
        )

        return req

    def submit_request(
        self,
        request: ConfirmationRequest,
        provider: IConfirmationProvider | None = None,
    ) -> ConfirmationResult:
        """Envía la solicitud al proveedor de confirmación y registra el resultado.
        
        GARANTÍA DE SEGURIDAD (FAIL-SAFE DENY):
        Si no se suministra un proveedor de confirmación, la solicitud se RECHAZA por defecto.
        Bajo ninguna circunstancia una confirmación sin proveedor debe auto-aprobarse.
        """
        prov = provider or MockConfirmationProvider(ConfirmationStatus.REJECTED)
        status_res = prov.request_confirmation(request)

        with self._lock:
            if datetime.now(UTC) >= request.expires_at:
                request.status = ConfirmationStatus.EXPIRED
            else:
                request.status = status_res

            if request.status == ConfirmationStatus.APPROVED:
                self._pending_requests.pop(request.request_id, None)
                self._resolved_requests[request.request_id] = request
            else:
                self._pending_requests.pop(request.request_id, None)
                self._resolved_requests[request.request_id] = request

        res_status = getattr(request.status, "value", str(request.status))
        logger.info(f"Solicitud de confirmación [{request.request_id}] resuelta con estado '{res_status}'")

        return ConfirmationResult(
            status=request.status,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            fingerprint=request.fingerprint,
            reason=f"Respuesta del proveedor: {res_status}",
            expires_at=request.expires_at,
        )

    def get_result(self, request_id: str) -> ConfirmationResult | None:
        """Obtiene el resultado de confirmación para una solicitud por su ID."""
        with self._lock:
            req = self._resolved_requests.get(request_id) or self._pending_requests.get(request_id)
            if not req:
                return None
            res_status = getattr(req.status, "value", str(req.status))
            return ConfirmationResult(
                status=req.status,
                request_id=req.request_id,
                correlation_id=req.correlation_id,
                fingerprint=req.fingerprint,
                reason=f"Estado de solicitud: {res_status}",
                expires_at=req.expires_at,
            )

    def cancel_request(self, request_id: str) -> bool:
        """Cancela una solicitud de confirmación pendiente."""
        with self._lock:
            req = self._pending_requests.pop(request_id, None)
            if req:
                req.status = ConfirmationStatus.CANCELLED
                self._resolved_requests[request_id] = req
                logger.info(f"Solicitud de confirmación [{request_id}] CANCELADA.")
                return True
            return False

    def consume_confirmation(
        self,
        request_id: str,
        tool_name: str,
        operation: str,
        parameters: JSONDict,
        session_id: str = "",
    ) -> bool:
        """Consume una confirmación aprobada verificando binding de fingerprint, expiración y uso único."""
        with self._lock:
            if request_id in self._consumed_requests:
                logger.warning(f"Replay Attack Bloqueado: La confirmación [{request_id}] ya fue consumida.")
                return False

            req = self._resolved_requests.get(request_id)
            if not req or str(req.status).lower() != "approved":
                logger.warning(f"Consumo Rechazado: Solicitud [{request_id}] no está aprobada.")
                return False

            if session_id and req.session_id and req.session_id != session_id:
                logger.warning(f"Consumo Rechazado: Desalineación de session_id para [{request_id}].")
                return False

            if datetime.now(UTC) >= req.expires_at:
                req.status = ConfirmationStatus.EXPIRED
                logger.warning(f"Consumo Rechazado: La confirmación [{request_id}] ha expirado.")
                return False

            target_fp = compute_action_fingerprint(tool_name, operation, parameters)
            if req.fingerprint != target_fp:
                logger.warning(
                    f"Consumo Rechazado: Mismatch de ActionFingerprint para [{request_id}]. Esperado '{req.fingerprint[:8]}', recibido '{target_fp[:8]}'."
                )
                return False

            self._consumed_requests.add(request_id)
            logger.info(f"Confirmación [{request_id}] consumida exitosamente para '{tool_name}'.")
            return True

    def get_pending_request(self, request_id: str) -> ConfirmationRequest | None:
        """Obtiene una solicitud de confirmación pendiente por su ID verificando expiración."""
        with self._lock:
            req = self._pending_requests.get(request_id)
            if req and datetime.now(UTC) >= req.expires_at:
                req.status = ConfirmationStatus.EXPIRED
                self._pending_requests.pop(request_id, None)
                self._resolved_requests[request_id] = req
                return None
            return req

    def list_pending_requests(self) -> list[ConfirmationRequest]:
        """Obtiene la lista de todas las solicitudes de confirmación pendientes no expiradas."""
        with self._lock:
            now = datetime.now(UTC)
            active: list[ConfirmationRequest] = []
            for req_id, req in list(self._pending_requests.items()):
                if now >= req.expires_at:
                    req.status = ConfirmationStatus.EXPIRED
                    self._pending_requests.pop(req_id, None)
                    self._resolved_requests[req_id] = req
                else:
                    active.append(req)
            return active

    def resolve_request(
        self,
        request_id: str,
        selected_action: PermissionAction,
        profile: ToolSecurityProfile | None = None,
        user_id: str = "user",
    ) -> SecurityDecision:
        """Resuelve una solicitud de confirmación aplicando la acción elegida por el usuario (compatibilidad)."""
        with self._lock:
            req = self._pending_requests.pop(request_id, None)
            if req is None:
                raise KeyError(f"No se encontró solicitud de confirmación pendiente con ID: '{request_id}'")

            if selected_action in (PermissionAction.ALLOW, PermissionAction.ALLOW_ONCE, PermissionAction.ALWAYS_ALLOW):
                req.status = ConfirmationStatus.APPROVED
            else:
                req.status = ConfirmationStatus.REJECTED

            self._resolved_requests[request_id] = req

        sec_profile = profile or ToolSecurityProfile(
            name=req.tool_name,
            category="general",
            risk_level=getattr(req, "risk_level", RiskLevel.DANGEROUS),
        )

        decision = self.security_manager.process_user_action(sec_profile, selected_action, user=user_id)
        decision.confirmation_request = req

        status_str = getattr(req.status, "value", str(req.status))
        logger.info(
            f"Solicitud de confirmación [{request_id}] resuelta con acción '{selected_action.value}' (Estado: {status_str})."
        )

        self.event_bus.publish(
            "confirmation:resolved",
            {
                "request_id": request_id,
                "tool_name": req.tool_name,
                "action": selected_action.value,
                "status": status_str,
                "user_id": user_id,
            },
        )

        return decision
