"""Modelos de datos formales para el Núcleo Conversacional de JESSYCA (Fases 49 y 50).

Define:
1. Estados de Sesión (ConversationStatus).
2. Estados de Diálogo (DialogueState).
3. Roles de Turno (TurnRole).
4. Turno Conversacional (ConversationTurn).
5. Ítem de Contexto Ponderado (ContextItem).
6. Sesión Conversacional Continua (ConversationSession).

INVARIANTE DE SEGURIDAD ABSOLUTA:
El contexto conversacional NUNCA confiere autorización (CONTEXT != AUTHORIZATION).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.local_agent.local_agent_models import InputModality
from core.logger import get_logger

logger = get_logger("jessyca.local_agent.conversation_models")


class ConversationStatus(StrEnum):
    """Estados del ciclo de vida de una sesión conversacional."""

    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    PROCESSING = "PROCESSING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class DialogueState(StrEnum):
    """Estados del diálogo en la máquina de estados conversacional."""

    NO_ACTIVE_TASK = "NO_ACTIVE_TASK"
    TASK_ACTIVE = "TASK_ACTIVE"
    WAITING_FOR_PARAMETER = "WAITING_FOR_PARAMETER"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    WAITING_FOR_CLARIFICATION = "WAITING_FOR_CLARIFICATION"
    ANSWERING = "ANSWERING"
    EXECUTING = "EXECUTING"


class TurnRole(StrEnum):
    """Roles de los participantes en un turno conversacional."""

    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"


# Claves de contexto que intentan inyectar autorizaciones de seguridad
FORBIDDEN_CONTEXT_KEYS: set[str] = {
    "authorization",
    "authorized",
    "is_authorized",
    "permission",
    "permissions",
    "security_level",
    "security_verdict",
    "security_override",
    "allow_all",
    "bypass_security",
    "admin_access",
    "root",
}


@dataclass(frozen=True)
class ContextItem:
    """Elemento contextual ponderado con origen, relevancia y marca temporal."""

    key: str
    value: Any
    relevance: float = 1.0
    timestamp: float = field(default_factory=time.time)
    source: str = "dialogue_turn"

    def is_fresh(self, max_age_seconds: float = 180.0) -> bool:
        """Determina si el elemento contextual es reciente y vigente."""
        return (time.time() - self.timestamp) <= max_age_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "relevance": self.relevance,
            "timestamp": self.timestamp,
            "source": self.source,
        }


@dataclass(frozen=True)
class ConversationTurn:
    """Representa un turno conversacional individual inmutable."""

    turn_id: str = field(default_factory=lambda: f"turn-{uuid.uuid4().hex[:8]}")
    role: TurnRole = TurnRole.USER
    raw_input: str = ""
    normalized_input: str = ""
    user_prompt: str = ""
    assistant_response: str = ""
    intent: str = "unknown"
    intent_confidence: float = 1.0
    modality: InputModality = InputModality.TEXT
    tools_executed: tuple[str, ...] = ()
    security_verdict: str = "ALLOW"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "role": str(self.role),
            "raw_input": self.raw_input or self.user_prompt,
            "normalized_input": self.normalized_input,
            "user_prompt": self.user_prompt,
            "assistant_response": self.assistant_response,
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "modality": str(self.modality),
            "tools_executed": list(self.tools_executed),
            "security_verdict": self.security_verdict,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ShortTermMemory:
    """Modelo estructurado de memoria a corto plazo para una sesión conversacional activa (Fase 54)."""

    session_id: str
    recent_turns: list[ConversationTurn] = field(default_factory=list)
    active_entities: dict[str, Any] = field(default_factory=dict)
    current_task: str | None = None
    pending_question: str | None = None
    current_application: str | None = None
    recent_results: list[dict[str, Any]] = field(default_factory=list)
    last_activity: float = field(default_factory=time.time)

    def is_expired(self, timeout_seconds: float = 300.0) -> bool:
        """Determina si la memoria a corto plazo ha expirado."""
        return (time.time() - self.last_activity) > timeout_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "recent_turns": [t.to_dict() for t in self.recent_turns],
            "active_entities": self.active_entities,
            "current_task": self.current_task,
            "pending_question": self.pending_question,
            "current_application": self.current_application,
            "recent_results": self.recent_results,
            "last_activity": self.last_activity,
        }


@dataclass
class ConversationSession:
    """Representa una sesión conversacional activa de múltiples turnos."""

    conversation_id: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    status: ConversationStatus = ConversationStatus.ACTIVE
    dialogue_state: DialogueState = DialogueState.NO_ACTIVE_TASK
    turns: list[ConversationTurn] = field(default_factory=list)
    active_context: dict[str, Any] = field(default_factory=dict)
    context_items: dict[str, ContextItem] = field(default_factory=dict)
    pending_intent: str | None = None
    pending_question: str | None = None
    pending_parameters: dict[str, Any] = field(default_factory=dict)
    expected_slot: str | None = None
    pending_confirmation: dict[str, Any] | None = None
    max_turns: int = 20

    def touch(self) -> None:
        """Actualiza la marca de tiempo de última actividad."""
        self.last_activity = time.time()

    def is_expired(self, timeout_seconds: float = 300.0) -> bool:
        """Determina si la sesión ha expirado por inactividad temporal."""
        if self.status == ConversationStatus.CLOSED:
            return True
        return (time.time() - self.last_activity) > timeout_seconds

    def add_turn(self, turn: ConversationTurn) -> None:
        """Agrega un turno al historial respetando el límite máximo de retención."""
        self.touch()
        self.turns.append(turn)
        if len(self.turns) > self.max_turns:
            self.turns.pop(0)

        # Actualizar contexto corto automáticamente
        if turn.role == TurnRole.USER or turn.user_prompt:
            self.set_context_item("last_user_intent", turn.intent, relevance=0.9, source="user_turn")
            self.set_context_item("last_user_prompt", turn.user_prompt, relevance=0.8, source="user_turn")
        if turn.role == TurnRole.ASSISTANT or turn.assistant_response:
            self.set_context_item("last_assistant_response", turn.assistant_response, relevance=0.8, source="assistant_turn")

    def update_context(self, key: str, value: Any) -> None:
        """Actualiza un valor en el contexto corto con protección contra escalada de privilegios."""
        self.set_context_item(key, value, relevance=1.0, source="direct_update")

    def set_context_item(
        self,
        key: str,
        value: Any,
        relevance: float = 1.0,
        source: str = "dialogue",
    ) -> None:
        """Establece un ítem contextual ponderado con validación estricta de seguridad."""
        key_clean = key.strip().lower()

        # REGLA: CONTEXT != AUTHORIZATION
        if key_clean in FORBIDDEN_CONTEXT_KEYS or "auth" in key_clean or "permit" in key_clean or "override" in key_clean:
            logger.warning(
                f"[SECURITY BLOCKED] Intento de inyectar clave de autorización '{key}' en contexto conversacional bloqueado."
            )
            return

        self.touch()
        item = ContextItem(key=key, value=value, relevance=relevance, timestamp=time.time(), source=source)
        self.context_items[key] = item
        self.active_context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """Obtiene un valor del contexto corto activo."""
        return self.active_context.get(key, default)

    def get_context_item(self, key: str) -> ContextItem | None:
        """Obtiene el objeto ContextItem ponderado si existe."""
        return self.context_items.get(key)

    def get_short_term_memory(self, turn_limit: int = 5) -> ShortTermMemory:
        """Genera una vista estructurada de la memoria a corto plazo de la sesión."""
        # Extraer entidades activas (excluyendo metadatos de turnos)
        entities = {
            k: v.value
            for k, v in self.context_items.items()
            if not k.startswith("last_user_") and not k.startswith("last_assistant_")
        }

        # Extraer resultados recientes
        results: list[dict[str, Any]] = []
        for k, v in self.context_items.items():
            if "result" in k or "calculation" in k:
                if isinstance(v.value, dict):
                    results.append(v.value)
                else:
                    results.append({k: v.value})

        curr_app = (
            self.active_context.get("current_application")
            or self.active_context.get("last_app")
            or self.active_context.get("app_name")
        )

        return ShortTermMemory(
            session_id=self.conversation_id,
            recent_turns=list(self.turns[-turn_limit:]),
            active_entities=entities,
            current_task=self.pending_intent or self.active_context.get("current_task"),
            pending_question=self.pending_question,
            current_application=curr_app,
            recent_results=results,
            last_activity=self.last_activity,
        )

    def get_relevant_context(
        self,
        query: str = "",
        min_relevance: float = 0.5,
        max_age_seconds: float = 180.0,
        max_items: int = 5,
    ) -> dict[str, Any]:
        """Obtiene el subconjunto de contexto filtrado por relevancia, vigencia y afinidad temática."""
        scored_items: list[tuple[float, str, Any]] = []
        query_words = set(query.lower().split()) if query else set()

        for key, item in self.context_items.items():
            if not item.is_fresh(max_age_seconds):
                continue

            score = item.relevance
            # Bono de afinidad temática léxica si hay consulta
            if query_words:
                item_text = f"{key} {item.value}".lower()
                matches = sum(
                    1
                    for w in query_words
                    if (len(w) >= 3 and (w[:4] in item_text or w in item_text or any(part in w for part in key.lower().split("_"))))
                )
                if matches > 0:
                    score += 0.3 * matches
                else:
                    # Penalizar si la consulta busca algo específico y no hay match
                    score *= 0.5

            if score >= min_relevance:
                scored_items.append((score, key, item.value))

        # Ordenar por relevancia descendente y limitar a max_items
        scored_items.sort(key=lambda x: x[0], reverse=True)
        return {k: val for _, k, val in scored_items[:max_items]}

    def clear_task_context(self) -> None:
        """Limpia el contexto de tarea activa ante cambios de tema sin borrar identidad de sesión."""
        self.touch()
        for k in ("current_task", "last_calculation", "pending_intent", "pending_question", "expected_slot"):
            self.active_context.pop(k, None)
            self.context_items.pop(k, None)
        self.pending_intent = None
        self.pending_question = None
        self.expected_slot = None
        self.pending_parameters.clear()
        self.dialogue_state = DialogueState.NO_ACTIVE_TASK

    def set_pending_question(
        self,
        question: str,
        intent: str,
        expected_slot: str,
        partial_parameters: dict[str, Any] | None = None,
    ) -> None:
        """Establece una pregunta pendiente para completitud de parámetros."""
        self.touch()
        self.pending_question = question
        self.pending_intent = intent
        self.expected_slot = expected_slot
        self.pending_parameters = dict(partial_parameters or {})
        self.dialogue_state = DialogueState.WAITING_FOR_PARAMETER
        self.status = ConversationStatus.WAITING_FOR_USER

    def set_pending_confirmation(
        self,
        intent: str,
        tool: str,
        parameters: dict[str, Any],
        prompt: str,
        security_level: str = "MEDIUM",
    ) -> None:
        """Establece una acción pendiente de confirmación por el usuario."""
        self.touch()
        self.pending_confirmation = {
            "intent": intent,
            "tool": tool,
            "parameters": dict(parameters),
            "prompt": prompt,
            "security_level": security_level,
        }
        self.dialogue_state = DialogueState.WAITING_FOR_CONFIRMATION
        self.status = ConversationStatus.WAITING_FOR_USER

    def clear_pending_confirmation(self) -> None:
        """Limpia la confirmación pendiente."""
        self.touch()
        self.pending_confirmation = None
        if self.dialogue_state == DialogueState.WAITING_FOR_CONFIRMATION:
            self.dialogue_state = DialogueState.NO_ACTIVE_TASK
        if self.status == ConversationStatus.WAITING_FOR_USER:
            self.status = ConversationStatus.ACTIVE

    def clear_pending(self) -> None:
        """Limpia el estado de pregunta pendiente y restablece el estado dialógico."""
        self.touch()
        self.pending_question = None
        self.pending_intent = None
        self.expected_slot = None
        self.pending_parameters.clear()
        self.dialogue_state = DialogueState.NO_ACTIVE_TASK
        if self.status == ConversationStatus.WAITING_FOR_USER:
            self.status = ConversationStatus.ACTIVE

    def close(self) -> None:
        """Cierra formalmente la sesión conversacional y limpia el contexto activo."""
        self.touch()
        self.status = ConversationStatus.CLOSED
        self.dialogue_state = DialogueState.NO_ACTIVE_TASK
        self.active_context.clear()
        self.context_items.clear()
        self.pending_question = None
        self.pending_intent = None
        self.pending_parameters.clear()
        self.expected_slot = None
        logger.info(f"[CONVERSATION CLOSED] Sesión '{self.conversation_id}' cerrada limpiamente.")

    def to_dict(self) -> dict[str, Any]:
        """Convierte la sesión en un diccionario serializable."""
        return {
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "status": self.status.value,
            "dialogue_state": self.dialogue_state.value,
            "turns_count": len(self.turns),
            "active_context": self.active_context,
            "context_items": {k: v.to_dict() for k, v in self.context_items.items()},
            "pending_intent": self.pending_intent,
            "pending_question": self.pending_question,
            "expected_slot": self.expected_slot,
        }
