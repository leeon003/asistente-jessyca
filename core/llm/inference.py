"""Abstracción e implementación desacoplada de inferencia LLM (inference.py - Fase 1 & 4: Multimodal).

Define el protocolo abstracto LLMProvider y las implementaciones concretas OllamaProvider y FakeLLMProvider.
GARANTÍA ARQUITECTÓNICA:
El Core de Jessyca interactúa con LLMProvider sin conocer detalles de transporte HTTP o llamadas de bajo nivel.
Soporta inferencia de texto y multimodal con imágenes en base64.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import requests

from core.llm.exceptions import (
    InferenceError,
    ProviderConnectionError,
    ProviderTimeoutError,
)
from core.llm.model_manager import ModelManager, get_model_manager
from core.logger import get_logger

logger = get_logger("jessyca.llm.inference")


@dataclass(frozen=True)
class InferenceRequest:
    """Solicitud tipada e inmutable de inferencia para un modelo LLM (texto o multimodal)."""

    prompt: str
    system_prompt: str | None = None
    model_name: str | None = None
    images: tuple[str, ...] = ()  # Lista inmutable de imágenes codificadas en Base64
    temperature: float = 0.1
    max_tokens: int | None = None
    stream: bool = False
    extra_options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "system_prompt": self.system_prompt,
            "model_name": self.model_name,
            "images_count": len(self.images),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": self.stream,
            "extra_options": dict(self.extra_options),
        }


@dataclass(frozen=True)
class InferenceResponse:
    """Respuesta estructurada e inmutable resultante de una inferencia LLM."""

    content: str
    model_name: str
    duration_ms: float = 0.0
    tokens_used: int | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "model_name": self.model_name,
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
            "success": self.success,
            "error_message": self.error_message,
        }


@runtime_checkable
class LLMProvider(Protocol):
    """Protocolo abstracto desacoplado para proveedores de inferencia LLM."""

    def generate(self, request: InferenceRequest) -> InferenceResponse:
        """Ejecuta la inferencia estructurada y retorna un InferenceResponse."""
        ...

    def generate_text(
        self,
        prompt: str,
        model_name: str | None = None,
        system_prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Método de conveniencia para generar directamente texto a partir de un prompt."""
        ...

    def is_available(self) -> bool:
        """Determina si el backend del proveedor está accesible y respondiendo."""
        ...


class OllamaProvider:
    """Proveedor concreto de inferencia mediante API HTTP REST de Ollama en localhost."""

    def __init__(
        self,
        host: str | None = None,
        model_manager: ModelManager | None = None,
        timeout_seconds: float = 60.0,
        post_fn: Callable[..., Any] | None = None,
    ) -> None:
        env_host = os.getenv("OLLAMA_HOST")
        resolved_host = host if host else (env_host if env_host else "http://localhost:11434")
        self.host = str(resolved_host).rstrip("/")
        self.model_manager = model_manager or get_model_manager()
        self.timeout_seconds = timeout_seconds
        self._post_fn = post_fn

    @property
    def endpoint(self) -> str:
        """Endpoint completo para la generación de inferencias."""
        return f"{self.host}/api/generate"

    def generate(self, request: InferenceRequest) -> InferenceResponse:
        """Ejecuta la petición de inferencia contra el endpoint /api/generate de Ollama."""
        if not request.prompt or not isinstance(request.prompt, str):
            raise InferenceError("El prompt de inferencia no puede estar vacío.")

        # Resolver el perfil del modelo a utilizar mediante ModelManager
        model_profile = self.model_manager.get_model(request.model_name)
        resolved_model = model_profile.name

        options_dict: dict[str, Any] = dict(model_profile.default_parameters)
        options_dict["temperature"] = request.temperature
        if request.max_tokens is not None:
            options_dict["num_predict"] = request.max_tokens
        if request.extra_options:
            options_dict.update(request.extra_options)

        payload: dict[str, Any] = {
            "model": resolved_model,
            "prompt": request.prompt,
            "stream": request.stream,
            "options": options_dict,
        }

        if request.system_prompt:
            payload["system"] = request.system_prompt

        if request.images:
            payload["images"] = list(request.images)

        start_time = time.perf_counter()
        post_callable = self._post_fn if self._post_fn is not None else requests.post

        try:
            resp = post_callable(self.endpoint, json=payload, timeout=self.timeout_seconds)
            if hasattr(resp, "raise_for_status"):
                resp.raise_for_status()
            data = resp.json() if hasattr(resp, "json") else {}
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"[OLLAMA PROVIDER] Fallo de conexión con {self.host}: {e}")
            raise ProviderConnectionError(
                provider_name="ollama",
                host=self.host,
                original_error=str(e),
            ) from e
        except requests.exceptions.Timeout as e:
            logger.warning(f"[OLLAMA PROVIDER] Timeout ({self.timeout_seconds}s) consultando {self.endpoint}")
            raise ProviderTimeoutError(
                provider_name="ollama",
                timeout_seconds=self.timeout_seconds,
            ) from e
        except Exception as e:
            logger.error(f"[OLLAMA PROVIDER] Error en llamada de inferencia a {self.endpoint}: {e}")
            raise InferenceError(f"Error durante inferencia con modelo '{resolved_model}': {e}") from e

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        response_text = str(data.get("response", ""))
        tokens_eval = data.get("eval_count")

        return InferenceResponse(
            content=response_text,
            model_name=resolved_model,
            duration_ms=duration_ms,
            tokens_used=tokens_eval,
            raw_response=data,
            success=True,
        )

    def generate_text(
        self,
        prompt: str,
        model_name: str | None = None,
        system_prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Atajo de conveniencia para obtener únicamente la cadena de respuesta."""
        req = InferenceRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            model_name=model_name,
            extra_options=options or {},
        )
        res = self.generate(req)
        return res.content

    def is_available(self) -> bool:
        """Comprueba de forma rápida si el servidor local de Ollama está activo."""
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=1.5)
            return resp.status_code == 200
        except Exception:
            return False


class FakeLLMProvider:
    """Proveedor sintético inmutable para pruebas unitarias deterministas sin red ni Ollama."""

    def __init__(
        self,
        default_response: str = '{"estado": "CLEAR", "respuesta_hablada": "Prueba completada", "skill": null}',
        model_manager: ModelManager | None = None,
    ) -> None:
        self.default_response = default_response
        self.model_manager = model_manager or get_model_manager()
        self.call_history: list[InferenceRequest] = []
        self._responses_queue: list[str] = []
        self.is_connected = True

    def queue_response(self, response_text: str) -> None:
        """Encola una respuesta para ser entregada en la siguiente invocación."""
        self._responses_queue.append(response_text)

    def generate(self, request: InferenceRequest) -> InferenceResponse:
        """Simula una respuesta inmediata determinista registrando la solicitud."""
        self.call_history.append(request)

        if not self.is_connected:
            raise ProviderConnectionError("fake_llm", "localhost:fake", "Simulated disconnection")

        resolved_model = request.model_name or self.model_manager.get_default_model_name()
        text = self._responses_queue.pop(0) if self._responses_queue else self.default_response

        return InferenceResponse(
            content=text,
            model_name=resolved_model,
            duration_ms=1.0,
            tokens_used=10,
            raw_response={"response": text, "fake": True},
            success=True,
        )

    def generate_text(
        self,
        prompt: str,
        model_name: str | None = None,
        system_prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        req = InferenceRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            model_name=model_name,
            extra_options=options or {},
        )
        return self.generate(req).content

    def is_available(self) -> bool:
        return self.is_connected
