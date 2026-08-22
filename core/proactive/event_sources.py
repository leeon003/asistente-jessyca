"""Adaptadores y Hub de Fuentes de Eventos Proactivos (event_sources.py - Fase 44).

Conecta fuentes existentes del sistema:
- Scheduler (tareas programadas, disparos temporales)
- Application State (cambios de ventana, aplicaciones en primer plano)
- Calendar (eventos, reuniones próximas y agenda)
- Files (archivos modificados, creados, descargados)
- Browser (navegación web, pestañas, descargas)
- System Events (alertas de disco, memoria, red, errores)
- User Interaction (foco, inactividad, peticiones recientes)

PRINCIPIO DE SEGURIDAD INMUTABLE:
Todos los datos provenientes de fuentes externas son UNTRUSTED DATA.
Ningún evento externo se interpreta directamente como instrucción sin pasar por el Proactive Pipeline.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from core.logger import get_logger
from core.proactive.proactive_models import (
    EventSourceType,
    ProactiveEvent,
    ProactiveEventType,
)

logger = get_logger("jessyca.proactive.sources")


class EventSourceAdapter(ABC):
    """Clase base abstracta para adaptadores de fuentes de eventos proactivos."""

    def __init__(self, source_type: EventSourceType, name: str) -> None:
        self.source_type = source_type
        self.name = name
        self._enabled = True

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @abstractmethod
    def create_event(
        self,
        event_type: ProactiveEventType,
        summary: str,
        payload: dict[str, Any] | None = None,
        proposed_tool: str | None = None,
        tool_parameters: dict[str, Any] | None = None,
        context_metadata: dict[str, Any] | None = None,
    ) -> ProactiveEvent:
        """Crea y normaliza un ProactiveEvent desde esta fuente específica."""
        pass


class GenericEventSourceAdapter(EventSourceAdapter):
    """Adaptador estándar reutilizable para fuentes de eventos del sistema."""

    def create_event(
        self,
        event_type: ProactiveEventType,
        summary: str,
        payload: dict[str, Any] | None = None,
        proposed_tool: str | None = None,
        tool_parameters: dict[str, Any] | None = None,
        context_metadata: dict[str, Any] | None = None,
    ) -> ProactiveEvent:
        return ProactiveEvent(
            event_type=event_type,
            source=self.name,
            source_type=self.source_type,
            summary=summary,
            payload=payload or {},
            proposed_tool=proposed_tool,
            tool_parameters=tool_parameters or {},
            is_untrusted_data=True,
            context_metadata=context_metadata or {},
        )


class SchedulerEventSource(GenericEventSourceAdapter):
    """Adaptador de eventos de tareas programadas y temporizadores."""

    def __init__(self) -> None:
        super().__init__(EventSourceType.SCHEDULER, "scheduler")


class ApplicationStateEventSource(GenericEventSourceAdapter):
    """Adaptador de eventos de estado de aplicaciones de escritorio y ventanas."""

    def __init__(self) -> None:
        super().__init__(EventSourceType.APPLICATION_STATE, "application_state")


class CalendarEventSource(GenericEventSourceAdapter):
    """Adaptador de eventos de calendario y reuniones próximas."""

    def __init__(self) -> None:
        super().__init__(EventSourceType.CALENDAR, "calendar")

    def create_upcoming_meeting_event(
        self,
        meeting_title: str,
        starts_in_minutes: int,
        related_document: str | None = None,
        participants: list[str] | None = None,
    ) -> ProactiveEvent:
        """Crea un evento especializado de reunión próxima con documentos relacionados."""
        payload = {
            "meeting_title": meeting_title,
            "starts_in_minutes": starts_in_minutes,
            "related_document": related_document,
            "participants": participants or [],
        }
        summary = f"Tienes una reunión próximamente: '{meeting_title}' en {starts_in_minutes} minutos."
        if related_document:
            summary += f" Existe un documento relacionado: '{related_document}'."

        tool = "document.open" if related_document else None
        params = {"path": related_document} if related_document else {}

        return self.create_event(
            event_type=ProactiveEventType.CALENDAR_UPCOMING,
            summary=summary,
            payload=payload,
            proposed_tool=tool,
            tool_parameters=params,
            context_metadata={"meeting_title": meeting_title, "document": related_document},
        )


class FilesEventSource(GenericEventSourceAdapter):
    """Adaptador de eventos del sistema de archivos."""

    def __init__(self) -> None:
        super().__init__(EventSourceType.FILES, "files")


class BrowserEventSource(GenericEventSourceAdapter):
    """Adaptador de eventos de actividad y navegación en el explorador web."""

    def __init__(self) -> None:
        super().__init__(EventSourceType.BROWSER, "browser")


class SystemEventsSource(GenericEventSourceAdapter):
    """Adaptador de eventos del sistema operativo Windows."""

    def __init__(self) -> None:
        super().__init__(EventSourceType.SYSTEM_EVENTS, "system_events")


class UserInteractionEventSource(GenericEventSourceAdapter):
    """Adaptador de eventos de interacción y foco del usuario."""

    def __init__(self) -> None:
        super().__init__(EventSourceType.USER_INTERACTION, "user_interaction")


class EventSourceHub:
    """Hub centralizado de gestión y registro de fuentes de eventos proactivos."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._adapters: dict[EventSourceType, EventSourceAdapter] = {
            EventSourceType.SCHEDULER: SchedulerEventSource(),
            EventSourceType.APPLICATION_STATE: ApplicationStateEventSource(),
            EventSourceType.CALENDAR: CalendarEventSource(),
            EventSourceType.FILES: FilesEventSource(),
            EventSourceType.BROWSER: BrowserEventSource(),
            EventSourceType.SYSTEM_EVENTS: SystemEventsSource(),
            EventSourceType.USER_INTERACTION: UserInteractionEventSource(),
        }
        self._subscribers: list[Callable[[ProactiveEvent], None]] = []

    def register_adapter(self, adapter: EventSourceAdapter) -> None:
        """Registra un adaptador de fuente de eventos personalizado."""
        with self._lock:
            self._adapters[adapter.source_type] = adapter
            logger.info(f"Adaptador '{adapter.name}' ({adapter.source_type}) registrado en EventSourceHub.")

    def get_adapter(self, source_type: EventSourceType) -> EventSourceAdapter | None:
        """Obtiene el adaptador para un tipo de fuente."""
        with self._lock:
            return self._adapters.get(source_type)

    def subscribe(self, callback: Callable[[ProactiveEvent], None]) -> None:
        """Suscribe un listener para recibir eventos capturados desde cualquier fuente."""
        with self._lock:
            self._subscribers.append(callback)

    def publish_event(self, event: ProactiveEvent) -> None:
        """Publica un evento capturado hacia todos los suscriptores registrados."""
        with self._lock:
            adapter = self._adapters.get(event.source_type)
            if adapter and not adapter.is_enabled:
                logger.debug(f"Evento {event.event_id} omitido porque la fuente {event.source_type} está deshabilitada.")
                return

            subscribers_copy = list(self._subscribers)

        for sub in subscribers_copy:
            try:
                sub(event)
            except Exception as ex:
                logger.warning(f"Error en suscriptor de EventSourceHub: {ex}")
