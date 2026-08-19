"""ObservabilityContext — Contexto de correlación propagado por ContextVar (Etapa 17.0).

Estrategia de propagación: contextvars.ContextVar (thread-safe, asyncio-safe).
El contexto se crea en el punto de entrada (MCPServer) y se propaga automáticamente
a todos los componentes que ejecuten en el mismo hilo/tarea asyncio.

Identificadores:
  correlation_id — raíz de la solicitud (une LOG + METRIC + TRACE + AUDIT)
  session_id     — sesión de usuario (persiste entre solicitudes)
  task_id        — tarea del ExecutionPlan (1 solicitud → N tareas)
  action_id      — acción atómica (1 tarea → N acciones)
  plugin_id      — ID del plugin activo, None si no aplica
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

F = TypeVar("F")

# ContextVar singleton: almacena el contexto de observabilidad del hilo/tarea actual
_CURRENT_CONTEXT: ContextVar[ObservabilityContext | None] = ContextVar(
    "jessyca_observability_context", default=None
)


@dataclass(frozen=True)
class ObservabilityContext:
    """Contexto inmutable de correlación para observabilidad.

    Todos los campos de identificación son inmutables una vez creados.
    Para cambiar task_id o action_id se crea un contexto hijo con derive().
    """

    correlation_id: str
    session_id: str
    component: str
    user_id: str = "system"
    task_id: str | None = None
    action_id: str | None = None
    plugin_id: str | None = None
    initiated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def derive(
        self,
        component: str | None = None,
        task_id: str | None = None,
        action_id: str | None = None,
        plugin_id: str | None = None,
    ) -> "ObservabilityContext":
        """Crea un contexto hijo heredando los IDs del padre y sobreescribiendo los indicados."""
        return ObservabilityContext(
            correlation_id=self.correlation_id,
            session_id=self.session_id,
            component=component or self.component,
            user_id=self.user_id,
            task_id=task_id if task_id is not None else self.task_id,
            action_id=action_id if action_id is not None else self.action_id,
            plugin_id=plugin_id if plugin_id is not None else self.plugin_id,
            initiated_at=self.initiated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """Retorna representación serializable segura (sin datos sensibles)."""
        return {
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "action_id": self.action_id,
            "plugin_id": self.plugin_id,
            "component": self.component,
            "user_id": self.user_id,
            "initiated_at": self.initiated_at.isoformat(),
        }

    @classmethod
    def create(
        cls,
        session_id: str,
        component: str,
        user_id: str = "system",
        correlation_id: str | None = None,
        task_id: str | None = None,
        action_id: str | None = None,
        plugin_id: str | None = None,
    ) -> "ObservabilityContext":
        """Crea un nuevo contexto de observabilidad generando un CorrelationId fresco."""
        return cls(
            correlation_id=correlation_id or str(uuid.uuid4()),
            session_id=session_id,
            component=component,
            user_id=user_id,
            task_id=task_id,
            action_id=action_id,
            plugin_id=plugin_id,
        )

    @classmethod
    def create_root(
        cls,
        session_id: str | None = None,
        component: str = "system",
        user_id: str = "system",
    ) -> "ObservabilityContext":
        """Crea un contexto raíz de observabilidad generando todos los IDs necesarios."""
        return cls.create(
            session_id=session_id or str(uuid.uuid4()),
            component=component,
            user_id=user_id,
        )


def get_current_context() -> ObservabilityContext | None:
    """Obtiene el contexto de observabilidad del hilo/tarea actual, o None si no está configurado."""
    return _CURRENT_CONTEXT.get(None)


def set_current_context(ctx: ObservabilityContext) -> Token[ObservabilityContext | None]:
    """Establece el contexto de observabilidad en el hilo/tarea actual.

    Retorna un Token que permite restaurar el contexto anterior.
    """
    return _CURRENT_CONTEXT.set(ctx)


def reset_context(token: Token[ObservabilityContext | None]) -> None:
    """Restaura el contexto de observabilidad previo usando el token retornado por set_current_context."""
    _CURRENT_CONTEXT.reset(token)


def run_with_context(ctx: ObservabilityContext, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Ejecuta func con el ObservabilityContext dado activo, restaurando el anterior al finalizar."""
    token = set_current_context(ctx)
    try:
        return func(*args, **kwargs)
    finally:
        reset_context(token)


def get_or_create_context(
    component: str,
    session_id: str | None = None,
    user_id: str = "system",
) -> ObservabilityContext:
    """Obtiene el contexto actual o crea uno raíz si no existe ninguno."""
    ctx = get_current_context()
    if ctx is not None:
        return ctx.derive(component=component)
    return ObservabilityContext.create_root(
        session_id=session_id,
        component=component,
        user_id=user_id,
    )
