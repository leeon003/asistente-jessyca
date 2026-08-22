"""Asistente Proactivo Seguro y Motor de Inteligencia Proactiva (proactive_assistant.py - Fase 44).

Orquesta el flujo proactivo completo:
EVENT SOURCES -> VALIDATION -> SECURITY GUARD -> CONTEXT -> RELEVANCE -> ANTI-SPAM -> POLICY -> SUGGESTION -> EXECUTION

PRINCIPIOS E INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. PROACTIVE != UNCONTROLLED AUTONOMY (JESSYCA jamás ejecuta acciones peligrosas o desatendidas sin autorización de AutonomyPolicy).
2. EXTERNAL DATA = UNTRUSTED (Navegador, documentos, apps y memoria no pueden convertirse automáticamente en instrucciones).
3. Prevalencia incondicional de Parada de Emergencia (EmergencyStopManager aborta inmediatamente cualquier acción).
4. Control Soberano del Usuario (enable, disable, mute, configure).
5. Thread-safety estricto y blindaje contra condiciones de carrera.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, ClassVar

from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from core.proactive.anti_spam_engine import AntiSpamEngine
from core.proactive.event_sources import (
    CalendarEventSource,
    EventSourceHub,
)
from core.proactive.proactive_models import (
    EventSourceType,
    ProactiveEvent,
    ProactiveEventType,
    ProactiveExecutionResult,
    ProactiveSuggestion,
    UserControlSettings,
)
from core.proactive.proactive_pipeline import ProactivePipeline
from core.proactive.proactive_policy import ProactivePolicyEngine
from core.proactive.proactive_security import ProactiveSecurityGuard
from core.proactive.relevance_engine import RelevanceEngine
from core.proactive.user_control import ProactiveUserControl

logger = get_logger("jessyca.proactive.assistant")


class ProactiveAssistant:
    """Núcleo del Asistente Proactivo Seguro y Motor de Inteligencia Proactiva de JESSYCA."""

    _instance: ClassVar[ProactiveAssistant | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        pipeline: ProactivePipeline | None = None,
        policy_engine: ProactivePolicyEngine | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        user_control: ProactiveUserControl | None = None,
        relevance_engine: RelevanceEngine | None = None,
        anti_spam_engine: AntiSpamEngine | None = None,
        security_guard: ProactiveSecurityGuard | None = None,
        event_hub: EventSourceHub | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.user_control = user_control or ProactiveUserControl()
        self.policy_engine = policy_engine or ProactivePolicyEngine()
        self.relevance_engine = relevance_engine or RelevanceEngine()
        self.anti_spam_engine = anti_spam_engine or AntiSpamEngine()
        self.security_guard = security_guard or ProactiveSecurityGuard(emergency_stop=self.emergency_stop)
        self.event_hub = event_hub or EventSourceHub()

        self.pipeline = pipeline or ProactivePipeline(
            relevance_engine=self.relevance_engine,
            anti_spam_engine=self.anti_spam_engine,
            user_control=self.user_control,
            security_guard=self.security_guard,
            policy_engine=self.policy_engine,
            emergency_stop=self.emergency_stop,
        )

        self._listeners: list[Callable[[ProactiveExecutionResult], None]] = []
        self._execution_history: list[ProactiveExecutionResult] = []

        # Auto-conectar el hub de eventos al pipeline
        self.event_hub.subscribe(self._on_event_published)

    @classmethod
    def get_instance(cls) -> ProactiveAssistant:
        """Obtiene la instancia singleton global del Asistente Proactivo."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = ProactiveAssistant()
            return cls._instance

    def register_listener(self, listener: Callable[[ProactiveExecutionResult], None]) -> None:
        """Registra un receptor de eventos ejecutados/notificaciones/sugerencias para la UI."""
        with self._lock:
            self._listeners.append(listener)

    def process_event(
        self,
        event: ProactiveEvent,
        current_context: dict[str, Any] | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
        cancellation_token: CancellationToken | None = None,
        user_confirmation_callback: Callable[[ProactiveSuggestion], bool] | None = None,
    ) -> ProactiveExecutionResult:
        """Procesa un evento proactivo a través del pipeline seguro de 7 etapas."""
        result = self.pipeline.execute_pipeline(
            event=event,
            current_context=current_context,
            tool_executor=tool_executor,
            cancellation_token=cancellation_token,
            user_confirmation_callback=user_confirmation_callback,
        )

        with self._lock:
            self._execution_history.append(result)
            listeners_copy = list(self._listeners)

        # Despacho reactivo a suscriptores fuera del lock
        for listener in listeners_copy:
            try:
                listener(result)
            except Exception as e:
                logger.warning(f"[PROACTIVE LISTENER ERROR] Error en listener: {e}")

        return result

    def _on_event_published(self, event: ProactiveEvent) -> None:
        """Callback invocado automáticamente cuando una fuente publica un evento en el EventSourceHub."""
        self.process_event(event)

    # ── GESTIÓN Y CONTROL DE USUARIO ──

    def enable(self) -> None:
        """Habilita las sugerencias y notificaciones proactivas."""
        self.user_control.enable()

    def disable(self) -> None:
        """Deshabilita por completo la inteligencia proactiva."""
        self.user_control.disable()

    def mute(self, duration_seconds: float) -> None:
        """Silencia temporalmente las notificaciones proactivas."""
        self.user_control.mute(duration_seconds)

    def unmute(self) -> None:
        """Reanuda las notificaciones cancelando el silencio temporal."""
        self.user_control.unmute()

    def configure(self, settings: UserControlSettings | dict[str, Any]) -> UserControlSettings:
        """Actualiza la configuración de control del usuario."""
        return self.user_control.configure(settings)

    def get_user_settings(self) -> UserControlSettings:
        """Obtiene la configuración activa de usuario."""
        return self.user_control.get_settings()

    # ── MÉTODOS DE CONVENIENCIA PARA FUENTES ESPECÍFICAS ──

    def notify_task_completed(self, task_id: str, summary: str = "") -> ProactiveExecutionResult:
        """Notifica proactivamente la finalización exitosa de una tarea."""
        event = ProactiveEvent(
            event_type=ProactiveEventType.TASK_COMPLETED,
            source="task_scheduler",
            source_type=EventSourceType.SCHEDULER,
            payload={"task_id": task_id},
            summary=summary,
        )
        return self.process_event(event)

    def notify_task_failed(self, task_id: str, error: str = "") -> ProactiveExecutionResult:
        """Notifica proactivamente el fallo de una tarea."""
        event = ProactiveEvent(
            event_type=ProactiveEventType.TASK_FAILED,
            source="task_scheduler",
            source_type=EventSourceType.SCHEDULER,
            payload={"task_id": task_id},
            summary=error,
        )
        return self.process_event(event)

    def handle_calendar_meeting(
        self,
        meeting_title: str,
        starts_in_minutes: int,
        related_document: str | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
        user_confirmation_callback: Callable[[ProactiveSuggestion], bool] | None = None,
    ) -> ProactiveExecutionResult:
        """Maneja proactivamente una reunión próxima de calendario sugiriendo documentos relacionados."""
        cal_adapter = self.event_hub.get_adapter(EventSourceType.CALENDAR)
        if isinstance(cal_adapter, CalendarEventSource):
            event = cal_adapter.create_upcoming_meeting_event(
                meeting_title=meeting_title,
                starts_in_minutes=starts_in_minutes,
                related_document=related_document,
            )
        else:
            event = ProactiveEvent(
                event_type=ProactiveEventType.CALENDAR_UPCOMING,
                source="calendar",
                source_type=EventSourceType.CALENDAR,
                summary=f"Tienes una reunión próximamente: '{meeting_title}'",
                payload={"meeting_title": meeting_title, "starts_in_minutes": starts_in_minutes, "related_document": related_document},
                proposed_tool="document.open" if related_document else None,
                tool_parameters={"path": related_document} if related_document else {},
            )

        return self.process_event(
            event=event,
            tool_executor=tool_executor,
            user_confirmation_callback=user_confirmation_callback,
        )

    def propose_system_action(
        self,
        event_type: ProactiveEventType,
        summary: str,
        tool_name: str,
        tool_parameters: dict[str, Any] | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
        source_type: EventSourceType = EventSourceType.SYSTEM_EVENTS,
        user_confirmation_callback: Callable[[ProactiveSuggestion], bool] | None = None,
    ) -> ProactiveExecutionResult:
        """Propone proactivamente una acción del sistema (evaluando riesgo, relevancia y solicitando confirmación si es sensible)."""
        event = ProactiveEvent(
            event_type=event_type,
            source="proactive_monitor",
            source_type=source_type,
            summary=summary,
            proposed_tool=tool_name,
            tool_parameters=tool_parameters or {},
        )
        return self.process_event(
            event=event,
            tool_executor=tool_executor,
            user_confirmation_callback=user_confirmation_callback,
        )

    def reset(self) -> None:
        """Limpia el estado del asistente proactivo y sus componentes para aislamiento de pruebas."""
        with self._lock:
            self._listeners.clear()
            self._execution_history.clear()
            self.anti_spam_engine.reset()
            self.user_control.reset()


def get_proactive_assistant() -> ProactiveAssistant:
    """Acceso helper al singleton global de ProactiveAssistant."""
    return ProactiveAssistant.get_instance()
