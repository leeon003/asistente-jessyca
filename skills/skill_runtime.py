"""Entorno de ejecución seguro para Skills (skill_runtime.py - Fase 28.0).

Ejecuta el ciclo de vida gobernado de una Skill:
Skill Validation -> SecurityPipeline -> Tool / Agent / Model -> Verification -> SkillResult

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. UNA SKILL NUNCA PUEDE EJECUTAR OPERACIONES PRIVILEGIADAS DIRECTAMENTE (sin pasar por SecurityPipeline).
2. PREVALENCIA DE PARADA DE EMERGENCIA: EmergencyStopManager interrumpe inmediatamente cualquier Skill.
"""

from __future__ import annotations

import time

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
    """Runtime seguro de ejecución e intermediación de Skills de JESSYCA."""

    def __init__(
        self,
        risk_engine: RiskEngine | None = None,
        permission_manager: PermissionManager | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.risk_engine = risk_engine or RiskEngine()
        self.permission_manager = permission_manager or PermissionManager()
        self.emergency_stop = emergency_stop or EmergencyStopManager.get_instance()

    def execute_skill(
        self,
        skill: BaseSkill,
        context: SkillContext,
    ) -> SkillResult:
        """Ejecuta una Skill a través de la frontera de seguridad y ciclo de vida controlado."""
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

        # 2. Comprobación de Cancelación
        if context.cancellation_token and context.cancellation_token.is_cancelled:
            logger.info(f"[SKILL RUNTIME CANCELLED] Skill '{skill.skill_id}' cancelada por token.")
            return SkillResult(
                skill_id=skill.skill_id,
                success=False,
                status=SkillStatus.CANCELLED,
                error="Ejecución cancelada por token de cancelación.",
                security_decision="CANCELLED",
                execution_id=context.execution_id,
            )

        # 3. Evaluación de Seguridad previa (RiskEngine + PermissionManager)
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

        # 4. Ejecución de la Skill
        logger.info(f"[SKILL RUNTIME EXECUTING] Ejecutando Skill '{skill.skill_id}'...")
        res = skill.execute(context)
        return res
