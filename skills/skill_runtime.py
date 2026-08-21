"""Entorno de ejecución y runtime seguro para Skills (skill_runtime.py - Fase 28.4).

Ejecuta el ciclo de vida gobernado de una Skill con:
1. Creación de contexto tipado (SkillContext).
2. Control estricto de Timeout con aislamiento de hilos.
3. Control y chequeo de Cancelación (CancellationToken).
4. Control de Presupuesto (AgentBudget / AutonomyPolicy).
5. Prevalencia de Parada de Emergencia (EmergencyStopManager).
6. Captura, aislamiento de excepciones y emisión de SkillResult estructurado.
"""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any

from core.cancellation import CancellationToken
from core.control_plane.models import AgentBudget
from core.emergency_stop import EmergencyStopManager
from core.logger import get_logger
from core.permission_manager import (
    PermissionDecision,
    PermissionManager,
)
from core.risk_engine import RiskEngine
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillContext,
    SkillResult,
    SkillStatus,
)

logger = get_logger("jessyca.skills.runtime")


class SkillRuntime:
    """Runtime seguro de ejecución, contención y ciclo de vida de Skills de JESSYCA."""

    def __init__(
        self,
        risk_engine: RiskEngine | None = None,
        permission_manager: PermissionManager | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.risk_engine = risk_engine or RiskEngine()
        self.permission_manager = permission_manager or PermissionManager()
        self.emergency_stop = emergency_stop or EmergencyStopManager.get_instance()

    def create_context(
        self,
        skill_id: str,
        intent: str = "",
        parameters: dict[str, Any] | None = None,
        timeout_seconds: float = 60.0,
        cancellation_token: CancellationToken | None = None,
        session_id: str = "default_session",
        user: str = "user",
        metadata: dict[str, Any] | None = None,
    ) -> SkillContext:
        """Helper para la creación formal y estructurada de un SkillContext."""
        return SkillContext(
            skill_id=skill_id,
            intent=intent or f"execute_{skill_id}",
            parameters=parameters or {},
            timeout_seconds=timeout_seconds,
            cancellation_token=cancellation_token,
            session_id=session_id,
            user=user,
            metadata=metadata or {},
        )

    def execute_skill(
        self,
        skill: BaseSkill,
        context: SkillContext,
        budget: AgentBudget | None = None,
    ) -> SkillResult:
        """Ejecuta una Skill bajo gobierno de seguridad, límites de presupuesto, timeout y cancelación."""
        start_time = time.perf_counter()

        # 1. Comprobación inmediata de Parada de Emergencia
        if self.emergency_stop.is_stopped():
            logger.critical(f"[SKILL RUNTIME HALTED] Parada de Emergencia activa. Skill '{skill.skill_id}' bloqueada.")
            return SkillResult(
                skill_id=skill.skill_id,
                success=False,
                status=SkillStatus.CANCELLED,
                error="Parada de Emergencia activa en el sistema. Ejecución de Skill abortada.",
                security_decision="EMERGENCY_STOP",
                execution_id=context.execution_id,
            )

        # 2. Comprobación de Cancelación previa
        if context.cancellation_token and context.cancellation_token.is_cancelled:
            logger.info(f"[SKILL RUNTIME CANCELLED] Skill '{skill.skill_id}' cancelada antes de iniciar.")
            return SkillResult(
                skill_id=skill.skill_id,
                success=False,
                status=SkillStatus.CANCELLED,
                error="Ejecución cancelada por token de cancelación.",
                security_decision="CANCELLED",
                execution_id=context.execution_id,
            )

        # 3. Control de Presupuesto (AgentBudget)
        if budget is not None:
            # Comprobar si el presupuesto está agotado
            if getattr(budget, "is_exhausted", lambda: False)():
                logger.warning(f"[SKILL BUDGET EXHAUSTED] Presupuesto agotado para skill '{skill.skill_id}'.")
                return SkillResult(
                    skill_id=skill.skill_id,
                    success=False,
                    status=SkillStatus.FAILED,
                    error="Presupuesto de ejecución agotado.",
                    security_decision="BUDGET_EXHAUSTED",
                    execution_id=context.execution_id,
                )

            # Comprobar techo de riesgo
            if hasattr(budget, "risk_ceiling"):
                skill_risk_val = str(getattr(skill.definition.risk_level, "value", skill.definition.risk_level)).upper()
                ceiling_val = str(getattr(budget.risk_ceiling, "value", budget.risk_ceiling)).upper()
                # Si la skill es de riesgo alto/peligroso/crítico y el techo del presupuesto es bajo/medio/solo lectura
                if skill_risk_val in ("DANGEROUS", "CRITICAL", "HIGH") and ceiling_val in ("SAFE", "LOW", "WARNING", "READ_ONLY", "LOW_RISK", "MEDIUM_RISK"):
                    logger.warning(
                        f"[SKILL BUDGET RISK EXCEEDED] Riesgo de skill '{skill.skill_id}' ({skill_risk_val}) supera techo ({ceiling_val})."
                    )
                    return SkillResult(
                        skill_id=skill.skill_id,
                        success=False,
                        status=SkillStatus.FAILED,
                        error=f"El nivel de riesgo de la Skill ({skill_risk_val}) supera el techo de riesgo del presupuesto ({ceiling_val}).",
                        security_decision="BUDGET_RISK_CEILING_EXCEEDED",
                        execution_id=context.execution_id,
                    )

        # 4. Evaluación de Seguridad previa (RiskEngine + PermissionManager)
        sec_req = SecurityRequest(
            action="execute",
            context=SecurityContext(
                user=context.user,
                tool_name=skill.skill_id,
                parameters=context.parameters,
            ),
            metadata=ToolSecurityMetadata(
                tool_name=skill.skill_id,
                category="skill",
                risk_level=skill.definition.risk_level,
            ),
        )

        risk_assessment = self.risk_engine.evaluate_risk(sec_req)
        effective_risk = risk_assessment.risk_level

        perm_decision = self.permission_manager.check_permission(
            tool_name=skill.skill_id,
            risk_level=effective_risk,
        )

        # Si el PermissionManager deniega explícitamente -> FAILED / BLOCKED
        if perm_decision == PermissionDecision.DENY:
            logger.warning(
                f"[SKILL SECURITY DENIAL] Skill '{skill.skill_id}' denegada por permisos de seguridad."
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillResult(
                skill_id=skill.skill_id,
                success=False,
                status=SkillStatus.FAILED,
                error=f"Autorización denegada para la Skill '{skill.skill_id}' por política de seguridad (DENY).",
                security_decision="DENY",
                execution_id=context.execution_id,
                duration_ms=elapsed_ms,
            )

        # Si requiere confirmación humana interactiva (DANGEROUS o CRITICAL)
        if effective_risk in (SecurityLevel.DANGEROUS, SecurityLevel.CRITICAL) or perm_decision == PermissionDecision.REQUIRE_CONFIRMATION:
            if not context.metadata.get("confirmation_approved", False):
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillResult(
                    skill_id=skill.skill_id,
                    success=False,
                    status=SkillStatus.WAITING_CONFIRMATION,
                    error=f"La Skill '{skill.skill_id}' representa riesgo '{effective_risk.value}' y requiere confirmación previa del usuario.",
                    security_decision="REQUIRE_CONFIRMATION",
                    execution_id=context.execution_id,
                    duration_ms=elapsed_ms,
                    metadata={"confirmation_required": True, "risk_level": str(effective_risk)},
                )

        # 5. Ejecución controlada con Timeout y Aislamiento de Errores
        logger.info(f"[SKILL RUNTIME EXECUTING] Ejecutando Skill '{skill.skill_id}' con timeout={context.timeout_seconds}s...")

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(skill.execute, context)
                try:
                    res: SkillResult = future.result(timeout=context.timeout_seconds)
                except TimeoutError:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                    logger.error(
                        f"[SKILL TIMEOUT] Skill '{skill.skill_id}' excedió el timeout de {context.timeout_seconds}s."
                    )
                    return SkillResult(
                        skill_id=skill.skill_id,
                        success=False,
                        status=SkillStatus.FAILED,
                        error=f"Timeout de ejecución: la Skill superó el tiempo límite de {context.timeout_seconds} segundos.",
                        security_decision="TIMEOUT",
                        execution_id=context.execution_id,
                        duration_ms=elapsed_ms,
                    )

            # Comprobar cancelación post-ejecución
            if context.cancellation_token and context.cancellation_token.is_cancelled:
                return SkillResult(
                    skill_id=skill.skill_id,
                    success=False,
                    status=SkillStatus.CANCELLED,
                    error="Ejecución cancelada durante la operación.",
                    security_decision="CANCELLED",
                    execution_id=context.execution_id,
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )

            # Comprobar Parada de Emergencia post-ejecución
            if self.emergency_stop.is_stopped():
                return SkillResult(
                    skill_id=skill.skill_id,
                    success=False,
                    status=SkillStatus.FAILED,
                    error="Parada de Emergencia activada durante la ejecución.",
                    security_decision="EMERGENCY_STOP",
                    execution_id=context.execution_id,
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )

            return res

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error(f"[SKILL RUNTIME EXCEPTION] Error en ejecución de '{skill.skill_id}': {exc}")
            return SkillResult(
                skill_id=skill.skill_id,
                success=False,
                status=SkillStatus.FAILED,
                error=f"Excepción no controlada durante la ejecución de la Skill: {exc}",
                security_decision="EXCEPTION",
                execution_id=context.execution_id,
                duration_ms=elapsed_ms,
            )
