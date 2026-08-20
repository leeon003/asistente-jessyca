"""Política Central Determinista de Autonomía (AutonomyPolicy - Etapa 16.2).

INVARIANTE DE SEGURIDAD PRINCIPAL:
LLM -> REQUEST
Memory -> EVIDENCE
Plugin -> CAPABILITY
Scheduler -> TRIGGER
Workflow -> SEQUENCE
Policy -> DECISION
SecureExecutionPipeline -> EXECUTION

Ningún actor externo (LLM, memoria, plugin, scheduler, workflow) puede elevar privilegios ni alterar la decisión de Policy.

FLUJO DE EVALUACIÓN CON REGISTRO DE PERFILES (Etapa 16.2):
1. Consultar CapabilityAutonomyRegistry por perfil declarado de la capability.
2. Si hay perfil:
   a. Si current_level < profile.minimum_autonomy_level → DENY (nivel insuficiente).
   b. Usar profile.risk_level (declarado) en lugar de inferencia por nombre.
   c. Usar profile.requires_confirmation.
3. Si no hay perfil → fallback al TaskRiskClassifier (inferencia por nombre).
4. Continuar con el resto del flujo de evaluación (scheduled, plugin, CRITICAL, nivel).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.autonomy.autonomy_decision import AutonomyDecision, AutonomyDecisionValue
from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger
from core.permission_manager import PermissionManager

logger = get_logger("jessyca.core.autonomy.policy")


class TaskRiskClassifier:
    """Clasificador determinista del nivel de riesgo de acciones y tareas autónomas."""

    CRITICAL_PATTERNS: tuple[str, ...] = (
        r"cmd",
        r"powershell",
        r"windows\.shell",
        r"system\.shutdown",
        r"system\.reboot",
        r"format\.disk",
        r"registry\.delete",
        r"user\.create",
        r"privilege\.elevate",
    )

    DANGEROUS_PATTERNS: tuple[str, ...] = (
        r"file\.delete",
        r"file\.remove",
        r"process\.kill",
        r"process\.terminate",
        r"registry\.write",
        r"service\.stop",
        r"network\.route_modify",
    )

    MEDIUM_RISK_PATTERNS: tuple[str, ...] = (
        r"file\.write",
        r"file\.modify",
        r"process\.list",
        r"network\.inspect",
        r"service\.query",
    )

    LOW_RISK_PATTERNS: tuple[str, ...] = (
        r"temp\.write",
        r"log\.write",
        r"cache\.clear",
    )

    def classify_task(self, tool_name: str, operation: str, parameters: dict[str, Any] | None = None) -> TaskActionRisk:
        """Clasifica una acción/tarea en uno de los 5 niveles de riesgo formales."""
        target = f"{tool_name}.{operation}".lower()
        param_str = str(parameters or {}).lower()

        # 1. CRITICAL
        for pat in self.CRITICAL_PATTERNS:
            if re.search(pat, target) or ("format" in param_str and "c:" in param_str) or ("hklm" in param_str):
                return TaskActionRisk.CRITICAL

        # 2. DANGEROUS
        for pat in self.DANGEROUS_PATTERNS:
            if re.search(pat, target) or "delete" in target or "kill" in target:
                return TaskActionRisk.DANGEROUS

        # 3. LOW_RISK
        for pat in self.LOW_RISK_PATTERNS:
            if re.search(pat, target):
                return TaskActionRisk.LOW_RISK

        # 4. MEDIUM_RISK
        for pat in self.MEDIUM_RISK_PATTERNS:
            if re.search(pat, target) or "write" in target or "modify" in target:
                return TaskActionRisk.MEDIUM_RISK

        # 5. READ_ONLY por defecto si es consulta o lectura
        if "read" in target or "get" in target or "list" in target or "inspect" in target or "query" in target:
            return TaskActionRisk.READ_ONLY

        return TaskActionRisk.MEDIUM_RISK


class AutonomySecurityError(MCPError):
    """Error base de violaciones de política de autonomía."""

    pass


class AutonomyPermissionDeniedError(AutonomySecurityError):
    """Error emitido cuando una tarea autónoma intenta ejecutarse sin permisos suficientes."""

    pass


class AutonomyConfirmationRequiredError(AutonomySecurityError):
    """Error emitido cuando una tarea autónoma/programada requiere confirmación humana en tiempo real."""

    pass


class AutonomyPolicyError(AutonomySecurityError):
    """Error base del subsistema de política de autonomía."""

    pass


class AutonomyEscalationError(AutonomyPolicyError):
    """Error emitido cuando un componente no autorizado intenta elevar el nivel de autonomía."""

    pass


@dataclass(frozen=True)
class AutonomyEvaluationContext:
    """Contexto inmutable de evaluación de autonomía para una acción."""

    task_id: str
    tool_name: str
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    task_source: str = "user_request"  # llm_request, scheduled_task, plugin_action, wake_word
    is_scheduled: bool = False
    is_plugin: bool = False
    workflow_id: str | None = None
    requested_autonomy_level: AutonomyLevel | None = None
    user_id: str = "default_user"
    metadata: dict[str, Any] = field(default_factory=dict)


class AutonomyPolicy:
    """Evaluador determinista de política de autonomía con soporte de perfiles declarados.

    Aplica rigurosamente la regla de jerarquía de autoridad:
    Policy -> DECISION.

    Con CapabilityAutonomyRegistry integrado (Etapa 16.2):
    - Las capabilities con perfil declarado usan minimum_autonomy_level y risk_level del perfil.
    - Las capabilities sin perfil hacen fallback al TaskRiskClassifier por nombre.
    """

    def __init__(
        self,
        permission_manager: PermissionManager | None = None,
        risk_classifier: TaskRiskClassifier | None = None,
        capability_registry: Any | None = None,
    ) -> None:
        self.permission_manager = permission_manager or PermissionManager()
        self.classifier = risk_classifier or TaskRiskClassifier()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()
        # Importación tardía para evitar ciclos de importación
        if capability_registry is not None:
            self._capability_registry = capability_registry
        else:
            from core.autonomy.capability_autonomy_registry import get_capability_autonomy_registry
            self._capability_registry = get_capability_autonomy_registry()

    def evaluate(
        self,
        context: AutonomyEvaluationContext,
        current_level: AutonomyLevel,
    ) -> AutonomyDecision:
        """Evalúa la solicitud de acción en función del nivel de autonomía actual y los controles de seguridad.

        Flujo con perfiles declarados (Etapa 16.2):
        1. Detección de escalation.
        2. Consulta al CapabilityAutonomyRegistry.
           - Si hay perfil → nivel mínimo y riesgo declarados.
           - Si current_level < minimum_autonomy_level → DENY inmediato.
        3. Fallback al TaskRiskClassifier si no hay perfil.
        4. Evaluación por nivel de autonomía, riesgo y confirmación.
        """
        # 1. Detección de Inyección / Escalado de Autonomía
        self._detect_escalation_attempts(context)

        # 2. Consultar CapabilityAutonomyRegistry por perfil declarado
        capability_key = f"{context.tool_name}.{context.operation}".lower()
        profile = self._capability_registry.get_profile(capability_key)
        profile_used = profile is not None
        profile_confirmation_required: bool | None = None

        if profile is not None:
            # 2a. Verificar nivel mínimo de autonomía declarado
            if not profile.is_level_sufficient(current_level):
                return self._create_decision(
                    decision_val=AutonomyDecisionValue.DENY,
                    current_level=current_level,
                    risk_level=profile.risk_level,
                    allowed=False,
                    requires_confirmation=False,
                    reason=(
                        f"[LEVEL INSUFFICIENT] La capability '{capability_key}' requiere nivel mínimo "
                        f"{profile.minimum_autonomy_level.label} (actual: {current_level.label}). "
                        f"El nivel de autonomía debe ser elevado por el usuario para ejecutar esta acción."
                    ),
                    context=context,
                    extra_metadata={"profile_used": True, "minimum_level": profile.minimum_autonomy_level.label},
                )
            # 2b. Usar riesgo y confirmación declarados del perfil
            risk_level = profile.risk_level
            profile_confirmation_required = profile.is_confirmation_required_for_level(current_level)
            logger.debug(
                f"[AUTONOMY POLICY] Perfil declarado encontrado para '{capability_key}': "
                f"risk={risk_level}, confirmation={profile_confirmation_required}"
            )
        else:
            # 3. Fallback: Clasificación determinista por nombre de herramienta
            risk_level = self.classifier.classify_task(
                tool_name=context.tool_name,
                operation=context.operation,
                parameters=context.parameters,
            )
            logger.debug(
                f"[AUTONOMY POLICY] Sin perfil declarado para '{capability_key}'. "
                f"Fallback a clasificador por nombre: risk={risk_level}"
            )

        # 4. Evaluación de Nivel 0 (OBSERVE) y Nivel 1 (SUGGEST)
        if current_level == AutonomyLevel.LEVEL_0_OBSERVE:
            if risk_level != TaskActionRisk.READ_ONLY:
                return self._create_decision(
                    decision_val=AutonomyDecisionValue.DENY,
                    current_level=current_level,
                    risk_level=risk_level,
                    allowed=False,
                    requires_confirmation=False,
                    reason=f"[LEVEL_0_OBSERVE] Ejecución de herramienta '{context.tool_name}' denegada. Solo se permite observación y diagnóstico.",
                    context=context,
                    extra_metadata={"profile_used": profile_used},
                )
            return self._create_decision(
                decision_val=AutonomyDecisionValue.ALLOW,
                current_level=current_level,
                risk_level=risk_level,
                allowed=True,
                requires_confirmation=False,
                reason="Acción de lectura/diagnóstico autorizada en Modo Observador.",
                context=context,
                extra_metadata={"profile_used": profile_used},
            )

        if current_level == AutonomyLevel.LEVEL_1_SUGGEST:
            return self._create_decision(
                decision_val=AutonomyDecisionValue.REQUIRE_REVIEW,
                current_level=current_level,
                risk_level=risk_level,
                allowed=False,
                requires_confirmation=True,
                reason=f"[LEVEL_1_SUGGEST] Acción '{context.tool_name}' no ejecutada. Se genera sugerencia/propuesta para revisión.",
                context=context,
                extra_metadata={"profile_used": profile_used},
            )

        # 5. Evaluación para Tareas Programadas (Scheduled Tasks)
        # REGLA INMUTABLE: scheduled_task != user_authorization
        if context.is_scheduled and risk_level in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL):
            return self._create_decision(
                decision_val=AutonomyDecisionValue.DENY,
                current_level=current_level,
                risk_level=risk_level,
                allowed=False,
                requires_confirmation=True,
                reason=f"[SCHEDULED TASK DENIED] Tarea programada involucra acción {risk_level.value} y requiere confirmación humana activa en tiempo real. CERO BYPASS.",
                context=context,
                extra_metadata={"profile_used": profile_used},
            )

        # 6. Evaluación para Plugins
        # REGLA INMUTABLE: Plugin -> CAPABILITY (cero auto-elevación)
        if context.is_plugin and risk_level in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL):
            return self._create_decision(
                decision_val=AutonomyDecisionValue.DENY,
                current_level=current_level,
                risk_level=risk_level,
                allowed=False,
                requires_confirmation=True,
                reason=f"[PLUGIN ACTION DENIED] Plugin intentó ejecutar acción {risk_level.value}. Exige confirmación interactiva humana.",
                context=context,
                extra_metadata={"profile_used": profile_used},
            )

        # 7. Evaluación de Riesgo CRITICAL (CERO AUTO-EJECUCIÓN — perfil declarado o inferido)
        if risk_level == TaskActionRisk.CRITICAL:
            return self._create_decision(
                decision_val=AutonomyDecisionValue.REQUIRE_CONFIRMATION,
                current_level=current_level,
                risk_level=risk_level,
                allowed=False,
                requires_confirmation=True,
                reason="Acción de nivel CRITICAL exige confirmación humana obligatoria en tiempo real.",
                context=context,
                extra_metadata={"profile_used": profile_used},
            )

        # 8. Si el perfil declarado exige confirmación explícita, respetar esa declaración
        if profile_confirmation_required is True:
            return self._create_decision(
                decision_val=AutonomyDecisionValue.REQUIRE_CONFIRMATION,
                current_level=current_level,
                risk_level=risk_level,
                allowed=False,
                requires_confirmation=True,
                reason=(
                    f"[PROFILE CONFIRMATION REQUIRED] El perfil declarado de '{capability_key}' "
                    f"exige confirmación humana ({profile.requires_confirmation if profile else 'n/a'})."
                ),
                context=context,
                extra_metadata={"profile_used": True, "confirmation_source": "declared_profile"},
            )

        # 9. Evaluación de acuerdo con el Nivel de Autonomía (LEVEL_2, LEVEL_3, LEVEL_4)
        if current_level.is_risk_allowed_auto(risk_level):
            return self._create_decision(
                decision_val=AutonomyDecisionValue.ALLOW,
                current_level=current_level,
                risk_level=risk_level,
                allowed=True,
                requires_confirmation=False,
                reason=f"Acción {risk_level.value} autorizada autónomamente bajo {current_level.label}.",
                context=context,
                extra_metadata={"profile_used": profile_used},
            )

        # Si requiere confirmación por nivel de autonomía
        return self._create_decision(
            decision_val=AutonomyDecisionValue.REQUIRE_CONFIRMATION,
            current_level=current_level,
            risk_level=risk_level,
            allowed=False,
            requires_confirmation=True,
            reason=f"Acción {risk_level.value} excede el umbral automático de {current_level.label} y requiere confirmación humana.",
            context=context,
            extra_metadata={"profile_used": profile_used},
        )

    def _detect_escalation_attempts(self, context: AutonomyEvaluationContext) -> None:
        """Inspecciona los parámetros y metadatos en busca de intentos no autorizados de elevar la autonomía."""
        params_str = str(context.parameters).lower()
        meta_str = str(context.metadata).lower()

        forbidden_escalation_keys = (
            "override_autonomy",
            "grant_full_autonomy",
            "bypass_confirmation",
            "elevate_privileges",
            "set_autonomy_level",
            "bypass_autonomy",
        )

        for key in forbidden_escalation_keys:
            if key in params_str or key in meta_str:
                err_msg = f"[AUTONOMY ESCALATION ATTEMPT] Intento de elevación de privilegios detectado ('{key}') desde fuente '{context.task_source}'."
                logger.error(err_msg)
                self.audit_logger.log_audit_event(
                    AuditEvent(
                        event_type=AuditEventType.SECURITY_ALERT,
                        request_id=f"escalation-alert-{context.task_id[:8]}",
                        tool_name=context.tool_name,
                        operation=context.operation,
                        reason=err_msg,
                        metadata={"task_id": context.task_id, "source": context.task_source},
                    )
                )
                raise AutonomyEscalationError(err_msg)

    def _create_decision(
        self,
        decision_val: AutonomyDecisionValue,
        current_level: AutonomyLevel,
        risk_level: TaskActionRisk,
        allowed: bool,
        requires_confirmation: bool,
        reason: str,
        context: AutonomyEvaluationContext,
        extra_metadata: dict[str, Any] | None = None,
    ) -> AutonomyDecision:
        """Construye y audita la decisión inmutable con metadata extendida (Etapa 16.2)."""
        base_meta: dict[str, Any] = {
            "task_source": context.task_source,
            "is_scheduled": context.is_scheduled,
            "is_plugin": context.is_plugin,
            "workflow_id": context.workflow_id,
        }
        if extra_metadata:
            base_meta.update(extra_metadata)

        decision = AutonomyDecision(
            decision=decision_val,
            autonomy_level=current_level,
            risk_level=risk_level,
            allowed=allowed,
            requires_confirmation=requires_confirmation,
            reason=reason,
            task_id=context.task_id,
            tool_name=context.tool_name,
            operation=context.operation,
            metadata=base_meta,
        )

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POLICY_EVALUATED if allowed else AuditEventType.EXECUTION_DENIED,
                request_id=f"autonomy-dec-{context.task_id[:8]}",
                tool_name=context.tool_name,
                operation=context.operation,
                reason=reason,
                metadata=decision.to_dict(),
            )
        )
        self.event_bus.publish("autonomy:decision_evaluated", decision.to_dict())
        return decision
