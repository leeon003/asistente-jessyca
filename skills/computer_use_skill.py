"""Habilidad de interacción de escritorio Windows Computer Use (skills/computer_use_skill.py).

Gobernada estrictamente por la Security Layer de JESSYCA (RiskEngine, PermissionManager):
- Observación y lectura de pantalla (SAFE / Nivel 1)
- Foco y cambio de ventana (MODERATE / Nivel 2)
- Clics de mouse, pulsación de teclas y escritura de texto (HIGH / Nivel 3)
"""

from __future__ import annotations

import time
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.execution.execution_verifier import ExecutionStatus, get_execution_verifier
from core.integration.adapters.computer_use_adapter import ComputerUseAdapter
from core.integration.models import IntegrationContext
from core.logger import get_logger
from core.permission_manager import PermissionManager
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

logger = get_logger("jessyca.skills.computer_use")


class WindowsComputerUseSkill(BaseSkill):
    """Habilidad oficial de Computer Use para control de escritorio gobernado en Windows."""

    def __init__(self, adapter: ComputerUseAdapter | None = None) -> None:
        manifest = SkillManifest(
            id="windows.computer_use",
            name="Windows Computer Use Controller",
            version="1.0.0",
            description="Control e interacción física gobernada con el escritorio de Windows: observación de pantalla, clics de mouse, escritura de texto, atajos de teclado y gestión de ventanas.",
            author="Jessyca Security & Systems",
            capabilities=("desktop", "desktop_interaction", "hardware_control", "application_control"),
            required_tools=("desktop.mouse", "desktop.keyboard", "desktop.window", "desktop.screen"),
            required_agents=("DesktopAgent",),
            permissions=("desktop.interact",),
            risk_level=SecurityLevel.HIGH,
        )
        def_obj = SkillDefinition(
            skill_id="windows.computer_use",
            name="Windows Computer Use Controller",
            version="1.0.0",
            description="Control seguro e interactivo del escritorio bajo gobernanza de RiskEngine.",
            capabilities=("desktop", "desktop_interaction", "hardware_control", "application_control"),
            required_tools=("desktop.mouse", "desktop.keyboard", "desktop.window", "desktop.screen"),
            required_permissions=("desktop.interact",),
            risk_level=SecurityLevel.HIGH,
            tags=("computer_use", "mouse", "teclado", "clic", "escribe", "ventana", "desktop", "pantalla", "control"),
            manifest=manifest,
        )
        super().__init__(nombre="windows.computer_use", nivel_riesgo=3, definition=def_obj)
        self.adapter = adapter or ComputerUseAdapter()
        self.risk_engine = RiskEngine()
        self.permission_manager = PermissionManager()
        self.audit_logger = get_audit_logger()
        self.verifier = get_execution_verifier()

    def descripcion(self) -> str:
        return "Control e interacción gobernada con el escritorio de Windows (mouse, teclado, ventanas y observación)."

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una acción física de Computer Use previa evaluación de riesgo."""
        accion = str(parametros.get("accion") or parametros.get("action") or "observe").strip().lower()
        request_id = str(parametros.get("request_id") or f"cua-{int(time.time()*1000)}")
        session_id = str(parametros.get("session_id") or "default_session")

        # 1. Mapeo de riesgo según la criticidad de la acción
        if accion in ("observe", "screenshot", "get_windows", "active_window"):
            action_risk = SecurityLevel.SAFE
        elif accion in ("focus_window", "move_mouse", "scroll"):
            action_risk = SecurityLevel.LOW
        else:
            # click, double_click, right_click, type_text, press_key, hotkey
            action_risk = SecurityLevel.HIGH

        # 2. Evaluación con PermissionManager y RiskEngine
        perm_granted = self.permission_manager.check_permission(
            skill_name="windows.computer_use",
            context={
                "action": accion,
                "risk_level": action_risk.value,
                "session_id": session_id,
            },
        )
        if not perm_granted:
            logger.warning(f"[COMPUTER_USE_DENIED] Acción '{accion}' bloqueada por PermissionManager (Riesgo: {action_risk.value}).")
            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.EXECUTION_DENIED,
                    user="leeon",
                    tool_name="windows.computer_use",
                    operation=accion,
                    security_level=action_risk,
                    success=False,
                    reason="PermissionManager denied action",
                    metadata={"risk_level": action_risk.value},
                )
            )
            return {
                "exito": False,
                "mensaje": f"Acción '{accion}' no autorizada por las políticas de seguridad de Windows Computer Use.",
                "action": accion,
                "risk_level": action_risk.value,
                "security_verdict": "DENY",
            }

        # 3. Despacho al ComputerUseAdapter
        ctx = IntegrationContext(
            session_id=session_id,
            user_id="user",
            parameters=parametros,
            metadata={
                "execution_id": request_id,
                "action_id": f"act-{accion}",
                "source": "JessycaLocalAgent",
                "risk_level": action_risk.value,
            },
        )

        try:
            # Asegurar adapter inicializado
            if not self.adapter.is_ready():
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Si ya hay loop corriendo, ejecutar sincrónicamente su lógica interna básica
                        self.adapter._status = self.adapter._status.__class__.READY
                    else:
                        loop.run_until_complete(self.adapter.initialize())
                except RuntimeError:
                    asyncio.run(self.adapter.initialize())

            res = self.adapter.execute(action=accion, params=parametros, context=ctx)
            exito = bool(res.success)
            mensaje = res.message or ("Acción completada exitosamente" if exito else "Fallo en la ejecución")

            # 4. Auditoría de Seguridad
            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.EXECUTION_SUCCEEDED if exito else AuditEventType.EXECUTION_FAILED,
                    user="leeon",
                    tool_name="windows.computer_use",
                    operation=accion,
                    security_level=action_risk,
                    success=exito,
                    reason=mensaje,
                    metadata={"verified": getattr(res, "verified", False)},
                )
            )

            return {
                "exito": exito,
                "mensaje": mensaje,
                "action": accion,
                "datos": res.data,
                "verified": res.verified,
                "security_verdict": "ALLOW",
                "risk_level": action_risk.value,
            }

        except Exception as exc:
            logger.error(f"[COMPUTER_USE_ERROR] Error ejecutando acción '{accion}': {exc}", exc_info=True)
            return {
                "exito": False,
                "mensaje": f"Error ejecutando '{accion}' en el escritorio: {exc}",
                "action": accion,
                "error": str(exc),
                "security_verdict": "ERROR",
            }

    def execute(self, context: SkillContext) -> SkillResult:
        """Interfaz moderna del Skill Framework (Fase 28+)."""
        raw_res = self.ejecutar(context.parameters)
        exito = raw_res.get("exito", False)
        msg = raw_res.get("mensaje", "")
        return SkillResult(
            skill_id=self.skill_id,
            success=exito,
            status=SkillStatus.COMPLETED if exito else SkillStatus.FAILED,
            output=raw_res,
            error=None if exito else msg,
            execution_id=context.execution_id,
            duration_ms=0.0,
            metadata={"action": raw_res.get("action"), "verified": raw_res.get("verified", False)},
        )
