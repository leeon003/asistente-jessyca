"""Catálogo centralizado y desacoplado de modelos LLM (ModelRegistry - Fase 1: Multi-LLM Foundation).

Mantiene el registro de perfiles de modelos disponibles en el sistema.
GARANTÍA ARQUITECTÓNICA:
El Registry NO ejecuta modelos, NO realiza inferencia, NO llama a Ollama ni ejecuta acciones del sistema.
"""

from __future__ import annotations

import threading
from typing import ClassVar

from core.llm.exceptions import DuplicateModelError, ModelNotFoundError
from core.llm.model_profile import ModelProfile
from core.logger import get_logger

logger = get_logger("jessyca.llm.registry")


def get_default_built_in_profiles() -> list[ModelProfile]:
    """Retorna los perfiles iniciales de los 5 modelos soportados en el catálogo."""
    return [
        ModelProfile(
            model_id="llama3.2",
            name="llama3.2",
            provider="ollama",
            capabilities=("completion", "tools"),
            context_length=131072,
            max_context_length=131072,
            input_modalities=("text",),
            output_modalities=("text",),
            vision=False,
            supports_vision=False,
            tool_calling=True,
            supports_tools=True,
            reasoning=False,
            priority=1,
            vram_estimate_mb=2500,
            enabled=True,
            default_parameters={"temperature": 0.1},
            description="Meta Llama 3.2 (3.2B) - Modelo ligero de baja latencia para diálogo y clasificación rápida.",
        ),
        ModelProfile(
            model_id="llama3.1",
            name="llama3.1",
            provider="ollama",
            capabilities=("completion", "tools"),
            context_length=131072,
            max_context_length=131072,
            input_modalities=("text",),
            output_modalities=("text",),
            vision=False,
            supports_vision=False,
            tool_calling=True,
            supports_tools=True,
            reasoning=False,
            priority=2,
            vram_estimate_mb=5500,
            enabled=True,
            default_parameters={"temperature": 0.1},
            description="Meta Llama 3.1 (8B) - Modelo general para instrucciones estructuradas y conversación.",
        ),
        ModelProfile(
            model_id="qwen3:8b",
            name="qwen3:8b",
            provider="ollama",
            capabilities=("completion", "tools", "thinking"),
            context_length=40960,
            max_context_length=40960,
            input_modalities=("text",),
            output_modalities=("text",),
            vision=False,
            supports_vision=False,
            tool_calling=True,
            supports_tools=True,
            reasoning=True,
            priority=3,
            vram_estimate_mb=5700,
            enabled=True,
            default_parameters={"temperature": 0.1},
            description="Qwen 3 (8B) - Modelo de alto rendimiento para razonamiento, código y análisis profundo.",
        ),
        ModelProfile(
            model_id="qwen3-vl:4b",
            name="qwen3-vl:4b",
            provider="ollama",
            capabilities=("completion", "tools", "thinking", "vision"),
            context_length=262144,
            max_context_length=262144,
            input_modalities=("text", "image"),
            output_modalities=("text",),
            vision=True,
            supports_vision=True,
            tool_calling=True,
            supports_tools=True,
            reasoning=False,
            priority=2,
            vram_estimate_mb=3600,
            enabled=True,
            default_parameters={"temperature": 0.1},
            description="Qwen 3 VL (4B) - Modelo multimodal con capacidad descriptiva para visión y texto.",
        ),
        ModelProfile(
            model_id="gemma4:e4b",
            name="gemma4:e4b",
            provider="ollama",
            capabilities=("completion", "tools", "thinking"),
            context_length=8192,
            max_context_length=8192,
            input_modalities=("text",),
            output_modalities=("text",),
            vision=False,
            supports_vision=False,
            tool_calling=True,
            supports_tools=True,
            reasoning=True,
            priority=1,
            vram_estimate_mb=5200,
            enabled=True,
            default_parameters={"temperature": 0.1},
            description="Gemma 4 (e4b) - Modelo de inferencia local para resolución estructurada de intenciones.",
        ),
    ]


class ModelRegistry:
    """Registro desacoplado y thread-safe de perfiles de modelos LLM."""

    _instance: ClassVar[ModelRegistry | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, load_defaults: bool = True) -> None:
        self._lock = threading.RLock()
        self._profiles: dict[str, ModelProfile] = {}
        if load_defaults:
            for profile in get_default_built_in_profiles():
                self._profiles[profile.name] = profile

    @classmethod
    def get_instance(cls) -> ModelRegistry:
        """Obtiene la instancia singleton global del registro."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = ModelRegistry(load_defaults=True)
            return cls._instance

    # ─── MÉTODOS DE INSTANCIA ───

    def register(self, profile: ModelProfile, overwrite: bool = False) -> None:
        """Registra un nuevo perfil de modelo en el catálogo."""
        with self._lock:
            if profile.name in self._profiles and not overwrite:
                raise DuplicateModelError(profile.name)
            self._profiles[profile.name] = profile
            logger.debug(f"[MODEL REGISTRY] Modelo registrado: '{profile.name}' (provider: {profile.provider})")

    def get(self, name: str) -> ModelProfile:
        """Obtiene el perfil inmutable del modelo solicitado. Lanza ModelNotFoundError si no existe."""
        with self._lock:
            clean_name = name.strip() if name else ""
            if clean_name not in self._profiles:
                # Búsqueda por alias o versión exacta (e.g. "llama3.1:latest" -> "llama3.1")
                base_name = clean_name.split(":")[0] if ":" in clean_name else clean_name
                if base_name in self._profiles:
                    return self._profiles[base_name]
                raise ModelNotFoundError(model_name=name)
            return self._profiles[clean_name]

    def exists(self, name: str) -> bool:
        """Comprueba si un modelo está registrado en el catálogo."""
        with self._lock:
            clean_name = name.strip() if name else ""
            if clean_name in self._profiles:
                return True
            base_name = clean_name.split(":")[0] if ":" in clean_name else clean_name
            return base_name in self._profiles

    def list_models(self) -> list[ModelProfile]:
        """Retorna una copia de la lista de todos los perfiles de modelos registrados."""
        with self._lock:
            return list(self._profiles.values())

    def list_names(self) -> list[str]:
        """Retorna la lista de identificadores de todos los modelos registrados."""
        with self._lock:
            return sorted(self._profiles.keys())

    def unregister(self, name: str) -> bool:
        """Elimina un modelo del registro. Retorna True si existía y fue removido."""
        with self._lock:
            clean_name = name.strip() if name else ""
            if clean_name in self._profiles:
                del self._profiles[clean_name]
                return True
            return False

    def reset(self) -> None:
        """Restablece el registro a su catálogo predeterminado de fábrica."""
        with self._lock:
            self._profiles.clear()
            for profile in get_default_built_in_profiles():
                self._profiles[profile.name] = profile

    # ─── MÉTODOS DE CONVENIENCIA A NIVEL DE CLASE ───

    @classmethod
    def register_profile(cls, profile: ModelProfile, overwrite: bool = False) -> None:
        cls.get_instance().register(profile, overwrite=overwrite)

    @classmethod
    def get_profile(cls, name: str) -> ModelProfile:
        return cls.get_instance().get(name)

    @classmethod
    def model_exists(cls, name: str) -> bool:
        return cls.get_instance().exists(name)

    @classmethod
    def list_all(cls) -> list[ModelProfile]:
        return cls.get_instance().list_models()

    @classmethod
    def list_all_names(cls) -> list[str]:
        return cls.get_instance().list_names()

    @classmethod
    def reset_registry(cls) -> None:
        cls.get_instance().reset()


# Funciones de conveniencia a nivel de módulo
def get_model_profile(name: str) -> ModelProfile:
    """Función de acceso directo para obtener un perfil desde el registro global."""
    return ModelRegistry.get_instance().get(name)
