"""Event Bus interno, asíncrono y tipado para JESSYCA 4.0.

Permite desacoplar componentes publicando y suscribiéndose a eventos tipados (instancias de Event).
Soporta handlers síncronos y asíncronos, múltiples suscriptores, despacho polimórfico,
aislamiento de excepciones y ejecución sin dependencias externas ni hardware real.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Coroutine, Generator
from typing import Any, TypeVar

from core.events.base import Event
from core.logger import get_logger

logger = get_logger("jessyca.event_bus")

T = TypeVar("T", bound=Event)
HandlerType = Callable[[Any], Any]


class PublishAwaitable:
    """Objeto awaitable devuelto por EventBus.publish.

    Permite que `bus.publish(event)` se utilice de forma transparente tanto
    en código síncrono (los handlers síncronos se ejecutan inmediatamente)
    como en código asíncrono con `await bus.publish(event)`.
    """

    def __init__(
        self,
        event: Event,
        async_handlers: list[Callable[[Any], Coroutine[Any, Any, Any]]],
    ) -> None:
        self._event = event
        self._async_handlers = async_handlers
        self._tasks: list[asyncio.Task[Any]] = []

        # Si hay handlers asíncronos y ya existe un bucle activo, programar como tareas
        if self._async_handlers:
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    for handler in self._async_handlers:
                        t = loop.create_task(self._safe_invoke_async(handler, self._event))
                        self._tasks.append(t)
            except RuntimeError:
                pass

    @staticmethod
    async def _safe_invoke_async(
        handler: Callable[[Any], Coroutine[Any, Any, Any]],
        event: Event,
    ) -> None:
        try:
            await handler(event)
        except Exception as exc:
            logger.error(
                f"EVENT BUS: Excepción en subscriber asíncrono {getattr(handler, '__name__', repr(handler))} "
                f"para evento {type(event).__name__} (id={event.event_id}): {exc}",
                exc_info=True,
            )

    def __await__(self) -> Generator[Any, None, None]:
        async def _runner() -> None:
            if self._tasks:
                await asyncio.gather(*self._tasks)
            else:
                for handler in self._async_handlers:
                    await self._safe_invoke_async(handler, self._event)

        return _runner().__await__()



class EventBus:
    """Bus de eventos tipado, desacoplado y asíncrono para JESSYCA 4.0."""

    def __init__(self) -> None:
        # Mapeo: clase de evento -> lista de funciones handler
        self._subscribers: dict[type[Event], list[HandlerType]] = {}

    def subscribe(self, event_type: type[T], handler: Callable[[T], Any]) -> None:
        """Suscribe un handler (síncrono o asíncrono) a un tipo específico de evento.

        Args:
            event_type: Clase de evento (subclase de Event).
            handler: Función síncrona o corrutina que recibe la instancia del evento.
        """
        if not inspect.isclass(event_type) or not issubclass(event_type, Event):
            raise TypeError(
                f"event_type debe ser una subclase de Event, se recibió: {event_type}"
            )

        if not callable(handler):
            raise TypeError(f"El handler debe ser invocable (callable), se recibió: {handler}")

        if event_type not in self._subscribers:
            self._subscribers[event_type] = []

        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)
            logger.debug(
                f"EVENT BUS: Suscrito handler {getattr(handler, '__name__', repr(handler))} "
                f"a {event_type.__name__}"
            )

    def unsubscribe(self, event_type: type[T], handler: Callable[[T], Any]) -> bool:
        """Cancela la suscripción de un handler para un tipo específico de evento.

        Args:
            event_type: Clase de evento a des-suscribir.
            handler: Función callback a remover.

        Returns:
            bool: True si la suscripción fue encontrada y eliminada, False de lo contrario.
        """
        if event_type not in self._subscribers:
            return False

        handlers = self._subscribers[event_type]
        if handler in handlers:
            handlers.remove(handler)
            if not handlers:
                del self._subscribers[event_type]
            logger.debug(
                f"EVENT BUS: Des-suscrito handler {getattr(handler, '__name__', repr(handler))} "
                f"de {event_type.__name__}"
            )
            return True
        return False

    def publish(self, event: Event) -> PublishAwaitable:
        """Publica un evento para todos los suscriptores compatibles.

        Ejecuta de inmediato los suscriptores síncronos y retorna un objeto awaitable
        para coordinar los suscriptores asíncronos si se utiliza `await`.
        Si un suscriptor falla, se registra la excepción y el resto continúa ejecutándose.

        Args:
            event: Instancia de Event a publicar.

        Returns:
            PublishAwaitable: Objeto awaitable compatible con await y llamadas síncronas.
        """
        if not isinstance(event, Event):
            raise TypeError(f"Se esperaba una instancia de Event, se recibió: {type(event)}")

        matching_handlers = self._resolve_handlers(type(event))
        logger.debug(
            f"EVENT BUS: Publicado {type(event).__name__} | Suscriptores coincidentes: {len(matching_handlers)}"
        )

        async_handlers: list[Callable[[Any], Coroutine[Any, Any, Any]]] = []

        for handler in matching_handlers:
            if inspect.iscoroutinefunction(handler):
                async_handlers.append(handler)
            else:
                self._safe_invoke_sync(handler, event)

        return PublishAwaitable(event, async_handlers)

    async def publish_async(self, event: Event) -> None:
        """Publica un evento de forma explícitamente asíncrona garantizando la espera de todos los handlers."""
        await self.publish(event)

    def publish_sync(self, event: Event) -> None:
        """Publica un evento sincrónicamente, ejecutando handlers async en un bucle temporal si es necesario."""
        awaitable = self.publish(event)
        if awaitable._async_handlers and not awaitable._tasks:
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    return
            except RuntimeError:
                asyncio.run(self.publish_async(event))


    def _safe_invoke_sync(self, handler: HandlerType, event: Event) -> None:
        """Invoca un handler síncrono aislando posibles excepciones."""
        try:
            handler(event)
        except Exception as exc:
            logger.error(
                f"EVENT BUS: Excepción en subscriber síncrono {getattr(handler, '__name__', repr(handler))} "
                f"para evento {type(event).__name__} (id={event.event_id}): {exc}",
                exc_info=True,
            )

    def _resolve_handlers(self, event_class: type[Event]) -> list[HandlerType]:
        """Obtiene la lista de suscriptores registrados para la clase del evento o cualquiera de sus superclases."""
        resolved: list[HandlerType] = []
        for registered_type, handlers in self._subscribers.items():
            if issubclass(event_class, registered_type):
                for h in handlers:
                    if h not in resolved:
                        resolved.append(h)
        return resolved

    def get_subscriber_count(self, event_type: type[Event] | None = None) -> int:
        """Devuelve el total de suscriptores registrados globalmente o para un tipo específico de evento."""
        if event_type is not None:
            return len(self._subscribers.get(event_type, []))
        return sum(len(handlers) for handlers in self._subscribers.values())

    def clear(self, event_type: type[Event] | None = None) -> None:
        """Elimina todos los suscriptores registrados o los de un tipo de evento específico."""
        if event_type is not None:
            self._subscribers.pop(event_type, None)
            logger.debug(f"EVENT BUS: Limpiados suscriptores de {event_type.__name__}")
        else:
            self._subscribers.clear()
            logger.debug("EVENT BUS: Todos los suscriptores han sido eliminados.")


# Instancia Singleton Global para JESSYCA 4.0
_global_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Obtiene la instancia Singleton del Event Bus tipado de JESSYCA 4.0."""
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus


def reset_event_bus() -> None:
    """Reinicia la instancia Singleton global (útil para pruebas unitarias)."""
    global _global_bus
    _global_bus = None
