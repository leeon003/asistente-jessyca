"""Gestor de Expiración y Ciclo de Vida Temporal de Memoria (memory_expiration.py - Fase 21: Memory Intelligence).

Permite almacenar memorias efímeras con tiempo de vida determinado (TTL) y garantiza que
datos caducados no contaminen el contexto de los agentes ni la inferencia del modelo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.logger import get_logger
from core.memory.memory_entry import MemoryEntry

logger = get_logger("jessyca.memory.expiration")


class MemoryExpirationManager:
    """Administrador de políticas de expiración y purga de memorias temporales."""

    @staticmethod
    def calculate_expiration_time(ttl_seconds: float | int) -> datetime:
        """Calcula la fecha y hora absoluta de expiración a partir de un TTL en segundos."""
        safe_ttl = max(1.0, float(ttl_seconds))
        return datetime.now(UTC) + timedelta(seconds=safe_ttl)

    @staticmethod
    def is_expired(entry: MemoryEntry, reference_time: datetime | None = None) -> bool:
        """Determina si una entrada de memoria ha superado su fecha de expiración."""
        if entry.expires_at is None:
            return False
        ref = reference_time or datetime.now(UTC)
        return ref > entry.expires_at

    @classmethod
    def filter_active(cls, entries: list[MemoryEntry] | tuple[MemoryEntry, ...]) -> list[MemoryEntry]:
        """Filtra y retorna únicamente las entradas que no han expirado."""
        now = datetime.now(UTC)
        return [e for e in entries if not cls.is_expired(e, reference_time=now)]

    @classmethod
    def find_expired(cls, entries: list[MemoryEntry] | tuple[MemoryEntry, ...]) -> list[MemoryEntry]:
        """Identifica todas las entradas que ya han caducado."""
        now = datetime.now(UTC)
        return [e for e in entries if cls.is_expired(e, reference_time=now)]
