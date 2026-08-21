"""Asistente Proactivo Seguro (proactive_assistant.py - Fase 27).

Orquesta el flujo controlado de eventos proactivos:
EVENT -> EVENT VALIDATION -> POLICY -> RISK -> PERMISSION -> ACTION

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. PROACTIVE != UNRESTRICTED_ACTION (JESSYCA jamás ejecuta acciones peligrosas sin confirmación).
2. Prevalencia de Parada de Emergencia: EmergencyStopManager interrumpe inmediatamente cualquier acción.
3. Thread-safety y blindaje contra condiciones de carrera.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, ClassVar

from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from core.proactive.event_validator import ProactiveEventValidator
from core.proactive.proactive_models import (
    ProactiveActionType,
    ProactiveEvent,
    ProactiveEventType,
    ProactiveExecutionResult,
)
from core.proactive.proactive_policy import ProactivePolicyEngine

logger = get_logger("jessyca.proactive.assistant")


class ProactiveAssistant:
    """Núcleo del Asistente Proactivo Seguro de JESSYCA."""

    _instance: ClassVar[ProactiveAssistant | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        policy_engine: ProactivePolicyEngine | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.policy_engine = policy_engine or ProactivePolicyEngine()
        self._listeners: list[Callable[[ProactiveExecutionResult], None]] = []
        self._execution_history: list[ProactiveExecutionResult] = []

    @classmethod
    def get_instance(cls) -> ProactiveAssistant:
        """Obtiene la instancia singleton global del Asistente Proactivo."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = ProactiveAssistant()
            return cls._instance

    def register_listener(self, listener: Callable[[ProactiveExecutionResult], None]) -> None:
        """Registra un receptor de eventos ejecutados/notificaciones para la UI."""
        with self._lock:
            self._listeners.append(listener)

    def process_event(
        self,
        event: ProactiveEvent,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> ProactiveExecutionResult:
        """Procesa un evento proactivo a través de toda la cadena de validación y seguridad."""
        with self._lock:
            # 1. Comprobación inmediata de Parada de Emergencia
            if self.emergency_stop.is_stopped():
                logger.warning(f"[PROACTIVE ABORTED] Parada de Emergencia activa. Evento '{event.event_id}' descartado.")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message="Parada de Emergencia activa. Acción proactiva descartada.",
                    execution_data={"emergency_stop": True},
                )

            # 2. Comprobación de Cancelación
            if cancellation_token and cancellation_token.is_cancelled:
                logger.info(f"[PROACTIVE CANCELLED] Evento '{event.event_id}' cancelado por token.")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message="Evento proactivo cancelado.",
                    execution_data={"cancelled": True},
                )

            # 3. Validación estructural del evento
            is_valid, val_err = ProactiveEventValidator.validate(event)
            if not is_valid:
                logger.error(f"[PROACTIVE EVENT INVALID] Evento '{event.event_id}' rechazado: {val_err}")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message=f"Evento inválido rechazado: {val_err}",
                    execution_data={"validation_error": val_err},
                )

            # 4. Evaluación de política y riesgo
            decision = self.policy_engine.evaluate_event(event)

            # 5. Ejecución controlada según el tipo de acción decidida
            result: ProactiveExecutionResult

            if decision.action_type == ProactiveActionType.NOTIFY_USER:
                result = ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=True,
                    action_taken=ProactiveActionType.NOTIFY_USER,
                    user_message=decision.user_message,
                    execution_data={"notified": True, "event_type": str(event.event_type)},
                )

            elif decision.action_type == ProactiveActionType.REQUEST_CONFIRMATION:
                result = ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=True,
                    action_taken=ProactiveActionType.REQUEST_CONFIRMATION,
                    user_message=decision.user_message,
                    execution_data={
                        "confirmation_required": True,
                        "risk_level": str(decision.risk_level),
                        "tool_name": event.proposed_tool,
                        "parameters": event.tool_parameters,
                    },
                )

            elif decision.action_type == ProactiveActionType.SAFE_EXECUTE:
                exec_data: dict[str, Any] = {"executed": True}
                if tool_executor and event.proposed_tool:
                    try:
                        out = tool_executor(event.proposed_tool, event.tool_parameters)
                        exec_data["output"] = out
                    except Exception as ex:
                        logger.error(f"[PROACTIVE TOOL EXECUTION ERROR] {ex}")
                        exec_data["execution_error"] = str(ex)

                result = ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=True,
                    action_taken=ProactiveActionType.SAFE_EXECUTE,
                    user_message=decision.user_message,
                    execution_data=exec_data,
                )

            else:  # SUPPRESS / DENY
                result = ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message=decision.user_message,
                    execution_data={"suppressed": True, "reason": decision.reason},
                )

            self._execution_history.append(result)
            listeners_copy = list(self._listeners)

        # Despacho reactivo fuera del lock
        for listener in listeners_copy:
            try:
                listener(result)
            except Exception as e:
                logger.warning(f"[PROACTIVE LISTENER ERROR] Error en listener: {e}")

        return result

    # ── MÉTODOS DE CONVENIENCIA ──

    def notify_task_completed(self, task_id: str, summary: str = "") -> ProactiveExecutionResult:
        """Notifica proactivamente la finalización exitosa de una tarea."""
        event = ProactiveEvent(
            event_type=ProactiveEventType.TASK_COMPLETED,
            source="task_scheduler",
            payload={"task_id": task_id},
            summary=summary,
        )
        return self.process_event(event)

    def notify_task_failed(self, task_id: str, error: str = "") -> ProactiveExecutionResult:
        """Notifica proactivamente el fallo de una tarea."""
        event = ProactiveEvent(
            event_type=ProactiveEventType.TASK_FAILED,
            source="task_scheduler",
            payload={"task_id": task_id},
            summary=error,
        )
        return self.process_event(event)

    def propose_system_action(
        self,
        event_type: ProactiveEventType,
        summary: str,
        tool_name: str,
        tool_parameters: dict[str, Any] | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> ProactiveExecutionResult:
        """Propone proactivamente una acción del sistema (evaluando riesgo y solicitando confirmación si es sensible)."""
        event = ProactiveEvent(
            event_type=event_type,
            source="proactive_monitor",
            summary=summary,
            proposed_tool=tool_name,
            tool_parameters=tool_parameters or {},
        )
        return self.process_event(event, tool_executor=tool_executor)

    def reset(self) -> None:
        """Limpia el estado del asistente proactivo para aislamiento de pruebas."""
        with self._lock:
            self._listeners.clear()
            self._execution_history.clear()


def get_proactive_assistant() -> ProactiveAssistant:
    """Acceso helper al singleton global de ProactiveAssistant."""
    return ProactiveAssistant.get_instance()
