"""Repositorio de Dominio para Consulta de Experiencias (repository.py - Fase 57).

Proporciona operaciones de alto nivel para consultar, filtrar y analizar
experiencias almacenadas sin acoplarse a la tecnología de base de datos.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.experience.experience_store import IExperienceStore, InMemoryExperienceStore
from core.experience.models import Experience, ExperienceCategory
from core.logger import get_logger

logger = get_logger("jessyca.experience.repository")


@runtime_checkable
class IExperienceRepository(Protocol):
    """Protocolo de interfaz para el repositorio de experiencias."""

    @property
    def store(self) -> IExperienceStore: ...
    def save_experience(self, experience: Experience) -> None: ...
    def get_by_id(self, experience_id: str) -> Experience | None: ...
    def get_by_session(self, session_id: str, limit: int = 50) -> list[Experience]: ...
    def get_by_correlation_id(self, correlation_id: str) -> list[Experience]: ...
    def get_by_category(self, category: ExperienceCategory | str, limit: int = 50) -> list[Experience]: ...
    def get_recent(self, limit: int = 20) -> list[Experience]: ...
    def get_failed_experiences(self, limit: int = 50) -> list[Experience]: ...
    def get_user_corrections(self, limit: int = 50) -> list[Experience]: ...
    def count_experiences(self, category: ExperienceCategory | str | None = None) -> int: ...


class ExperienceRepository:
    """Implementación concreta del repositorio de experiencias."""

    def __init__(self, store: IExperienceStore | None = None) -> None:
        self._store = store or InMemoryExperienceStore()

    @property
    def store(self) -> IExperienceStore:
        return self._store

    def save_experience(self, experience: Experience) -> None:
        """Guarda la experiencia a través del almacén configurado."""
        self._store.save(experience)

    def get_by_id(self, experience_id: str) -> Experience | None:
        """Obtiene una experiencia individual por ID."""
        return self._store.get(experience_id)

    def get_by_session(self, session_id: str, limit: int = 50) -> list[Experience]:
        """Obtiene todas las experiencias asociadas a una sesión conversacional."""
        return self._store.query(session_id=session_id, limit=limit)

    def get_by_correlation_id(self, correlation_id: str) -> list[Experience]:
        """Obtiene experiencias vinculadas a un ID de correlación."""
        return self._store.query(correlation_id=correlation_id)

    def get_by_category(self, category: ExperienceCategory | str, limit: int = 50) -> list[Experience]:
        """Obtiene experiencias pertenecientes a una categoría específica."""
        return self._store.query(category=category, limit=limit)

    def get_recent(self, limit: int = 20) -> list[Experience]:
        """Obtiene las experiencias más recientes ordenadas por timestamp."""
        return self._store.query(limit=limit)

    def get_failed_experiences(self, limit: int = 50) -> list[Experience]:
        """Obtiene experiencias que registraron fallos de acción o verificación."""
        failed_actions = self._store.query(category=ExperienceCategory.ACTION_FAILED, limit=limit)
        failed_verifs = self._store.query(category=ExperienceCategory.VERIFICATION_FAILED, limit=limit)
        combined = failed_actions + failed_verifs
        return sorted(combined, key=lambda e: e.timestamp, reverse=True)[:limit]

    def get_user_corrections(self, limit: int = 50) -> list[Experience]:
        """Obtiene experiencias donde el usuario corrigió al asistente."""
        return self._store.query(category=ExperienceCategory.USER_CORRECTION, limit=limit)

    def count_experiences(self, category: ExperienceCategory | str | None = None) -> int:
        """Obtiene el número total de experiencias registradas."""
        return self._store.count(category=category)
