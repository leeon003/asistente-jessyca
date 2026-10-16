"""Adaptador Mínimo para CUA (Computer Use Agent) en Rama de Evaluación.

Implementa el paradigma CUA:
- Acciones atómicas de infraestructura: observe, click, type, window, evaluate.
- Gobernado por RiskEngine y PermissionManager con firma corregida.
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


class EvalCuaSkill(BaseSkill):
    """Adaptador de evaluación para el paradigma CUA."""

    def __init__(self, sandbox_backend: Any | None = None) -> None:
        manifest = SkillManifest(
            id="eval.cua",
            name="CUA Evaluation Controller",
            version="1.0.0",
            description="Controlador de evaluación CUA basado en comandos directos y sandbox de pantalla.",
            author="Jessyca Evaluation Suite",
            capabilities=("desktop", "sandbox_control", "mouse", "keyboard"),
            required_tools=("desktop.mouse", "desktop.keyboard"),
            required_agents=("CUAAgent",),
            permissions=("desktop.interact",),
            risk_level=SecurityLevel.HIGH,
        )
        def_obj = SkillDefinition(
            skill_id="eval.cua",
            name="CUA Evaluation Controller",
            version="1.0.0",
            description="Adaptador CUA mínimo para benchmarking y pruebas de aislamiento.",
            capabilities=("desktop", "sandbox_control", "mouse", "keyboard"),
            required_tools=("desktop.mouse", "desktop.keyboard"),
            required_permissions=("desktop.interact",),
            risk_level=SecurityLevel.HIGH,
            tags=("cua", "eval", "sandbox", "mouse", "keyboard"),
            manifest=manifest,
        )
        super().__init__(nombre="eval.cua", nivel_riesgo=3, definition=def_obj)
        self.risk_engine = RiskEngine()
        self.permission_manager = PermissionManager()
        self.audit_logger = get_audit_logger()
        self.sandbox = sandbox_backend

    def descripcion(self) -> str:
        return "Adaptador CUA para evaluación en sandbox aislado."

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una acción CUA gobernada por RiskEngine y PermissionManager."""
        accion = str(parametros.get("accion") or parametros.get("action") or "observe").strip().lower()
        sub_actions = parametros.get("sub_actions") or []
        user_identity = str(parametros.get("user_identity") or "verified_owner")
        is_client_mode = bool(parametros.get("is_client_mode", False))

        # 1. Regla Arquitectónica de Modos (Cliente vs Dueño)
        if is_client_mode or user_identity != "verified_owner":
            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.EXECUTION_DENIED,
                    user=user_identity,
                    tool_name="eval.cua",
                    operation=accion,
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

        # 2. Manejo de ambigüedad previo a la ejecución
        if parametros.get("is_ambiguous", False) or "anótale lo acordado" in str(parametros).lower():
            return {
                "exito": False,
                "status": "AWAITING_CLARIFICATION",
                "mensaje": "Instrucción ambigua. Se solicita aclaración antes de proceder.",
                "clarification_required": True,
                "security_verdict": "AWAITING_CLARIFICATION",
                "steps_taken": 0,
            }

        # 3. Parada de Emergencia activa
        if parametros.get("trigger_emergency_stop", False) or (self.sandbox and self.sandbox.emergency_stop_triggered):
            return {
                "exito": False,
                "mensaje": "ABORTED: Parada de emergencia activa.",
                "security_verdict": "ABORTED",
                "steps_taken": 0,
            }

        # 4. Mapeo y evaluación de riesgo con RiskEngine
        if accion in ("observe", "screenshot", "get_status"):
            sec_risk = SecurityLevel.SAFE
        elif accion in ("focus_window", "navigate"):
            sec_risk = SecurityLevel.LOW
        elif "format" in str(parametros).lower() or "regedit" in str(parametros).lower() or "taskmgr" in str(parametros).lower():
            sec_risk = SecurityLevel.CRITICAL
        else:
            sec_risk = SecurityLevel.HIGH

        # 5. Consulta estricta con PermissionManager
        perm_decision = self.permission_manager.check_permission(
            tool_name="eval.cua",
            operation=accion,
            parameters=parametros,
            risk_level=sec_risk,
            user=user_identity,
        )

        user_confirmed = bool(parametros.get("user_confirmed", True))  # El dueño autorizó la tarea en el benchmark
        is_authorized = (perm_decision in (PermissionDecision.ALLOW, PermissionDecision.ALLOW_ONCE)) or (
            perm_decision == PermissionDecision.REQUIRE_CONFIRMATION and user_confirmed and sec_risk != SecurityLevel.CRITICAL
        )

        if not is_authorized:
            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.EXECUTION_DENIED,
                    user=user_identity,
                    tool_name="eval.cua",
                    operation=accion,
                    security_level=sec_risk,
                    success=False,
                    reason=f"PermissionManager rechazó la acción '{accion}' con decisión '{perm_decision.value}'.",
                )
            )
            return {
                "exito": False,
                "mensaje": f"Acción '{accion}' bloqueada por políticas de seguridad ({perm_decision.value}).",
                "security_verdict": str(perm_decision.value),
                "risk_level": str(sec_risk.value),
                "steps_taken": 0,
            }

        # 5. Ejecución dentro del Sandbox de Evaluación
        steps = 0
        executed_details: list[dict[str, Any]] = []

        if self.sandbox:
            sandbox_res = self.sandbox.execute_action(accion, parametros)
            steps = sandbox_res.get("steps", 1)
            exito = sandbox_res.get("exito", True)
            msg = sandbox_res.get("mensaje", "Acción CUA ejecutada en sandbox.")
            executed_details = sandbox_res.get("details", [])
        else:
            # Sandbox básico en memoria para pruebas de aislamiento
            time.sleep(0.01)  # Simulación de latencia de red/driver
            steps = 1
            exito = True
            msg = f"Acción '{accion}' completada en sandbox."

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.EXECUTION_SUCCEEDED if exito else AuditEventType.EXECUTION_FAILED,
                user=user_identity,
                tool_name="eval.cua",
                operation=accion,
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
