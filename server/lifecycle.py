"""Gestor del ciclo de vida del servidor MCP (Subetapa 05.1).

Define los estados explícitos del ciclo de vida (STOPPED, INITIALIZING, RUNNING, STOPPING, FAILED)
y proporciona transiciones deterministas e hilos-seguras.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from enum import StrEnum

from core.logger import get_logger
from server.errors import MCPServerStateError

logger = get_logger("jessyca.server.lifecycle")


class LifecycleState(StrEnum):
    """Estados explícitos del ciclo de vida del servidor MCP."""

    STOPPED = "STOPPED"
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    FAILED = "FAILED"


class ServerLifecycleManager:
    """Gestor de estados y transiciones del ciclo de vida del servidor MCP."""

    def __init__(self) -> None:
        self._state: LifecycleState = LifecycleState.STOPPED
        self._start_time: datetime | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> LifecycleState:
        """Devuelve el estado actual del servidor."""
        with self._lock:
            return self._state

    @property
    def is_running(self) -> bool:
        """Indica si el servidor está en estado RUNNING."""
        with self._lock:
            return self._state == LifecycleState.RUNNING

    @property
    def uptime_seconds(self) -> float:
        """Devuelve los segundos transcurridos desde el inicio en estado RUNNING."""
        with self._lock:
            if self._state == LifecycleState.RUNNING and self._start_time is not None:
                return (datetime.now(UTC) - self._start_time).total_seconds()
            return 0.0

    def initialize(self) -> None:
        """Transición a INITIALIZING -> STOPPED (listo para iniciar). Idempotente si ya está listo."""
        with self._lock:
            if self._state == LifecycleState.RUNNING:
                logger.info("El servidor ya está en estado RUNNING. Inicialización omitida.")
                return
            if self._state == LifecycleState.INITIALIZING:
                logger.info("El servidor ya se encuentra inicializando.")
                return

            self._state = LifecycleState.INITIALIZING
            logger.info("Inicializando componentes del servidor MCP...")
            # Completar inicialización exitosa
            self._state = LifecycleState.STOPPED
            logger.info("Servidor MCP inicializado y listo en estado STOPPED.")

    def start(self) -> None:
        """Inicia el servidor cambiando el estado a RUNNING."""
        with self._lock:
            if self._state == LifecycleState.RUNNING:
                logger.warning("Intento de iniciar un servidor que ya está RUNNING.")
                return

            if self._state == LifecycleState.FAILED:
                raise MCPServerStateError(self._state.value, "start")

            self._state = LifecycleState.RUNNING
            self._start_time = datetime.now(UTC)
            logger.info("Servidor MCP iniciado exitosamente en estado RUNNING.")

    def shutdown(self) -> None:
        """Detiene el servidor cambiando el estado a STOPPED de manera segura."""
        with self._lock:
            if self._state == LifecycleState.STOPPED:
                logger.info("El servidor ya se encuentra en estado STOPPED.")
                return

            self._state = LifecycleState.STOPPING
            logger.info("Deteniendo el servidor MCP...")
            self._state = LifecycleState.STOPPED
            self._start_time = None
            logger.info("Servidor MCP detenido exitosamente en estado STOPPED.")

    def set_failed(self, error_message: str) -> None:
        """Marca el servidor en estado FAILED ante un error catastrófico."""
        with self._lock:
            self._state = LifecycleState.FAILED
            logger.error(f"Servidor MCP marcado como FAILED: {error_message}")
