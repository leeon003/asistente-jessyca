"""Modelos de Datos para Human-in-the-Loop e Interacción Confiable (interaction_models.py - Fase 41).

Define:
- InteractionAction: ACTS, ASKS, CLARIFIES, CONFIRMS, PAUSES, DENIES, STOPS.
- InteractionState: EXECUTE, ASK_CLARIFICATION, REQUEST_CONFIRMATION, WAITING_USER, DENIED, PAUSED, CANCELLED, COMPLETED, FAILED.
- ClarificationPrompt: Preguntas y opciones ante intenciones ambiguas o incompletas.
- ConfirmationPrompt: Solicitudes explicables de confirmación con alcance, parámetros y riesgo.
- InteractionDecision: Decisión final evaluada del flujo de interacción.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.security_architecture import SecurityLevel


class InteractionAction(StrEnum):
    """Acción de interacción decidida por el sistema."""

    ACTS = "ACTS"                # Ejecución directa autorizada sin necesidad de confirmación.
    ASKS = "ASKS"                # Pregunta al usuario ante información faltante no crítica.
    CLARIFIES = "CLARIFIES"      # Solicitud de aclaración estructurada ante ambigüedad en parámetros críticos.
    CONFIRMS = "CONFIRMS"        # Requerimiento de confirmación explícita con explicación de alcance y riesgo.
    PAUSES = "PAUSES"            # Pausa de ejecución por solicitud de usuario o desvío detectado.
    DENIES = "DENIES"            # Denegación inmutable de seguridad (acción prohibida).
    STOPS = "STOPS"              # Parada inmediata e incondicional por Emergency Stop.


class InteractionState(StrEnum):
    """Estados canónicos de interacción con el usuario."""

    EXECUTE = "EXECUTE"
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"
    WAITING_USER = "WAITING_USER"
    DENIED = "DENIED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class UserResponseType(StrEnum):
    """Tipos de respuesta emitida por el usuario."""

    CONFIRM = "CONFIRM"
    REJECT = "REJECT"
    CLARIFY = "CLARIFY"
    MODIFY = "MODIFY"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"


@dataclass(frozen=True)
class ClarificationPrompt:
    """Solicitud de aclaración ante intenciones ambiguas o incompletas."""

    prompt_id: str = field(default_factory=lambda: f"clar-{uuid.uuid4().hex[:8]}")
    question: str = ""
    candidate_options: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    context_hint: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ConfirmationPrompt:
    """Solicitud de confirmación estructurada y explicable."""

    confirmation_id: str = field(default_factory=lambda: f"conf-{uuid.uuid4().hex[:8]}")
    task_id: str = ""
    action_name: str = ""
    target_resource: str = ""
    objective: str = ""
    scope_description: str = ""
    risk_level: SecurityLevel = SecurityLevel.ELEVATED
    relevant_parameters: dict[str, Any] = field(default_factory=dict)
    potential_impact: str = ""
    ttl_seconds: float = 120.0
    created_at: float = field(default_factory=time.time)

    def compute_params_hash(self) -> str:
        raw = f"{self.action_name}:{self.target_resource}:{json.dumps(self.relevant_parameters, sort_keys=True)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


@dataclass(frozen=True)
class InteractionDecision:
    """Decisión de interacción evaluada por InteractionPolicy."""

    action: InteractionAction
    state: InteractionState
    reason: str
    clarification: ClarificationPrompt | None = None
    confirmation: ConfirmationPrompt | None = None
    execution_authorized: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class UserInteractionResponse:
    """Respuesta explícita provista por el usuario."""

    response_type: UserResponseType
    confirmation_id: str | None = None
    prompt_id: str | None = None
    selected_option: str | None = None
    modified_parameters: dict[str, Any] | None = None
    comment: str = ""
    timestamp: float = field(default_factory=time.time)
