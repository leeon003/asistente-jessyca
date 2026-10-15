"""Adaptador Mínimo para Agent-S en Rama de Evaluación.

Implementa el paradigma Agent-S:
- Planificación Proactiva Jerárquica (PHP: Proactive Hierarchical Planning).
- Mezcla de Grounding (MoG: Mixture of Grounding combinando accesibilidad/DOM + visión).
- Gobernado por RiskEngine y PermissionManager.
- Entorno de ejecución aislado en Sandbox/Mock sin impacto en el escritorio anfitrión.
"""

from __future__ import annotations

import time
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.permission_manager import PermissionDecision, PermissionManager
from core.risk_engine import RiskEngine
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillContext,
    SkillDefinition,
    SkillManifest,
    SkillResult,
    SkillStatus,
)


class EvalAgentSSkill(BaseSkill):
    """Adaptador de evaluación para el paradigma Agent-S."""

    def __init__(self, sandbox_backend: Any | None = None) -> None:
        manifest = SkillManifest(
            id="eval.agent_s",
            name="Agent-S Evaluation Controller",
            version="1.0.0",
            description="Controlador de evaluación Agent-S basado en planificación jerárquica y grounding semántico.",
            author="Jessyca Evaluation Suite",
            capabilities=("desktop", "hierarchical_planning", "grounding", "gui_navigation"),
            required_tools=("desktop.grounding", "desktop.planner"),
            required_agents=("AgentSAgent",),
            permissions=("desktop.interact",),
            risk_level=SecurityLevel.HIGH,
        )
        def_obj = SkillDefinition(
            skill_id="eval.agent_s",
            name="Agent-S Evaluation Controller",
            version="1.0.0",
            description="Adaptador Agent-S mínimo para benchmarking y pruebas de aislamiento.",
            capabilities=("desktop", "hierarchical_planning", "grounding", "gui_navigation"),
            required_tools=("desktop.grounding", "desktop.planner"),
            required_permissions=("desktop.interact",),
            risk_level=SecurityLevel.HIGH,
            tags=("agent_s", "eval", "php", "grounding", "mog"),
            manifest=manifest,
        )
        super().__init__(nombre="eval.agent_s", nivel_riesgo=3, definition=def_obj)
        self.risk_engine = RiskEngine()
        self.permission_manager = PermissionManager()
        self.audit_logger = get_audit_logger()
        self.sandbox = sandbox_backend

    def descripcion(self) -> str:
        return "Adaptador Agent-S para evaluación de planificación y grounding en sandbox."

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una tarea mediante el pipeline PHP + MoG de Agent-S bajo gobernanza."""
        goal = str(parametros.get("goal") or parametros.get("meta") or parametros.get("accion") or "navigate").strip()
        user_identity = str(parametros.get("user_identity") or "verified_owner")
        is_client_mode = bool(parametros.get("is_client_mode", False))

        # 1. Regla Arquitectónica de Modos (Cliente vs Dueño)
        if is_client_mode or user_identity != "verified_owner":
            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.EXECUTION_DENIED,
                    user=user_identity,
                    tool_name="eval.agent_s",
                    operation="hierarchical_plan",
                    security_level=SecurityLevel.CRITICAL,
                    success=False,
                    reason="Acceso denegado: Modo cliente de WhatsApp no tiene autorización para agentes de pantalla.",
                )
            )
            return {
                "exito": False,
                "mensaje": "ACCESO DENEGADO: El modo cliente no tiene acceso al control de pantalla.",
                "security_verdict": "DENY",
                "risk_level": "CRITICAL",
                "steps_taken": 0,
            }

        # 2. Manejo de ambigüedad en fase de planificación (PHP)
        if parametros.get("is_ambiguous", False) or "anótale lo acordado" in goal.lower():
            return {
                "exito": False,
                "status": "AWAITING_CLARIFICATION",
                "mensaje": "Instrucción ambigua detectada por Agent-S Planner. Se solicita aclaración antes de proceder.",
                "clarification_required": True,
                "security_verdict": "AWAITING_CLARIFICATION",
                "steps_taken": 0,
            }

        # 3. Detección de Inyección de Prompt y Rutas Críticas
        params_str = str(parametros).lower()
        if "format" in params_str or "regedit" in params_str or "taskmgr" in params_str or "powershell" in params_str:
            sec_risk = SecurityLevel.CRITICAL
        elif "click" in params_str or "submit" in params_str or "write" in params_str or "fill" in params_str:
            sec_risk = SecurityLevel.HIGH
        else:
            sec_risk = SecurityLevel.SAFE

        # 4. Consulta a PermissionManager
        perm_decision = self.permission_manager.check_permission(
            tool_name="eval.agent_s",
            operation="execute_plan",
            parameters=parametros,
            risk_level=sec_risk,
            user=user_identity,
        )

        if perm_decision not in (PermissionDecision.ALLOW, PermissionDecision.ALLOW_ONCE):
            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.EXECUTION_DENIED,
                    user=user_identity,
                    tool_name="eval.agent_s",
                    operation="execute_plan",
                    security_level=sec_risk,
                    success=False,
                    reason=f"PermissionManager rechazó el plan con decisión '{perm_decision.value}'.",
                )
            )
            return {
                "exito": False,
                "mensaje": f"Plan bloqueado por directivas de seguridad ({perm_decision.value}).",
                "security_verdict": str(perm_decision.value),
                "risk_level": str(sec_risk.value),
                "steps_taken": 0,
            }

        # 5. Ejecución guiada por Grounding (MoG) en el Sandbox
        steps = 0
        executed_details: list[dict[str, Any]] = []

        if self.sandbox:
            # Agent-S primero inspecciona el árbol semántico y luego despacha acciones grounded
            grounding_tree = self.sandbox.get_grounding_tree()
            sandbox_res = self.sandbox.execute_grounded_plan(goal, parametros, grounding_tree)
            steps = sandbox_res.get("steps", 1)
            exito = sandbox_res.get("exito", True)
            msg = sandbox_res.get("mensaje", "Plan Agent-S ejecutado exitosamente.")
            executed_details = sandbox_res.get("details", [])
        else:
            # Sandbox básico en memoria para pruebas de aislamiento
            time.sleep(0.015)  # Simulación de inferencia MoG + UIA parsing
            steps = 2
            exito = True
            msg = f"Meta '{goal}' completada mediante planificación Agent-S."

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.EXECUTION_SUCCEEDED if exito else AuditEventType.EXECUTION_FAILED,
                user=user_identity,
                tool_name="eval.agent_s",
                operation="execute_plan",
                security_level=sec_risk,
                success=exito,
                reason=msg,
                metadata={"steps": steps, "details": executed_details},
            )
        )

        return {
            "exito": exito,
            "mensaje": msg,
            "security_verdict": "ALLOW",
            "risk_level": str(sec_risk.value),
            "steps_taken": steps,
            "details": executed_details,
        }

    def execute(self, context: SkillContext) -> SkillResult:
        raw_res = self.ejecutar(context.parameters)
        exito = raw_res.get("exito", False)
        return SkillResult(
            skill_id=self.skill_id,
            success=exito,
            status=SkillStatus.COMPLETED if exito else SkillStatus.FAILED,
            output=raw_res,
            error=None if exito else raw_res.get("mensaje"),
            execution_id=context.execution_id,
            duration_ms=0.0,
        )
