"""Contrato Tipado e Inmutable de Intención y Ciclo de Vida de Acción (Fase 64.1.1).

Define los modelos de datos formales para transportar una acción completa
a través de las etapas del pipeline de JESSYCA sin acoplamiento con subsistemas ejecutores:
USER REQUEST -> INTENT -> TARGET/PARAMS -> CONFIDENCE/UNDERSTANDING -> CAN EXECUTE?
-> NEEDS CLARIFICATION? -> NEEDS CONFIRMATION? -> PRE-ACTION STATUS -> EXECUTION
-> POST-ACTION VERIFICATION -> REAL RESULT -> VOICE RESPONSE -> EXPERIENCE LOGGING.

INVARIANTES Y REGLAS DE DISEÑO:
1. TOTAL DESACOPLAMIENTO: No importa agentes, gestores de skills, verificadores ni motores de audio.
2. INMUTABILIDAD ESTRICTA: Todos los modelos son inmutables (frozen=True).
3. ANTI-FALSE SUCCESS: is_verified == False OBLIGA determinísticamente claims_success == False.
4. GATEKEEPER CONSISTENCY:
   - needs_clarification == True exige clarification_prompt no vacío.
   - needs_confirmation == True exige confirmation_prompt no vacío.
5. IDENTIFICADORES Y NOMBRES VÁLIDOS: request_id, session_id e intent_name no pueden ser cadenas vacías.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ActionIntent(BaseModel):
    """Representa la comprensión e interpretación de la petición del usuario.

    Modela qué desea hacer el usuario, sobre qué objetivo y con qué grado de certeza,
    sin prejuzgar si la acción es ejecutable o segura.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_name: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_ambiguous: bool = False
    input_modality: str = "text"
    target: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)

    @field_validator("intent_name")
    @classmethod
    def _validate_intent_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("intent_name no puede ser una cadena vacía.")
        return clean

    @field_validator("input_modality")
    @classmethod
    def _validate_input_modality(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("input_modality no puede ser una cadena vacía.")
        return clean


class ExecutionGate(BaseModel):
    """Representa las compuertas de gobernanza para determinar si una acción puede avanzar.

    Captura si la intención está lista para ejecución, si requiere desambiguación/aclaración,
    o si exige autorización explícita humana por nivel de riesgo.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    can_execute: bool = True
    needs_clarification: bool = False
    clarification_prompt: str | None = None
    needs_confirmation: bool = False
    risk_level: str | None = None
    confirmation_prompt: str | None = None

    @model_validator(mode="after")
    def _validate_gate_consistency(self) -> ExecutionGate:
        # Validación de aclaración
        if self.needs_clarification:
            if not self.clarification_prompt or not self.clarification_prompt.strip():
                raise ValueError(
                    "ExecutionGate inconsistente: needs_clarification=True exige un clarification_prompt no vacío."
                )

        # Validación de confirmación
        if self.needs_confirmation:
            if not self.confirmation_prompt or not self.confirmation_prompt.strip():
                raise ValueError(
                    "ExecutionGate inconsistente: needs_confirmation=True exige un confirmation_prompt no vacío."
                )

        return self


class PreActionFeedback(BaseModel):
    """Representa exclusivamente la locución de acuse de recibo previa a la ejecución.

    Informa al usuario de lo que el sistema va a realizar (acknowledgement) antes de
    bloquearse en una tarea de sistema operativo o inferencia prolongada.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    acknowledgement_speech: str | None = None


class ExecutionSpec(BaseModel):
    """Especificación técnica inmutable requerida para despachar la ejecución de la acción.

    Contiene exclusivamente los identificadores de la skill, tool y clave de idempotencia,
    sin interactuar con el entorno ni ejecutar código del sistema operativo.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: str
    tool_name: str | None = None
    idempotency_key: str

    @field_validator("skill_id")
    @classmethod
    def _validate_skill_id(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("skill_id no puede ser una cadena vacía.")
        return clean

    @field_validator("idempotency_key")
    @classmethod
    def _validate_idempotency_key(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("idempotency_key no puede ser una cadena vacía.")
        return clean


class ActionExecutionReport(BaseModel):
    """Representa el resultado de ejecución física y verificación determinista sobre el sistema.

    Aplica rigurosamente la regla fundamental de JESSYCA:
    NO EXECUTION EVIDENCE / NO VERIFICATION = NO SUCCESS CLAIM (Anti-False Success).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: str | None = None
    tool_name: str | None = None
    execution_status: str | None = None
    is_verified: bool = False
    claims_success: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None

    @model_validator(mode="after")
    def _validate_anti_false_success(self) -> ActionExecutionReport:
        if not self.is_verified and self.claims_success:
            raise ValueError(
                "Invariante violada (Anti-False Success): claims_success no puede ser True si is_verified es False."
            )
        return self


class PostActionFeedback(BaseModel):
    """Representa la respuesta verbal y textual final generada tras conocerse el resultado real."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spoken_response: str
    response_text: str | None = None

    @field_validator("spoken_response")
    @classmethod
    def _validate_spoken_response(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("spoken_response no puede ser una cadena vacía.")
        return clean


class ActionIntentContract(BaseModel):
    """Objeto raíz que representa el contrato y ciclo de vida integral de una acción en JESSYCA.

    Es un snapshot seguro e inmutable que acompaña la intención desde su análisis hasta
    la verificación y persistencia en el log de experiencia.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    session_id: str
    action_intent: ActionIntent
    execution_gate: ExecutionGate
    pre_action_feedback: PreActionFeedback = Field(default_factory=PreActionFeedback)
    execution_spec: ExecutionSpec | None = None
    execution_report: ActionExecutionReport | None = None
    post_action_feedback: PostActionFeedback | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("request_id")
    @classmethod
    def _validate_request_id(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("request_id no puede ser una cadena vacía.")
        return clean

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("session_id no puede ser una cadena vacía.")
        return clean


__all__ = [
    "ActionExecutionReport",
    "ActionIntent",
    "ActionIntentContract",
    "ExecutionGate",
    "ExecutionSpec",
    "PostActionFeedback",
    "PreActionFeedback",
]
