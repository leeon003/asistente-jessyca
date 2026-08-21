"""Gestor del ciclo de vida de modelos LLM (ModelLifecycleManager - Fase 3: Model Manager + VRAM Governor).

Controla la carga (load), descarga (unload), precalentamiento (warmup) y monitorización de salud (health check)
de modelos LLM en Ollama, coordinado con VRAMGovernor para prevenir saturación de VRAM en hardware acotado.

GARANTÍA DE SEGURIDAD Y CONCURRENCIA:
- Concurrencia controlada con threading.RLock (cero race conditions).
- Prevención de cargas simultáneas innecesarias o duplicadas.
- NO ejecuta herramientas de usuario ni modifica políticas de seguridad.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar

import requests

from core.llm.exceptions import (
    InferenceError,
    ModelNotFoundError,
    ProviderConnectionError,
    ProviderTimeoutError,
)
from core.llm.model_registry import ModelRegistry
from core.llm.vram_manager import VRAMGovernor
from core.logger import get_logger

logger = get_logger("jessyca.llm.lifecycle")


class ModelStatus(StrEnum):
    """Estados del ciclo de vida de un modelo LLM."""

    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    UNLOADING = "unloading"
    ERROR = "error"


@dataclass(frozen=True)
class LoadedModelInfo:
    """Información inmutable sobre el estado de residencia de un modelo."""

    model_name: str
    status: ModelStatus
    vram_usage_mb: int
    last_used_timestamp: float
    load_duration_ms: float = 0.0


class ModelLifecycleManager:
    """Administrador thread-safe del ciclo de vida y residencia de modelos en VRAM."""

    _instance: ClassVar[ModelLifecycleManager | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        host: str | None = None,
        registry: ModelRegistry | None = None,
        vram_governor: VRAMGovernor | None = None,
        post_fn: Callable[..., Any] | None = None,
        get_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._load_lock = threading.Lock()  # Serializa las operaciones de carga/descarga pesadas
        env_host = os.getenv("OLLAMA_HOST")
        resolved_host = host if host else (env_host if env_host else "http://localhost:11434")
        self.host = str(resolved_host).rstrip("/")
        self._registry = registry or ModelRegistry.get_instance()
        self._vram_governor = vram_governor or VRAMGovernor.get_instance()
        self._post_fn = post_fn
        self._get_fn = get_fn
        self._model_states: dict[str, ModelStatus] = {}
        self._active_model: str | None = None

    @classmethod
    def get_instance(cls) -> ModelLifecycleManager:
        """Obtiene la instancia singleton global del gestor de ciclo de vida."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = ModelLifecycleManager()
            return cls._instance

    # ─── MÉTODOS DE CICLO DE VIDA ───

    def load_model(
        self,
        model_name: str,
        warmup: bool = True,
        timeout_seconds: float = 60.0,
    ) -> bool:
        """Carga un modelo en VRAM. Si el presupuesto es insuficiente, desaloja automáticamente modelos LRU."""
        # 1. Validar existencia del perfil en el catálogo
        profile = self._registry.get(model_name)
        resolved_name = profile.name

        with self._load_lock:
            with self._lock:
                # Comprobar si ya está listo
                if self._model_states.get(resolved_name) == ModelStatus.READY:
                    self._active_model = resolved_name
                    self._vram_governor.touch_model(resolved_name, time.time())
                    logger.debug(f"[MODEL LIFECYCLE] Modelo '{resolved_name}' ya está en memoria VRAM.")
                    return True

                self._model_states[resolved_name] = ModelStatus.LOADING

            # 2. Planificar y ejecutar desalojos si la VRAM es insuficiente
            evictions = self._vram_governor.calculate_eviction_plan(profile)
            for evict_name in evictions:
                logger.info(f"[MODEL LIFECYCLE] Desalojando '{evict_name}' para liberar VRAM...")
                self.unload_model(evict_name, timeout_seconds=15.0)

            # 3. Invocar a Ollama para cargar / precalentar el modelo en memoria
            start_time = time.perf_counter()
            url = f"{self.host}/api/generate"
            payload: Any = {
                "model": resolved_name,
                "prompt": "ping" if warmup else "",
                "stream": False,
                "keep_alive": "10m",
            }
            post_call = self._post_fn if self._post_fn is not None else requests.post

            try:
                resp = post_call(url, json=payload, timeout=timeout_seconds)
                if hasattr(resp, "raise_for_status"):
                    resp.raise_for_status()
            except requests.exceptions.ConnectionError as e:
                with self._lock:
                    self._model_states[resolved_name] = ModelStatus.ERROR
                raise ProviderConnectionError("ollama", self.host, str(e)) from e
            except requests.exceptions.Timeout as e:
                with self._lock:
                    self._model_states[resolved_name] = ModelStatus.ERROR
                raise ProviderTimeoutError("ollama", timeout_seconds) from e
            except Exception as e:
                with self._lock:
                    self._model_states[resolved_name] = ModelStatus.ERROR
                raise InferenceError(f"Error al cargar el modelo '{resolved_name}': {e}") from e

            duration_ms = (time.perf_counter() - start_time) * 1000.0

            # 4. Registrar en el gobernador y actualizar estado
            with self._lock:
                self._model_states[resolved_name] = ModelStatus.READY
                self._active_model = resolved_name
                self._vram_governor.register_loaded(
                    model_name=resolved_name,
                    vram_mb=profile.vram_estimate_mb or 4000,
                    priority=profile.priority,
                    timestamp=time.time(),
                )
                logger.info(
                    f"[MODEL LIFECYCLE] Modelo '{resolved_name}' cargado con éxito en {duration_ms:.1f}ms."
                )
            return True

    def unload_model(
        self,
        model_name: str,
        timeout_seconds: float = 15.0,
    ) -> bool:
        """Descarga un modelo liberando inmediatamente su memoria VRAM."""
        try:
            profile = self._registry.get(model_name)
            resolved_name = profile.name
        except ModelNotFoundError:
            resolved_name = model_name

        with self._lock:
            self._model_states[resolved_name] = ModelStatus.UNLOADING

        # Enviar petición con keep_alive: 0 para que Ollama libere la VRAM
        url = f"{self.host}/api/generate"
        payload: Any = {
            "model": resolved_name,
            "prompt": "",
            "keep_alive": 0,
        }
        post_call = self._post_fn if self._post_fn is not None else requests.post

        try:
            resp = post_call(url, json=payload, timeout=timeout_seconds)
            if hasattr(resp, "raise_for_status"):
                resp.raise_for_status()
        except Exception as e:
            logger.warning(f"[MODEL LIFECYCLE] Error no fatal al descargar '{resolved_name}': {e}")

        with self._lock:
            self._model_states[resolved_name] = ModelStatus.UNLOADED
            if self._active_model == resolved_name:
                self._active_model = None
            self._vram_governor.register_unloaded(resolved_name)
            logger.info(f"[MODEL LIFECYCLE] Modelo '{resolved_name}' descargado de VRAM.")
        return True

    def warmup_model(self, model_name: str) -> bool:
        """Precalienta un modelo enviando un prompt mínimo para compilar grafos en GPU."""
        return self.load_model(model_name=model_name, warmup=True)

    def health_check(self) -> dict[str, Any]:
        """Realiza un chequeo integral de salud del servidor Ollama y estado de VRAM."""
        get_call = self._get_fn if self._get_fn is not None else requests.get

        # 1. Consultar modelos instalados en disco
        installed_models: list[str] = []
        server_ok = False
        try:
            resp_tags = get_call(f"{self.host}/api/tags", timeout=2.0)
            if hasattr(resp_tags, "status_code") and resp_tags.status_code == 200:
                server_ok = True
                data = resp_tags.json() if hasattr(resp_tags, "json") else {}
                installed_models = [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            server_ok = False

        # 2. Consultar modelos residentes en VRAM
        ps_models: list[dict[str, Any]] = []
        if server_ok:
            try:
                resp_ps = get_call(f"{self.host}/api/ps", timeout=2.0)
                if hasattr(resp_ps, "status_code") and resp_ps.status_code == 200:
                    data_ps = resp_ps.json() if hasattr(resp_ps, "json") else {}
                    ps_models = data_ps.get("models", [])
            except Exception:
                pass

        budget = self._vram_governor.get_budget_report()

        with self._lock:
            return {
                "server_healthy": server_ok,
                "host": self.host,
                "active_model": self._active_model,
                "installed_models_on_disk": installed_models,
                "loaded_models_in_vram": list(self._vram_governor._loaded_models.keys()),
                "ollama_ps_models": ps_models,
                "vram_budget": {
                    "total_mb": budget.total_vram_mb,
                    "usable_mb": budget.usable_budget_mb,
                    "allocated_mb": budget.currently_allocated_mb,
                    "remaining_mb": budget.remaining_budget_mb,
                    "loaded_count": budget.loaded_models_count,
                },
            }

    def get_active_model(self) -> str | None:
        """Retorna el nombre del modelo actualmente activo."""
        with self._lock:
            return self._active_model

    def get_loaded_models(self) -> list[str]:
        """Retorna la lista de modelos actualmente registrados como residentes en VRAM."""
        with self._lock:
            return list(self._vram_governor._loaded_models.keys())

    def is_model_loaded(self, model_name: str) -> bool:
        """Comprueba si un modelo específico se encuentra cargado y listo."""
        with self._lock:
            try:
                profile = self._registry.get(model_name)
                resolved = profile.name
            except Exception:
                resolved = model_name
            return self._model_states.get(resolved) == ModelStatus.READY

    def reset(self) -> None:
        """Restablece el estado de los modelos en memoria."""
        with self._lock:
            self._model_states.clear()
            self._active_model = None
            self._vram_governor.reset()


def get_model_lifecycle_manager() -> ModelLifecycleManager:
    """Función de acceso directo a la instancia global de ModelLifecycleManager."""
    return ModelLifecycleManager.get_instance()
