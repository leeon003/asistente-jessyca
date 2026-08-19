"""Modelos de métricas para el canal METRIC (Etapa 17.0).

Define las tres primitivas estándar:
  Counter   — valor que solo incrementa (requests_total, errors_total)
  Histogram — distribución de valores numéricos (duration_ms, wait_ms)
  Gauge     — valor actual puntual (active_sessions, pending_confirmations)

Nomenclatura: jessyca_<subsistema>_<nombre>_<unidad>
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import inf
from typing import Any


@dataclass
class Counter:
    """Contador monotónicamente creciente. Thread-safe."""

    name: str
    help: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    _value: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def increment(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        if amount < 0:
            raise ValueError(f"Counter '{self.name}' no puede decrementarse (amount={amount})")
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        with self._lock:
            return self._value

    def reset(self) -> None:
        """Reset para uso en tests únicamente."""
        with self._lock:
            self._value = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "counter",
            "name": self.name,
            "help": self.help,
            "labels": self.labels,
            "value": self.value,
        }


# Buckets estándar en ms para histogramas de duración
DEFAULT_DURATION_BUCKETS_MS: list[float] = [
    1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0, inf
]


@dataclass
class Histogram:
    """Distribución de valores numéricos con buckets configurable. Thread-safe.

    Internamente mantiene conteos por bucket y suma/count para calcular media.
    Compatible con formato Prometheus (bucket + sum + count).
    """

    name: str
    help: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    buckets: list[float] = field(default_factory=lambda: list(DEFAULT_DURATION_BUCKETS_MS))

    _bucket_counts: dict[float, int] = field(default_factory=dict, init=False)
    _sum: float = field(default=0.0, init=False)
    _count: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        # Inicializar conteos a 0 para todos los buckets
        for b in self.buckets:
            self._bucket_counts[b] = 0

    def observe(self, value: float) -> None:
        """Registra una observación del valor en los buckets correspondientes."""
        with self._lock:
            self._sum += value
            self._count += 1
            for b in self.buckets:
                if value <= b:
                    self._bucket_counts[b] += 1

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    @property
    def sum(self) -> float:
        with self._lock:
            return self._sum

    @property
    def mean(self) -> float | None:
        with self._lock:
            return self._sum / self._count if self._count > 0 else None

    def reset(self) -> None:
        """Reset para uso en tests únicamente."""
        with self._lock:
            self._sum = 0.0
            self._count = 0
            for b in self.buckets:
                self._bucket_counts[b] = 0

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "type": "histogram",
                "name": self.name,
                "help": self.help,
                "labels": self.labels,
                "count": self._count,
                "sum": self._sum,
                "mean": self._sum / self._count if self._count > 0 else None,
                "buckets": {
                    str(b): c for b, c in sorted(self._bucket_counts.items())
                },
            }


@dataclass
class Gauge:
    """Valor numérico que puede subir y bajar. Thread-safe.

    Útil para: sessions_active, pending_confirmations, queue_size, emergency_stop_active.
    """

    name: str
    help: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    _value: float = field(default=0.0, init=False)
    _updated_at: datetime = field(default_factory=lambda: datetime.now(UTC), init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value
            self._updated_at = datetime.now(UTC)

    def increment(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount
            self._updated_at = datetime.now(UTC)

    def decrement(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value -= amount
            self._updated_at = datetime.now(UTC)

    @property
    def value(self) -> float:
        with self._lock:
            return self._value

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "type": "gauge",
                "name": self.name,
                "help": self.help,
                "labels": self.labels,
                "value": self._value,
                "updated_at": self._updated_at.isoformat(),
            }
