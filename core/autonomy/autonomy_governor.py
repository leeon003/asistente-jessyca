"""Gobernador Central de Autonomía (AutonomyGovernor - Etapa 16.2).

Mantiene el estado global thread-safe del Nivel de Autonomía y enforza la regla inmutable:
UNICAMENTE EL USUARIO (O ADMINISTRADOR DEL SISTEMA) PUEDE CAMBIAR EL NIVEL DE AUTONOMÍA.

Ningún actor secundario (LLM, memoria, plugin, scheduler, workflow) puede elevar privilegios.

Actores AUTORIZADOS (AUTHORIZED_ACTORS): {"user", "system_admin", "interactive_user"}
Actores DENEGADOS  (UNAUTHORIZED_ACTORS): {"llm", "plugin", "scheduler", "memory",
                                            "workflow", "assistant", "wake_word"}
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.autonomy.autonomy_decision import AutonomyDecision, AutonomyDecisionValue
from core.autonomy.autonomy_level import AutonomyLevel
from core.autonomy.autonomy_policy import (
    AutonomyConfirmationRequiredError,
    AutonomyEscalationError,
    AutonomyEvaluationContext,
    AutonomyPermissionDeniedError,
    AutonomyPolicy,
)
from core.event_bus import get_event_bus
from core.logger import get_logger

logger = get_logger("jessyca.core.autonomy.governor")


class AutonomyGovernor:
    """Gobernador central singleton thread-safe del Nivel de Autonomía de Jessyca 3.0."""

    _instance: AutonomyGovernor | None = None
    _singleton_lock: threading.Lock = threading.Lock()

    # Actores explícitamente autorizados para cambiar el nivel de autonomía
    AUTHORIZED_ACTORS: set[str] = {"user", "system_admin", "interactive_user"}

    # Actores explícitamente prohibidos — NUNCA pueden cambiar el nivel de autonomía
    UNAUTHORIZED_ACTORS: set[str] = {
        "llm",
        "plugin",
        "scheduler",
        "memory",
        "workflow",
        "assistant",
        "wake_word",
        "tool",
        "external",
    }

    def __init__(self, policy: AutonomyPolicy | None = None) -> None:
        # Nivel por defecto desde la configuración (por defecto LEVEL_3_CONFIRMATION_REQUIRED)
        self._current_level: AutonomyLevel = AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED
        self._lock: threading.RLock = threading.RLock()
        self._policy = policy or AutonomyPolicy()
        self._last_changed_by: str = "system_init"
        self._last_changed_at: datetime = datetime.now(UTC)

        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    @classmethod
    def get_instance(cls) -> AutonomyGovernor:
        """Obtiene la instancia singleton thread-safe del Gobernador de Autonomía."""
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def current_level(self) -> AutonomyLevel:
        """Obtiene el nivel de autonomía actual de forma thread-safe."""
        with self._lock:
            return self._current_level

    def set_autonomy_level(self, new_level: AutonomyLevel, actor: str = "user") -> None:
        """Establece un nuevo nivel de autonomía.

        INVARIANTE DE SEGURIDAD ABSOLUTA:
        Solo un actor humano autorizado ('user', 'system_admin') puede modificar el nivel.
        Intentos por parte de 'llm', 'plugin', 'scheduler', 'memory' o 'workflow' lanzan AutonomyEscalationError.
        """
        actor_clean = str(actor).strip().lower()

        if actor_clean not in self.AUTHORIZED_ACTORS:
            err_msg = f"[AUTONOMY ESCALATION REJECTED] El actor '{actor}' intentó cambiar el nivel de autonomía a {new_level.label}. Únicamente el usuario humano puede cambiar este nivel."
            logger.error(err_msg)

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.SECURITY_ALERT,
                    request_id=f"governor-escalation-{int(datetime.now(UTC).timestamp())}",
                    tool_name="system.autonomy_governor",
                    operation="set_autonomy_level",
                    reason=err_msg,
                    metadata={"attempted_level": new_level.label, "unauthorized_actor": actor},
                )
            )
            raise AutonomyEscalationError(err_msg)

        with self._lock:
            old_level = self._current_level
            self._current_level = new_level
            self._last_changed_by = actor_clean
            self._last_changed_at = datetime.now(UTC)

            logger.info(f"[AUTONOMY GOVERNOR] Nivel de autonomía actualizado: {old_level.label} -> {new_level.label} por '{actor_clean}'.")

            audit_meta = {
                "old_level": old_level.label,
                "new_level": new_level.label,
                "actor": actor_clean,
                "changed_at": self._last_changed_at.isoformat(),
            }

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.POLICY_EVALUATED,
                    request_id="autonomy-governor-level-change",
                    tool_name="system.autonomy_governor",
                    operation="set_autonomy_level",
                    reason=f"Nivel de autonomía cambiado a {new_level.label} por {actor_clean}.",
                    metadata=audit_meta,
                )
            )
            self.event_bus.publish("autonomy:level_changed", audit_meta)

    def evaluate_action(self, context: AutonomyEvaluationContext) -> AutonomyDecision:
        """Evalúa una acción contra la política y el nivel de autonomía activo de forma thread-safe."""
        with self._lock:
            level = self._current_level
        return self._policy.evaluate(context, level)

    def enforce_action(self, context: AutonomyEvaluationContext) -> AutonomyDecision:
        """Evalúa una acción y enforza la decisión lanzando una excepción si es rechazada o exige confirmación."""
        decision = self.evaluate_action(context)

        if decision.decision == AutonomyDecisionValue.DENY or not decision.allowed:
            if decision.requires_confirmation:
                raise AutonomyConfirmationRequiredError(
                    f"[AUTONOMY DENIED] {decision.reason} (Task ID: {context.task_id})"
                )
            raise AutonomyPermissionDeniedError(
                f"[AUTONOMY DENIED] {decision.reason} (Task ID: {context.task_id})"
            )

        if decision.requires_confirmation:
            raise AutonomyConfirmationRequiredError(
                f"[AUTONOMY CONFIRMATION REQUIRED] {decision.reason} (Task ID: {context.task_id})"
            )

        return decision

    def get_profile_for_action(
        self,
        tool_name: str,
        operation: str,
    ) -> "Any | None":
        """Obtiene el CapabilityAutonomyProfile para una acción, sin modificarlo.

        Expuesto para que el SecureExecutionPipeline y herramientas de diagnóstico
        puedan consultar el perfil de una capability sin alterar el registro.

        INVARIANTE: Este método es SÓLO LECTURA. No modifica el perfil ni el nivel de autonomía.
        """
        from core.autonomy.capability_autonomy_registry import get_capability_autonomy_registry
        registry = get_capability_autonomy_registry()
        capability_key = f"{tool_name}.{operation}".lower()
        return registry.get_profile(capability_key)

    def reset_to_default(self) -> None:
        """Restablece el nivel de autonomía al valor por defecto (LEVEL_3_CONFIRMATION_REQUIRED)."""
        with self._lock:
            self.set_autonomy_level(AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED, actor="system_admin")

    def get_status(self) -> dict[str, Any]:
        """Obtiene un resumen estructurado del estado actual del Gobernador de Autonomía."""
        with self._lock:
            return {
                "current_level": self._current_level.label,
                "level_value": self._current_level.value,
                "description": self._current_level.description,
                "allows_tool_execution": self._current_level.allows_tool_execution(),
                "last_changed_by": self._last_changed_by,
                "last_changed_at": self._last_changed_at.isoformat(),
                "authorized_actors": sorted(self.AUTHORIZED_ACTORS),
                "unauthorized_actors": sorted(self.UNAUTHORIZED_ACTORS),
            }


def get_autonomy_governor() -> AutonomyGovernor:
    """Función de conveniencia para acceder al singleton del AutonomyGovernor."""
    return AutonomyGovernor.get_instance()
