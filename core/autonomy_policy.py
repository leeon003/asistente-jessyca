"""Subsistema de Política de Autonomía de Tareas (AutonomyPolicy - Etapa 13.0).

GARANTÍA ABSOLUTA DE SEGURIDAD EN ETAPA 13.0:
1. REGLA FUNDAMENTAL: scheduled_task != user_authorization.
2. Una tarea programada NUNCA obtiene más autoridad por haber sido previamente configurada.
3. Clasificación estricta de acciones: READ_ONLY, LOW_RISK, MEDIUM_RISK, DANGEROUS, CRITICAL.
4. Flujo obligatorio:
   Task -> TaskRiskClassifier -> PermissionManager -> SecureExecutionPipeline -> Execution -> AuditLogger.
5. Acciones DANGEROUS y CRITICAL exigen confirmación humana obligatoria. CERO BYPASS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger
from core.permission_manager import PermissionDecision, PermissionManager

logger = get_logger("jessyca.core.autonomy")


class TaskActionRisk(StrEnum):
    """Clasificación formal de nivel de riesgo para acciones y tareas autónomas."""

    READ_ONLY = "READ_ONLY"
    LOW_RISK = "LOW_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    DANGEROUS = "DANGEROUS"
    CRITICAL = "CRITICAL"


class AutonomySecurityError(MCPError):
    """Error base de violaciones de política de autonomía."""

    pass


class AutonomyPermissionDeniedError(AutonomySecurityError):
    """Error emitido cuando una tarea autónoma intenta ejecutarse sin permisos suficientes."""

    pass


class AutonomyConfirmationRequiredError(AutonomySecurityError):
    """Error emitido cuando una tarea autónoma/programada requiere confirmación humana en tiempo real."""

    pass


@dataclass(frozen=True)
class AutonomousTaskRequest:
    """Solicitud inmutable de ejecución de tarea autónoma o programada."""

    task_id: str
    tool_name: str
    operation: str
    is_scheduled: bool = False
    is_wake_word: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)
    user_id: str = "default_user"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.task_id or not isinstance(self.task_id, str):
            raise ValueError("El task_id debe ser una cadena válida no vacía.")
        if not self.tool_name or not isinstance(self.tool_name, str):
            raise ValueError("El tool_name debe ser una cadena válida no vacía.")


@dataclass(frozen=True)
class AutonomyEvaluationResult:
    """Resultado inmutable de la evaluación de la política de autonomía."""

    task_id: str
    risk_level: TaskActionRisk
    allowed: bool
    requires_confirmation: bool
    reason: str
    permission_decision: PermissionDecision
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado a un diccionario seguro para auditoría (sin parámetros crudos)."""
        return {
            "task_id": self.task_id,
            "risk_level": str(self.risk_level),
            "allowed": self.allowed,
            "requires_confirmation": self.requires_confirmation,
            "reason": self.reason,
            "permission_decision": str(self.permission_decision),
            "evaluated_at": self.evaluated_at.isoformat(),
        }


class TaskRiskClassifier:
    """Clasificador determinista del nivel de riesgo de acciones y tareas autónomas."""

    # Mapeo de patrones de herramientas/operaciones a niveles de riesgo
    CRITICAL_PATTERNS: tuple[str, ...] = (
        r"cmd\.",
        r"powershell\.",
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
            if re.search(pat, target) or ("format" in param_str and "c:" in param_str):
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



class ScheduledActionPolicy:
    """Política explícita para tareas programadas (Scheduled Tasks).

    REGLA INCOMPROMETIBLE: scheduled_task != user_authorization.
    Una tarea programada NUNCA obtiene mayor autoridad ni se le otorga bypass de seguridad.
    """

    def __init__(self, classifier: TaskRiskClassifier | None = None) -> None:
        self.classifier = classifier or TaskRiskClassifier()

    def evaluate_scheduled_action(
        self,
        request: AutonomousTaskRequest,
    ) -> tuple[bool, str, bool]:
        """Evalúa si una tarea programada puede proceder o requiere confirmación.

        Retorna: (allowed, reason, requires_confirmation)
        - READ_ONLY / LOW_RISK: Permitido autónomamente.
        - MEDIUM_RISK: Permitido si la política lo autoriza.
        - DANGEROUS / CRITICAL: NUNCA se autorizan automáticamente por ser programadas. Requieren confirmación activa.
        """
        risk = self.classifier.classify_task(request.tool_name, request.operation, request.parameters)

        if risk in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL):
            return (
                False,
                f"La tarea programada '{request.task_id}' involucra una acción {risk.value} y requiere confirmación humana activa en tiempo real. CERO BYPASS.",
                True,
            )

        if risk == TaskActionRisk.MEDIUM_RISK:
            return (
                True,
                f"La tarea programada '{request.task_id}' de nivel MEDIUM_RISK es evaluada bajo controles estándar.",
                False,
            )

        return (
            True,
            f"La tarea programada '{request.task_id}' ({risk.value}) está permitida autónomamente.",
            False,
        )


class AutonomyPolicy:
    """Administrador Central de la Política de Autonomía de Tareas (Etapa 13.0).

    ENFORZA EL PIPELINE DE EJECUCIÓN SEGURA:
    Task -> TaskRiskClassifier -> ScheduledActionPolicy -> PermissionManager -> AuditLogger -> Execution.
    """

    def __init__(
        self,
        permission_manager: PermissionManager | None = None,
        risk_classifier: TaskRiskClassifier | None = None,
        scheduled_policy: ScheduledActionPolicy | None = None,
    ) -> None:
        self.permission_manager = permission_manager or PermissionManager()

        self.classifier = risk_classifier or TaskRiskClassifier()
        self.scheduled_policy = scheduled_policy or ScheduledActionPolicy(self.classifier)
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def evaluate_task(self, request: AutonomousTaskRequest) -> AutonomyEvaluationResult:
        """Evalúa una solicitud de tarea autónoma o programada aplicando el flujo riguroso de seguridad."""
        # 1. Clasificación del Nivel de Riesgo
        risk_level = self.classifier.classify_task(
            tool_name=request.tool_name,
            operation=request.operation,
            parameters=request.parameters,
        )

        # 2. Evaluación de Política para Tareas Programadas (scheduled_task != user_authorization)
        if request.is_scheduled:
            sched_allowed, sched_reason, sched_req_conf = self.scheduled_policy.evaluate_scheduled_action(request)
            if not sched_allowed:
                result = AutonomyEvaluationResult(
                    task_id=request.task_id,
                    risk_level=risk_level,
                    allowed=False,
                    requires_confirmation=sched_req_conf,
                    reason=sched_reason,
                    permission_decision=PermissionDecision.DENY,
                )
                self._log_autonomy_audit(request, result)
                return result

        # 3. Evaluación en PermissionManager
        from core.permission_manager import PermissionRequest
        from core.risk_engine import RiskAssessment
        from core.security import RiskLevel
        from core.security_architecture import SecurityContext, ToolSecurityMetadata



        risk_map = {
            TaskActionRisk.READ_ONLY: RiskLevel.READ_ONLY,
            TaskActionRisk.LOW_RISK: RiskLevel.SAFE,
            TaskActionRisk.MEDIUM_RISK: RiskLevel.WARNING,
            TaskActionRisk.DANGEROUS: RiskLevel.DANGEROUS,
            TaskActionRisk.CRITICAL: RiskLevel.CRITICAL,
        }
        r_level_enum = risk_map.get(risk_level, RiskLevel.WARNING)


        risk_assessment = RiskAssessment(
            risk_level=r_level_enum,
            score=2,
            reason=f"Autonomy policy risk level: {risk_level.value}",
            risk_factors=set(),
        )


        perm_req = PermissionRequest(
            context=SecurityContext(user=request.user_id, tool_name=request.tool_name, parameters=request.parameters),
            metadata=ToolSecurityMetadata(tool_name=request.tool_name, category=request.operation),


            risk_assessment=risk_assessment,
            tool_name=request.tool_name,
            operation=request.operation,
            parameters=request.parameters,
        )

        perm_result = self.permission_manager.evaluate_permission(perm_req)

        allowed = perm_result.is_allowed
        requires_confirmation = (perm_result.decision == PermissionDecision.REQUIRE_CONFIRMATION) or (
            risk_level in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL)
        )
        reason = perm_result.reason


        if risk_level in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL) and not requires_confirmation:
            requires_confirmation = True

        if requires_confirmation and request.is_scheduled:
            allowed = False
            reason = f"Acción programada de nivel {risk_level.value} denegada por requerir confirmación humana interactiva."

        final_result = AutonomyEvaluationResult(
            task_id=request.task_id,
            risk_level=risk_level,
            allowed=allowed,
            requires_confirmation=requires_confirmation,
            reason=reason,
            permission_decision=perm_result.decision,
        )

        self._log_autonomy_audit(request, final_result)
        return final_result

    def enforce_task_execution(self, request: AutonomousTaskRequest) -> AutonomyEvaluationResult:
        """Enforza la ejecución del pipeline seguro de autonomía, emitiendo excepciones en caso de denegación."""
        res = self.evaluate_task(request)

        if res.requires_confirmation and not res.allowed:
            raise AutonomyConfirmationRequiredError(
                f"[AUTONOMY POLICY DENIAL] {res.reason} (Task ID: {request.task_id})"
            )

        if not res.allowed:
            raise AutonomyPermissionDeniedError(
                f"[AUTONOMY POLICY DENIAL] {res.reason} (Task ID: {request.task_id})"
            )

        return res

    def _log_autonomy_audit(self, request: AutonomousTaskRequest, result: AutonomyEvaluationResult) -> None:
        """Registra el evento de auditoría sanitizado sin parámetros de datos sensibles."""
        audit_meta = result.to_dict()
        audit_meta["is_scheduled"] = request.is_scheduled
        audit_meta["is_wake_word"] = request.is_wake_word

        event_type = AuditEventType.POLICY_EVALUATED
        if result.requires_confirmation:
            event_type = AuditEventType.CONFIRMATION_REQUESTED
        elif not result.allowed:
            event_type = AuditEventType.EXECUTION_DENIED

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=event_type,
                request_id=f"autonomy-{request.task_id[:8]}",
                tool_name=request.tool_name,
                operation=request.operation,
                duration_ms=0.0,
                reason=result.reason,
                metadata=audit_meta,
            )
        )
        self.event_bus.publish("autonomy:evaluated", audit_meta)
