"""Circuit Breaker para Aislamiento de Fallos en Componentes (Etapa 17.3).

Garantiza:
  - Transiciones deterministas: CLOSED -> OPEN -> HALF_OPEN -> CLOSED (o OPEN).
  - Umbral de fallos acotado (failure_threshold).
  - Periodo de enfriamiento (cooldown_seconds) antes de sondear en HALF_OPEN.
  - Thread-safe.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from core.logger import get_logger
from core.recovery.models import CircuitState

logger = get_logger("jessyca.recovery.circuit_breaker")


class CircuitBreakerOpenError(Exception):
    """Excepción lanzada cuando una operación es bloqueada porque el Circuit Breaker está en estado OPEN."""

    pass


class CircuitBreaker:
    """Implementación thread-safe del patrón Circuit Breaker para protección de subsistemas."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 10.0,
        half_open_success_threshold: int = 1,
    ) -> None:
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_seconds = max(0.001, cooldown_seconds)
        self.half_open_success_threshold = max(1, half_open_success_threshold)

        self._state: CircuitState = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._last_state_change_time: float = time.monotonic()
        self._lock = threading.RLock()

    @property
    def state(self) -> CircuitState:
        """Obtiene el estado actual del Circuit Breaker (evaluando posible transición a HALF_OPEN por cooldown)."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_state_change_time
                if elapsed >= self.cooldown_seconds:
                    logger.info(
                        f"[CIRCUIT BREAKER: {self.name}] Cooldown de {self.cooldown_seconds}s cumplido. "
                        "Transición de OPEN -> HALF_OPEN (permitiendo solicitud sonda)."
                    )
                    self._state = CircuitState.HALF_OPEN
                    self._last_state_change_time = time.monotonic()
                    self._consecutive_successes = 0
            return self._state

    def allow_request(self) -> bool:
        """Verifica si una solicitud puede ejecutarse a través del circuito."""
        current = self.state
        return current in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        """Registra una ejecución exitosa a través del circuito."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._consecutive_successes += 1
                if self._consecutive_successes >= self.half_open_success_threshold:
                    logger.info(
                        f"[CIRCUIT BREAKER: {self.name}] Solicitud sonda exitosa. "
                        "Transición de HALF_OPEN -> CLOSED (circuito recuperado)."
                    )
                    self._state = CircuitState.CLOSED
                    self._consecutive_failures = 0
                    self._last_state_change_time = time.monotonic()
            elif self._state == CircuitState.CLOSED:
                self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Registra un fallo en la ejecución a través del circuito."""
        with self._lock:
            self._consecutive_failures += 1

            if self._state == CircuitState.HALF_OPEN:
                logger.warning(
                    f"[CIRCUIT BREAKER: {self.name}] Falló solicitud sonda en HALF_OPEN. "
                    "Reabriendo circuito (HALF_OPEN -> OPEN)."
                )
                self._state = CircuitState.OPEN
                self._last_state_change_time = time.monotonic()
                self._consecutive_successes = 0

            elif self._state == CircuitState.CLOSED:
                if self._consecutive_failures >= self.failure_threshold:
                    logger.warning(
                        f"[CIRCUIT BREAKER: {self.name}] Umbral de fallos alcanzado ({self._consecutive_failures}/{self.failure_threshold}). "
                        "Abriendo circuito (CLOSED -> OPEN). Deteniendo solicitudes subsiguientes."
                    )
                    self._state = CircuitState.OPEN
                    self._last_state_change_time = time.monotonic()

    def reset(self) -> None:
        """Restablece el Circuit Breaker al estado CLOSED."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            self._last_state_change_time = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        """Obtiene un resumen estructurado del estado del Circuit Breaker."""
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "consecutive_failures": self._consecutive_failures,
                "failure_threshold": self.failure_threshold,
                "cooldown_seconds": self.cooldown_seconds,
            }
