"""Event Bus Interno para Jessyca Windows MCP.

Proporciona comunicación asíncrona y desacoplada entre componentes basada en el patrón
Publicador/Suscriptor (Pub/Sub) con soporte para ordenación por prioridades,
múltiples listeners, handlers síncronos/asíncronos y tolerancia a fallos.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.event_bus")


class EventPriority(IntEnum):
    """Niveles de prioridad para la ordenación de ejecución de listeners.

    Los valores numéricos menores indican mayor prioridad de ejecución.
    """

    HIGHEST = 0
    HIGH = 10
    NORMAL = 50
    LOW = 100


@dataclass
class Event:
    """Modelo de datos inmutable que representa un evento dentro del sistema."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Subscription:
    """Representación interna de una suscripción activa de un listener."""

    subscription_id: str
    event_name: str
    handler: Callable[..., Any]
    priority: EventPriority = EventPriority.NORMAL


class EventBus:
    """Bus de eventos interno desacoplado y tolerante a fallos."""

    def __init__(self) -> None:
        # Mapa: event_name -> Lista de objetos Subscription
        self._subscriptions: dict[str, list[Subscription]] = {}

    def subscribe(
        self,
        event_name: str,
        handler: Callable[..., Any],
        priority: EventPriority | int = EventPriority.NORMAL,
    ) -> str:
        """Suscribe un handler (síncrono o asíncrono) a un evento específico.

        Args:
            event_name: Nombre del evento a escuchar (ej: 'tool:executed', 'security:alert').
            handler: Función callback a invocar cuando se publique el evento.
            priority: Nivel de prioridad de ejecución (EventPriority).

        Returns:
            str: ID de suscripción único util para cancelar la suscripción posteriormente.
        """
        event_key = event_name.strip()
        sub_id = f"sub_{uuid.uuid4().hex[:12]}"
        enum_priority = (
            priority if isinstance(priority, EventPriority) else EventPriority(int(priority))
        )

        sub = Subscription(
            subscription_id=sub_id,
            event_name=event_key,
            handler=handler,
            priority=enum_priority,
        )

        if event_key not in self._subscriptions:
            self._subscriptions[event_key] = []

        self._subscriptions[event_key].append(sub)
        # Ordenar los listeners según la prioridad (menor valor numérico ejecuta primero)
        self._subscriptions[event_key].sort(key=lambda s: s.priority.value)

        logger.debug(
            f"Nuevo listener suscrito a '{event_key}' [Prioridad: {sub.priority.name}, SubID: {sub_id}]"
        )
        return sub_id

    def unsubscribe(
        self,
        subscription_id_or_handler: str | Callable[..., Any],
        event_name: str | None = None,
    ) -> bool:
        """Cancela la suscripción de un listener por su ID de suscripción o por su función handler.

        Args:
            subscription_id_or_handler: String de ID de suscripción o la función callback.
            event_name: Nombre opcional del evento para acotar la búsqueda.

        Returns:
            bool: True si la suscripción fue encontrada y eliminada, False de lo contrario.
        """
        removed = False

        if isinstance(subscription_id_or_handler, str):
            sub_id = subscription_id_or_handler
            for name, subs in list(self._subscriptions.items()):
                if event_name and name != event_name:
                    continue
                initial_len = len(subs)
                self._subscriptions[name] = [s for s in subs if s.subscription_id != sub_id]
                if len(self._subscriptions[name]) < initial_len:
                    removed = True
                    logger.debug(f"Suscripción '{sub_id}' eliminada de '{name}'.")
        else:
            handler_func = subscription_id_or_handler
            for name, subs in list(self._subscriptions.items()):
                if event_name and name != event_name:
                    continue
                initial_len = len(subs)
                self._subscriptions[name] = [s for s in subs if s.handler != handler_func]
                if len(self._subscriptions[name]) < initial_len:
                    removed = True
                    logger.debug(f"Handler '{handler_func}' des-suscrito de '{name}'.")

        return removed

    def publish(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        """Publica un evento invocando todos los listeners suscritos de forma segura.

        Si un listener lanza una excepción, esta es capturada y registrada en los logs,
        permitiendo que el bus continúe notificando a los demás listeners.

        Args:
            event_name: Nombre del evento a publicar.
            payload: Datos o carga útil asociada al evento.
        """
        event = Event(name=event_name.strip(), payload=payload or {})
        subs = self._get_listeners_for_event(event.name)

        if not subs:
            logger.debug(f"Evento '{event.name}' publicado sin listeners suscritos.")
            return

        logger.debug(f"Publicando evento '{event.name}' a {len(subs)} listeners...")

        for sub in subs:
            try:
                if inspect.iscoroutinefunction(sub.handler):
                    # Si estamos en un bucle asíncrono activo, programar la corrutina
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._safe_async_call(sub, event))
                    except RuntimeError:
                        # Si no hay bucle asíncrono activo, ejecutar sincrónicamente en un loop temporal
                        asyncio.run(self._safe_async_call(sub, event))
                else:
                    sub.handler(event)
            except Exception as e:
                logger.error(
                    f"Error no controlado en el listener de '{event.name}' [SubID: {sub.subscription_id}]: {e}",
                    exc_info=True,
                )

    async def publish_async(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        """Publica un evento de manera asíncrona awaitable, ejecutando todos los listeners en orden de prioridad."""
        event = Event(name=event_name.strip(), payload=payload or {})
        subs = self._get_listeners_for_event(event.name)

        if not subs:
            logger.debug(f"Evento asíncrono '{event.name}' publicado sin listeners.")
            return

        logger.debug(f"Publicando evento asíncrono '{event.name}' a {len(subs)} listeners...")

        for sub in subs:
            await self._safe_async_call(sub, event)

    async def _safe_async_call(self, sub: Subscription, event: Event) -> None:
        """Ejecuta un listener (síncrono o asíncrono) dentro de un bloque seguro contra fallos."""
        try:
            if inspect.iscoroutinefunction(sub.handler):
                await sub.handler(event)
            else:
                sub.handler(event)
        except Exception as e:
            logger.error(
                f"Error en listener asíncrono de '{event.name}' [SubID: {sub.subscription_id}]: {e}",
                exc_info=True,
            )

    def _get_listeners_for_event(self, event_name: str) -> list[Subscription]:
        """Obtiene la lista ordenada de listeners para un evento específico, incluyendo comodines ('*')."""
        exact_subs = self._subscriptions.get(event_name, [])
        wildcard_subs = self._subscriptions.get("*", [])

        all_subs = list(exact_subs) + list(wildcard_subs)
        all_subs.sort(key=lambda s: s.priority.value)
        return all_subs

    def clear_all_listeners(self, event_name: str | None = None) -> None:
        """Limpia todos los listeners registrados o los pertenecientes a un evento específico."""
        if event_name:
            self._subscriptions.pop(event_name.strip(), None)
            logger.debug(f"Todos los listeners de '{event_name}' han sido limpiados.")
        else:
            self._subscriptions.clear()
            logger.info("Todos los listeners del EventBus han sido limpiados.")

    def get_listener_count(self, event_name: str | None = None) -> int:
        """Devuelve el total de listeners registrados globalmente o para un evento específico."""
        if event_name:
            return len(self._subscriptions.get(event_name.strip(), []))
        return sum(len(subs) for subs in self._subscriptions.values())


# Instancia Singleton Global de conveniencia
_global_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Devuelve la instancia Singleton global del EventBus."""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus
