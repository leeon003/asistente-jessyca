"""Sistema de Safe Caching para inferencias deterministas y consultas de sólo lectura (safe_caching.py - Fase 18).

Optimiza la latencia y el uso de recursos evitando inferencias y cómputos redundantes.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. SÓLO datos deterministas y no volátiles (ej. especificaciones estáticas, perfiles de modelos, resultados de herramientas READ_ONLY).
2. NUNCA se cachean contraseñas, tokens Bearer, cookies de sesión ni datos sensibles.
3. Expiración determinista por TTL y capacidad acotada con política de desalojo LRU.
4. El caché NO confiere permisos ni elude el SecurityPipeline.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.optimization.caching")

SENSITIVE_PATTERNS = (
    r"password",
    r"token",
    r"bearer\s+",
    r"cookie",
    r"secret",
    r"api[_-]?key",
    r"authorization",
)


@dataclass(frozen=True)
class CacheEntry:
    """Entrada inmutable en el Safe Cache."""

    key: str
    value: Any
    created_at: float
    ttl_seconds: float

    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl_seconds


class SafeCache:
    """Caché LRU thread-safe con validación estricta de no-sensibilidad y expiración TTL."""

    def __init__(self, max_entries: int = 256, default_ttl_seconds: float = 300.0) -> None:
        self._max_entries = max_entries
        self._default_ttl = default_ttl_seconds
        self._lock = threading.RLock()
        self._cache: dict[str, CacheEntry] = {}
        self._access_history: list[str] = []

    def get(self, query: str) -> Any | None:
        """Recupera un valor del caché si existe y no ha expirado."""
        cache_key = self._generate_key(query)
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is None:
                return None

            if entry.is_expired:
                del self._cache[cache_key]
                if cache_key in self._access_history:
                    self._access_history.remove(cache_key)
                logger.debug(f"[SAFE CACHE] Entrada expirada para clave '{cache_key[:8]}'")
                return None

            # Actualizar orden LRU
            if cache_key in self._access_history:
                self._access_history.remove(cache_key)
            self._access_history.append(cache_key)

            logger.debug(f"[SAFE CACHE HIT] Clave '{cache_key[:8]}'")
            return entry.value

    def set(self, query: str, value: Any, ttl_seconds: float | None = None) -> bool:
        """Almacena un resultado si y sólo si el contenido es seguro y no contiene secretos."""
        # 1. Comprobar que no contenga datos sensibles
        query_str = str(query)
        value_str = str(value)

        for pattern in SENSITIVE_PATTERNS:
            if re.search(pattern, query_str, re.IGNORECASE) or re.search(pattern, value_str, re.IGNORECASE):
                logger.warning("[SAFE CACHE DENY] Intento de cachear datos sensibles o credenciales bloqueado.")
                return False

        cache_key = self._generate_key(query)
        effective_ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl

        with self._lock:
            # Control de capacidad LRU
            if len(self._cache) >= self._max_entries and cache_key not in self._cache:
                if self._access_history:
                    lru_key = self._access_history.pop(0)
                    self._cache.pop(lru_key, None)

            entry = CacheEntry(
                key=cache_key,
                value=value,
                created_at=time.monotonic(),
                ttl_seconds=effective_ttl,
            )
            self._cache[cache_key] = entry
            if cache_key in self._access_history:
                self._access_history.remove(cache_key)
            self._access_history.append(cache_key)

            logger.debug(f"[SAFE CACHE SET] Guardado '{cache_key[:8]}' (TTL: {effective_ttl}s)")
            return True

    def invalidate(self, query: str) -> None:
        """Invalida explícitamente una entrada del caché."""
        cache_key = self._generate_key(query)
        with self._lock:
            self._cache.pop(cache_key, None)
            if cache_key in self._access_history:
                self._access_history.remove(cache_key)

    def clear(self) -> None:
        """Limpia la totalidad del caché."""
        with self._lock:
            self._cache.clear()
            self._access_history.clear()

    def size(self) -> int:
        """Retorna el número de elementos actualmente residentes en caché."""
        with self._lock:
            return len(self._cache)

    def _generate_key(self, query: str) -> str:
        """Genera un hash SHA-256 normalizado para la clave de consulta."""
        normalized = query.strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
