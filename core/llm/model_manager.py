"""Administrador de resolución y selección de modelos LLM (ModelManager - Fase 1: Multi-LLM Foundation).

Actúa como capa intermedia desacoplada entre el Core de Jessyca y el ModelRegistry.
Responsabilidad:
  - Resolver el modelo configurado o solicitado explícitamente.
  - Administrar el modelo predeterminado del sistema.
  - Consultar capacidades descriptivas sin acoplamiento a librerías de inferencia.
"""

from __future__ import annotations

import os
import threading
from typing import ClassVar

from core.llm.exceptions import ModelNotFoundError
from core.llm.model_profile import ModelProfile
from core.llm.model_registry import ModelRegistry
from core.logger import get_logger

logger = get_logger("jessyca.llm.manager")

# Modelo por defecto del sistema si no se especifica explícitamente
FALLBACK_DEFAULT_MODEL = "gemma4:e4b"


class ModelManager:
    """Administrador de selección explícita y resolución de perfiles de modelos LLM."""

    _instance: ClassVar[ModelManager | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        default_model_name: str | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._registry = registry or ModelRegistry.get_instance()
        # Resolución inicial del modelo por defecto (prioridad: argumento -> variable de entorno -> fallback)
        env_model = os.getenv("OLLAMA_MODEL")
        initial_default = default_model_name if default_model_name else (env_model if env_model else FALLBACK_DEFAULT_MODEL)
        self._default_model_name = str(initial_default).strip()

    @classmethod
    def get_instance(cls) -> ModelManager:
        """Obtiene la instancia singleton global del gestor de modelos."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = ModelManager()
            return cls._instance

    @property
    def registry(self) -> ModelRegistry:
        """Acceso de solo lectura al registro de modelos."""
        return self._registry

    def get_model(self, name: str | None = None) -> ModelProfile:
        """Resuelve y obtiene el ModelProfile solicitado o el modelo predeterminado si name es None."""
        with self._lock:
            target_name = (name.strip() if name and name.strip() else self._default_model_name)
            try:
                profile = self._registry.get(target_name)
                return profile
            except ModelNotFoundError:
                logger.error(
                    f"[MODEL MANAGER] El modelo '{target_name}' no se encuentra en el registro."
                )
                raise

    def set_default_model(self, name: str) -> None:
        """Establece el modelo predeterminado del sistema validando previamente su existencia en el catálogo."""
        with self._lock:
            clean_name = name.strip()
            if not self._registry.exists(clean_name):
                raise ModelNotFoundError(
                    model_name=clean_name,
                    details={"error": "No se puede establecer como predeterminado un modelo no registrado."},
                )
            self._default_model_name = clean_name
            logger.info(f"[MODEL MANAGER] Modelo predeterminado establecido a: '{clean_name}'")

    def get_default_model_name(self) -> str:
        """Retorna el identificador del modelo predeterminado actual."""
        with self._lock:
            return self._default_model_name

    def list_available_models(self) -> list[ModelProfile]:
        """Lista todos los perfiles de modelos disponibles en el catálogo."""
        return self._registry.list_models()

    def is_model_available(self, name: str) -> bool:
        """Comprueba si un modelo específico se encuentra registrado."""
        return self._registry.exists(name)


def get_model_manager() -> ModelManager:
    """Función de acceso directo a la instancia global de ModelManager."""
    return ModelManager.get_instance()
