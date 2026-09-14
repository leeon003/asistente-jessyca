"""Módulo de Recuperación Conversacional y Resolución de Errores (action_recovery.py - Fase 64.3.4).

Gestiona la recuperación conversacional inteligente ante errores, fallos, ambigüedades
o resultados no verificables dentro del sistema de acciones de JESSYCA 3.0:

PRINCIPIOS FUNDAMENTALES:
1. Un fallo NO significa automáticamente que la conversación terminó.
2. Anti-False-Success: EXECUTION_FAILURE, VERIFICATION_FAILURE y UNVERIFIED NUNCA se convierten en SUCCESS.
3. El reintento (retry) es conversacional, seguro e idempotente:
   - NUNCA se salta el ExecutionGate ni las autorizaciones/permisos.
   - Cada reintento genera un action_id unificado (original_action_id -> retry_action_id).
   - En secuencias, NO duplica pasos previamente exitosos.
4. "Sí" solo se interpreta como retry si existe explícitamente una oferta de recuperación pendiente.
5. "No", "cancela", "olvídalo" cancela limpiamente la recuperación y cualquier secuencia pausada.
6. Soporta modificación/reemplazo de la acción fallida ("mejor abre Y") y nuevas intenciones no relacionadas.
7. Los errores técnicos se comunican al usuario en lenguaje natural seguro (sin exponer stack traces).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from core.logger import get_logger

if TYPE_CHECKING:
    from core.action_intent_contract import ActionIntentContract
    from core.execution.action_pipeline import ActionPipelineResult

logger = get_logger("jessyca.dialogue.action_recovery")


class ActionFailureCategory(StrEnum):
    """Categorías canónicas de fallo para acciones en JESSYCA (Fase 64.3.4)."""

    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    UNVERIFIED = "UNVERIFIED"
    AMBIGUITY = "AMBIGUITY"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ActionRecoveryState(StrEnum):
    """Estados del ciclo de vida de recuperación de una acción fallida."""

    NONE = "NONE"
    RETRY_AVAILABLE = "RETRY_AVAILABLE"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    MODIFICATION_AVAILABLE = "MODIFICATION_AVAILABLE"
    SEQUENCE_PAUSED = "SEQUENCE_PAUSED"
    CANCELLED = "CANCELLED"
    RESOLVED = "RESOLVED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


class RecoveryUserIntent(StrEnum):
    """Intenciones conversacionales del usuario en respuesta a una recuperación."""

    RETRY = "RETRY"
    CANCEL = "CANCEL"
    MODIFY = "MODIFY"
    CLARIFY = "CLARIFY"
    UNRELATED = "UNRELATED"


@dataclass
class ActionRecoveryContext:
    """Contexto formal de recuperación de una acción fallida o pausada (Fase 64.3.4).

    Conserva la trazabilidad completa, la relación original_id -> retry_id,
    el conteo de reintentos y el estado de la secuencia si aplica.
    """

    action_id: str
    original_action_id: str
    session_id: str
    intent: str
    target: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    risk_level: str | int | None = 1
    requires_confirmation: bool = False
    failure_category: ActionFailureCategory = ActionFailureCategory.EXECUTION_FAILURE
    failure_reason: str = ""
    friendly_explanation: str = ""
    recovery_state: ActionRecoveryState = ActionRecoveryState.RETRY_AVAILABLE
    retry_count: int = 0
    max_retries: int = 2
    sequence_id: str | None = None
    step_id: str | None = None
    step_number: int | None = None
    contract: ActionIntentContract | None = None
    pipeline_result: ActionPipelineResult | None = None
    execution_result: Any | None = None
    verification_result: Any | None = None
    prompt_offered: str | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def can_retry(self) -> bool:
        """Determina si la acción puede ser reintentada según la política de retries."""
        return (
            self.retry_count < self.max_retries
            and self.recovery_state in (
                ActionRecoveryState.RETRY_AVAILABLE,
                ActionRecoveryState.SEQUENCE_PAUSED,
                ActionRecoveryState.MODIFICATION_AVAILABLE,
            )
        )

    def next_retry_action_id(self) -> str:
        """Genera un action_id determinista y trazable para el siguiente intento."""
        return f"retry-{self.retry_count + 1}-{self.original_action_id}"

    def increment_retry(self) -> None:
        """Incrementa el contador de reintentos y actualiza el timestamp."""
        self.retry_count += 1
        self.timestamp = time.time()
        if self.retry_count >= self.max_retries:
            self.recovery_state = ActionRecoveryState.LIMIT_EXCEEDED

    def mark_cancelled(self) -> None:
        """Marca el contexto de recuperación como cancelado por el usuario."""
        self.recovery_state = ActionRecoveryState.CANCELLED
        self.timestamp = time.time()

    def mark_resolved(self) -> None:
        """Marca la recuperación como exitosamente resuelta."""
        self.recovery_state = ActionRecoveryState.RESOLVED
        self.timestamp = time.time()

    def mark_paused(self) -> None:
        """Marca la recuperación en estado de secuencia pausada."""
        self.recovery_state = ActionRecoveryState.SEQUENCE_PAUSED
        self.timestamp = time.time()


# ── HELPERS DETERMINISTAS DE CLASIFICACIÓN Y SANITIZACIÓN ────────────────────


def classify_failure_category(
    pipe_res: ActionPipelineResult | None,
    raw_error: str | None = None,
) -> ActionFailureCategory:
    """Determina la categoría canónica de fallo a partir del resultado del pipeline."""
    if pipe_res is None:
        return ActionFailureCategory.EXECUTION_FAILURE

    # 1. Rechazo por ExecutionGate o permisos
    if hasattr(pipe_res, "status") and getattr(pipe_res.status, "value", str(pipe_res.status)) in ("REJECTED", "REJECT"):
        return ActionFailureCategory.REJECTED
    if pipe_res.decision:
        d_type = getattr(pipe_res.decision, "decision_type", None)
        if d_type and getattr(d_type, "value", str(d_type)) in ("REJECT", "REJECTED"):
            return ActionFailureCategory.REJECTED

    # 2. Fallo durante ejecución física en Dispatcher / Skill (EXECUTION_FAILURE)
    if pipe_res.dispatch_result and not pipe_res.dispatch_result.is_success:
        return ActionFailureCategory.EXECUTION_FAILURE

    # 3. Evaluación de Verificación post-ejecución (VERIFICATION_FAILURE / UNVERIFIED)
    if pipe_res.verification_report:
        v_status = getattr(pipe_res.verification_report, "verification_status", None) or getattr(pipe_res.verification_report, "status", None)
        if v_status:
            v_val = v_status.value if hasattr(v_status, "value") else str(v_status)
            if v_val == "UNVERIFIED":
                return ActionFailureCategory.UNVERIFIED
            if v_val in ("VERIFIED_FAILURE", "VERIFICATION_ERROR"):
                return ActionFailureCategory.VERIFICATION_FAILURE

    # 4. Ambigüedad
    if hasattr(pipe_res, "status") and pipe_res.status.value == "CLARIFICATION_REQUIRED":
        return ActionFailureCategory.AMBIGUITY

    # Fallo por defecto
    return ActionFailureCategory.EXECUTION_FAILURE


def format_friendly_error(
    category: ActionFailureCategory,
    target: str | None,
    raw_error: str | None = None,
) -> str:
    """Convierte errores técnicos a explicaciones claras en lenguaje natural.

    REGLA 15: No exponer excepciones técnicas (WinError, FileNotFoundError, etc.).
    """
    target_name = (target or "la aplicación").strip()

    if category == ActionFailureCategory.REJECTED:
        return f"La acción en {target_name} fue rechazada por motivos de seguridad o permisos."

    if category == ActionFailureCategory.UNVERIFIED:
        return f"No pude verificar con seguridad si {target_name} completó la acción."

    if category == ActionFailureCategory.VERIFICATION_FAILURE:
        return f"No pude confirmar el resultado en {target_name}: la acción no tuvo el efecto esperado."

    if category == ActionFailureCategory.AMBIGUITY:
        return f"Hay varias opciones posibles para {target_name} y necesito que me aclares cuál prefieres."

    if category == ActionFailureCategory.CANCELLED:
        return "La operación fue cancelada."

    # EXECUTION_FAILURE: sanitizar mensajes técnicos comunes
    if raw_error:
        lower_err = raw_error.lower()
        if "not found" in lower_err or "no encontrado" in lower_err or "no se encuentra" in lower_err:
            return f"No pude encontrar la aplicación {target_name} en el equipo."
        if "access denied" in lower_err or "permiso" in lower_err or "denegado" in lower_err:
            return f"No tengo permisos suficientes para ejecutar {target_name}."
        if "timeout" in lower_err or "tiempo" in lower_err:
            return f"El tiempo de espera para {target_name} se agotó."

    return f"No pude abrir {target_name}." if "open" in str(raw_error or "").lower() else f"No pude completar la acción en {target_name}."


def build_recovery_prompt(
    category: ActionFailureCategory,
    target: str | None,
    raw_error: str | None = None,
    sequence_context: str | None = None,
    can_retry: bool = True,
) -> str:
    """Genera la respuesta conversacional natural ofreciendo recuperación.

    REGLA 20: Respuestas naturales y breves.
    """
    target_display = target or "la aplicación"
    friendly_err = format_friendly_error(category, target, raw_error)

    if not can_retry:
        return f"Ya lo intenté varias veces y {target_display} sigue sin responder. ¿Quieres que hagamos otra cosa?"

    if category == ActionFailureCategory.REJECTED:
        return f"{friendly_err} Si deseas realizarla, debes confirmar explícitamente."

    if sequence_context:
        # En secuencias: "Abrí Chrome y YouTube, pero no pude abrir Spotify. ¿Quieres que lo intente de nuevo?"
        return f"{sequence_context}, pero {friendly_err.lower()} ¿Quieres que lo intente de nuevo?"

    return f"{friendly_err} ¿Quieres que lo intente de nuevo?"


def classify_recovery_intent(
    user_input: str,
    recovery_context: ActionRecoveryContext | None = None,
) -> tuple[RecoveryUserIntent, str | None]:
    """Analiza conversacionalmente la respuesta del usuario ante una recuperación pendiente.

    Retorna (RecoveryUserIntent, detail_or_target).
    """
    text = user_input.strip().lower()

    # 1. CANCELACIÓN EXPLÍCITA
    # Expresiones: "no", "no gracias", "cancela", "cancelar", "olvídalo", "ya no", "déjalo", "no importa"
    cancel_exact = (
        "no",
        "no gracias",
        "no lo hagas",
        "para nada",
        "nunca",
        "cancela",
        "cancelar",
        "cancélalo",
        "cancelalo",
        "olvídalo",
        "olvidalo",
        "ya no",
        "ya no quiero",
        "déjalo",
        "dejalo",
        "no importa",
        "abortar",
        "aborta",
        "basta",
        "déjalo así",
        "dejalo asi",
    )
    if text in cancel_exact or re.match(
        r"^(?:no|cancela|cancelar|cancélalo|cancelalo|olvídalo|olvidalo|ya\s+no|déjalo|dejalo|no\s+importa)(?:,\s*.*)?$",
        text,
    ):
        return RecoveryUserIntent.CANCEL, None

    # 2. MODIFICACIÓN / REEMPLAZO ("mejor abre Y", "en vez de eso abre Y", "cambia a Y")
    mod_match = re.match(
        r"^(?:no,\s*)?(?:mejor|en\s+vez\s+de\s+eso|más\s+bien|cambia\s+a|en\s+lugar\s+de\s+eso)\s+(?:abre\s+|pon\s+|inicia\s+)?(.+)$",
        text,
    )
    if mod_match:
        replacement = mod_match.group(1).strip()
        # Limpiar palabras residuales
        replacement = re.sub(r"^(?:abre|abrir|pon|poner|inicia|iniciar)\s+", "", replacement).strip()
        if replacement:
            return RecoveryUserIntent.MODIFY, replacement

    # Otra variante de modificación: "abre X" cuando hay un fallo previo de otra app
    open_mod_match = re.match(r"^(?:abre|inicia|lanza)\s+([a-zA-Z0-9_áéíóúÁÉÍÓÚ\s]+)$", text)
    if open_mod_match and recovery_context and recovery_context.target:
        new_target = open_mod_match.group(1).strip()
        if new_target.lower() != recovery_context.target.lower():
            return RecoveryUserIntent.MODIFY, new_target

    # 3. REINTENTO EXPLÍCITO O AFIRMATIVO
    # Expresiones: "intenta de nuevo", "otra vez", "hazlo otra vez", "reintenta", "sí"
    retry_phrases = (
        "intenta de nuevo",
        "inténtalo de nuevo",
        "intentalo de nuevo",
        "otra vez",
        "hazlo otra vez",
        "hazlo de nuevo",
        "reintenta",
        "reintentar",
        "reinténtalo",
        "reintentalo",
        "prueba de nuevo",
        "pruébalo de nuevo",
        "pruebalo de nuevo",
        "vuelve a intentarlo",
        "dale de nuevo",
        "de nuevo",
        "hazlo",
    )
    if text in retry_phrases or any(text.startswith(p) for p in retry_phrases):
        return RecoveryUserIntent.RETRY, None

    # Respuesta afirmativa ("sí", "claro", "por favor", "adelante", "dale")
    # REGLA 7: Solamente si existe explícitamente recovery_context esperando respuesta afirmativa
    affirmative_words = ("sí", "si", "claro", "por favor", "adelante", "dale", "de acuerdo", "ok", "bueno", "yes")
    if text in affirmative_words:
        if recovery_context and recovery_context.recovery_state in (
            ActionRecoveryState.RETRY_AVAILABLE,
            ActionRecoveryState.SEQUENCE_PAUSED,
        ):
            return RecoveryUserIntent.RETRY, None

    # 4. NUEVA INTENCIÓN NO RELACIONADA ("¿qué hora es?", etc.)
    return RecoveryUserIntent.UNRELATED, None


__all__ = [
    "ActionFailureCategory",
    "ActionRecoveryContext",
    "ActionRecoveryState",
    "RecoveryUserIntent",
    "build_recovery_prompt",
    "classify_failure_category",
    "classify_recovery_intent",
    "format_friendly_error",
]
