"""Gobernador Central de Autonomía (AutonomyGovernor - Etapas 16.2 y 20.2).

Mantiene el estado global thread-safe del Nivel de Autonomía y enforza la regla inmutable:
UNICAMENTE EL USUARIO (O ADMINISTRADOR DEL SISTEMA) PUEDE CAMBIAR EL NIVEL DE AUTONOMÍA.

Controla cuánto puede hacer JESSYCA dentro de una tarea evaluando:
  - Autonomy Level (Niveles 0 a 4)
  - Risk Level (READ_ONLY, LOW_RISK, MEDIUM_RISK, DANGEROUS, CRITICAL)
  - Capability (Perfil formal inmutable)
  - Permission (Permisos efectivos)
  - Confirmation (Obligatoriedad individual en DANGEROUS/CRITICAL)
  - Reversibility (REVERSIBLE, PARTIALLY_REVERSIBLE, IRREVERSIBLE)
  - Task Budget, Time Budget, Tool Budget

Decisiones formales:
  ALLOW | DENY | REQUIRE_CONFIRMATION | REQUIRE_REVIEW | STOP
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.autonomy.autonomy_decision import AutonomyDecision, AutonomyDecisionValue
from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk
from core.autonomy.autonomy_policy import (
    AutonomyConfirmationRequiredError,
    AutonomyEscalationError,
    AutonomyEvaluationContext,
    AutonomyPermissionDeniedError,
    AutonomyPolicy,
    TaskRiskClassifier,
)
from core.event_bus import get_event_bus
from core.logger import get_logger

logger = get_logger("jessyca.core.autonomy.governor")


class AutonomyGovernor:
    """Gobernador central singleton thread-safe del Nivel de Autonomía y Gobernanza de Tareas de JESSYCA 3.0."""

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
        self._current_level: AutonomyLevel = AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED
        self._lock: threading.RLock = threading.RLock()
        self._policy = policy or AutonomyPolicy()
        self._classifier = TaskRiskClassifier()
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

    @property
    def policy(self) -> AutonomyPolicy:
        """Obtiene la política de autonomía asociada."""
        return self._policy

    def set_autonomy_level(self, new_level: AutonomyLevel, actor: str = "user") -> None:
        """Establece un nuevo nivel de autonomía.

        INVARIANTE DE SEGURIDAD ABSOLUTA:
        Solo un actor humano autorizado ('user', 'system_admin') puede modificar el nivel.
        Intentos por parte de 'llm', 'plugin', 'scheduler', 'memory' o 'workflow' lanzan AutonomyEscalationError.
        """
        actor_clean = str(actor).strip().lower()

        if actor_clean not in self.AUTHORIZED_ACTORS:
            err_msg = (
                f"[AUTONOMY ESCALATION REJECTED] El actor '{actor}' intentó cambiar el nivel de autonomía a "
                f"{new_level.label}. Únicamente el usuario humano puede cambiar este nivel."
            )
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

            logger.info(
                f"[AUTONOMY GOVERNOR] Nivel de autonomía actualizado: {old_level.label} -> {new_level.label} por '{actor_clean}'."
            )

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

    def govern_action(
        self,
        tool_name: str,
        operation: str,
        task_id: str = "default_task",
        parameters: dict[str, Any] | None = None,
        task_budget: Any | None = None,
        time_elapsed: float = 0.0,
        tools_count: int = 0,
        is_confirmed: bool = False,
        task_source: str = "interactive",
        workflow_context: dict[str, Any] | None = None,
        scheduler_context: dict[str, Any] | None = None,
        plugin_context: dict[str, Any] | None = None,
    ) -> AutonomyDecision:
        """Controla exhaustivamente cuánto puede hacer JESSYCA dentro de una tarea (Etapa 20.2).

        Evalúa:
          - Niveles de autonomía y riesgo
          - Presupuestos de tarea, tiempo y herramientas
          - Reversibilidad y obligatoriedad de confirmación humana
          - Contextos de scheduler, plugin y workflow

        Returns:
          AutonomyDecision: ALLOW | DENY | REQUIRE_CONFIRMATION | REQUIRE_REVIEW | STOP
        """
        with self._lock:
            current_lvl = self._current_level

        cap_key = f"{tool_name}.{operation}".lower()
        profile = self.get_profile_for_action(tool_name, operation)
        risk = profile.risk_level if profile else self._classifier.classify_task(tool_name, operation, parameters)
        reversibility = profile.reversibility.value if profile and hasattr(profile.reversibility, "value") else "UNKNOWN"
        requires_conf_profile = (profile.requires_confirmation.value != "NEVER") if profile else (risk in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL))

        decision_val = AutonomyDecisionValue.DENY
        allowed = False
        requires_confirmation = False
        reason = ""

        # ── 1. EVALUACIÓN DE PRESUPUESTOS (Task Budget, Time Budget, Tool Budget) ──
        if task_budget is not None:
            max_timeout = getattr(task_budget, "global_timeout_seconds", 60.0)
            max_tools = getattr(task_budget, "max_tool_executions", 15)
            risk_ceiling = getattr(task_budget, "risk_ceiling", TaskActionRisk.CRITICAL)

            if time_elapsed >= max_timeout:
                return self._build_decision(
                    decision=AutonomyDecisionValue.STOP,
                    level=current_lvl,
                    risk=risk,
                    allowed=False,
                    req_conf=False,
                    reason=f"Presupuesto de tiempo agotado ({time_elapsed:.2f}s >= {max_timeout:.2f}s).",
                    tool_name=tool_name,
                    operation=operation,
                    task_id=task_id,
                    metadata={"time_elapsed": time_elapsed, "timeout": max_timeout, "budget_breach": "timeout"},
                )

            if tools_count >= max_tools:
                return self._build_decision(
                    decision=AutonomyDecisionValue.STOP,
                    level=current_lvl,
                    risk=risk,
                    allowed=False,
                    req_conf=False,
                    reason=f"Presupuesto de herramientas agotado ({tools_count} >= {max_tools}).",
                    tool_name=tool_name,
                    operation=operation,
                    task_id=task_id,
                    metadata={"tools_count": tools_count, "max_tools": max_tools, "budget_breach": "tools"},
                )

            # Techo de riesgo
            risk_hierarchy = {
                TaskActionRisk.READ_ONLY: 0,
                TaskActionRisk.LOW_RISK: 1,
                TaskActionRisk.MEDIUM_RISK: 2,
                TaskActionRisk.DANGEROUS: 3,
                TaskActionRisk.CRITICAL: 4,
            }
            if risk_hierarchy.get(risk, 0) > risk_hierarchy.get(risk_ceiling, 4):
                return self._build_decision(
                    decision=AutonomyDecisionValue.DENY,
                    level=current_lvl,
                    risk=risk,
                    allowed=False,
                    req_conf=False,
                    reason=f"Riesgo de la acción ({risk.value}) supera el techo de riesgo permitido ({risk_ceiling.value}).",
                    tool_name=tool_name,
                    operation=operation,
                    task_id=task_id,
                    metadata={"risk_ceiling": risk_ceiling.value, "declared_risk": risk.value},
                )

        # ── 2. EVALUACIÓN SEGÚN NIVEL DE AUTONOMÍA ACTIVO ──
        if current_lvl == AutonomyLevel.LEVEL_0_OBSERVE:
            if risk == TaskActionRisk.READ_ONLY:
                decision_val = AutonomyDecisionValue.ALLOW
                allowed = True
                reason = "Nivel 0 (OBSERVE): Lectura e inspección permitida."
            else:
                decision_val = AutonomyDecisionValue.DENY
                allowed = False
                reason = f"Nivel 0 (OBSERVE): Prohibida la ejecución de acciones con riesgo '{risk.value}'."

        elif current_lvl == AutonomyLevel.LEVEL_1_SUGGEST:
            if risk == TaskActionRisk.READ_ONLY:
                decision_val = AutonomyDecisionValue.ALLOW
                allowed = True
                reason = "Nivel 1 (SUGGEST): Lectura permitida para generar sugerencias."
            else:
                decision_val = AutonomyDecisionValue.REQUIRE_REVIEW
                allowed = False
                reason = f"Nivel 1 (SUGGEST): Acción '{cap_key}' requiere revisión humana previa antes de ejecutar."

        elif current_lvl == AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION:
            if risk in (TaskActionRisk.READ_ONLY, TaskActionRisk.LOW_RISK):
                decision_val = AutonomyDecisionValue.ALLOW
                allowed = True
                reason = f"Nivel 2: Ejecución automática de bajo riesgo permitida ({risk.value})."
            elif risk == TaskActionRisk.MEDIUM_RISK:
                if is_confirmed:
                    decision_val = AutonomyDecisionValue.ALLOW
                    allowed = True
                    reason = "Nivel 2: Acción MEDIUM_RISK ejecutada con confirmación."
                else:
                    decision_val = AutonomyDecisionValue.REQUIRE_CONFIRMATION
                    requires_confirmation = True
                    reason = "Nivel 2: Acción MEDIUM_RISK requiere confirmación del usuario."
            else:
                # DANGEROUS / CRITICAL
                if is_confirmed:
                    decision_val = AutonomyDecisionValue.ALLOW
                    allowed = True
                    reason = f"Nivel 2: Acción {risk.value} ejecutada con confirmación explícita."
                else:
                    decision_val = AutonomyDecisionValue.REQUIRE_CONFIRMATION
                    requires_confirmation = True
                    reason = f"Nivel 2: Acción {risk.value} requiere confirmación explícita del usuario."

        elif current_lvl == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED:
            if risk in (TaskActionRisk.READ_ONLY, TaskActionRisk.LOW_RISK):
                decision_val = AutonomyDecisionValue.ALLOW
                allowed = True
                reason = f"Nivel 3: Ejecución automática permitida ({risk.value})."
            elif risk == TaskActionRisk.MEDIUM_RISK:
                if not requires_conf_profile:
                    decision_val = AutonomyDecisionValue.ALLOW
                    allowed = True
                    reason = "Nivel 3: Acción MEDIUM_RISK permitida por perfil."
                elif is_confirmed:
                    decision_val = AutonomyDecisionValue.ALLOW
                    allowed = True
                    reason = "Nivel 3: Acción MEDIUM_RISK confirmada por el usuario."
                else:
                    decision_val = AutonomyDecisionValue.REQUIRE_CONFIRMATION
                    requires_confirmation = True
                    reason = "Nivel 3: Acción MEDIUM_RISK requiere confirmación."
            else:
                # DANGEROUS / CRITICAL
                if is_confirmed:
                    decision_val = AutonomyDecisionValue.ALLOW
                    allowed = True
                    reason = f"Nivel 3: Acción {risk.value} autorizada tras confirmación obligatoria."
                else:
                    decision_val = AutonomyDecisionValue.REQUIRE_CONFIRMATION
                    requires_confirmation = True
                    reason = f"Nivel 3: Acción {risk.value} exige confirmación humana obligatoria."

        elif current_lvl == AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY:
            if risk == TaskActionRisk.CRITICAL:
                # CRITICAL siempre exige confirmación individual incluso en Nivel 4
                if is_confirmed:
                    decision_val = AutonomyDecisionValue.ALLOW
                    allowed = True
                    reason = "Nivel 4: Acción CRITICAL ejecutada tras confirmación individual."
                else:
                    decision_val = AutonomyDecisionValue.REQUIRE_CONFIRMATION
                    requires_confirmation = True
                    reason = "Nivel 4: Acciones CRITICAL exigen confirmación individual obligatoria."
            else:
                decision_val = AutonomyDecisionValue.ALLOW
                allowed = True
                reason = f"Nivel 4: Ejecución supervisada de {risk.value} permitida."

        # ── 3. REGLAS CONTEXTUALES ESTRICTAS (SCHEDULER & PLUGIN) ──
        if (scheduler_context is not None or task_source == "scheduled") and risk in (
            TaskActionRisk.DANGEROUS,
            TaskActionRisk.CRITICAL,
        ):
            decision_val = AutonomyDecisionValue.DENY
            allowed = False
            requires_confirmation = False
            reason = f"Operación de alto riesgo ({risk.value}) prohibida en tareas programadas desatendidas."

        if (plugin_context is not None or task_source == "plugin") and (
            profile and profile.category != "plugin" and risk in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL)
        ):
            decision_val = AutonomyDecisionValue.DENY
            allowed = False
            requires_confirmation = False
            reason = f"Operación de alto riesgo ({risk.value}) bloqueada fuera de los límites del plugin."

        return self._build_decision(
            decision=decision_val,
            level=current_lvl,
            risk=risk,
            allowed=allowed,
            req_conf=requires_confirmation,
            reason=reason,
            tool_name=tool_name,
            operation=operation,
            task_id=task_id,
            metadata={
                "reversibility": reversibility,
                "task_source": task_source,
                "is_confirmed": is_confirmed,
                "tools_count": tools_count,
                "time_elapsed": round(time_elapsed, 3),
            },
        )

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
    ) -> Any | None:
        """Obtiene el CapabilityAutonomyProfile para una acción en modo sólo lectura."""
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

    def _build_decision(
        self,
        decision: AutonomyDecisionValue,
        level: AutonomyLevel,
        risk: TaskActionRisk,
        allowed: bool,
        req_conf: bool,
        reason: str,
        tool_name: str,
        operation: str,
        task_id: str,
        metadata: dict[str, Any],
    ) -> AutonomyDecision:
        """Construye y audita la decisión inmutable del Gobernador."""
        full_meta = dict(metadata)
        full_meta.update({
            "governor_level": level.label,
            "governor_risk": risk.value,
            "decision_enum": decision.value,
        })

        dec = AutonomyDecision(
            decision=decision,
            autonomy_level=level,
            risk_level=risk,
            allowed=allowed,
            requires_confirmation=req_conf,
            reason=reason,
            task_id=task_id,
            tool_name=tool_name,
            operation=operation,
            metadata=full_meta,
        )

        # Registro en el AuditLogger
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POLICY_EVALUATED,
                request_id=f"gov-{task_id}",
                tool_name=tool_name,
                operation=operation,
                duration_ms=0.0,
                reason=reason,
                metadata=full_meta,
            )
        )
        return dec


def get_autonomy_governor() -> AutonomyGovernor:
    """Función de conveniencia para acceder al singleton del AutonomyGovernor."""
    return AutonomyGovernor.get_instance()
