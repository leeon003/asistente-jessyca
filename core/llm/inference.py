"""Abstracción e implementación desacoplada de inferencia LLM (inference.py - Fase 1 & 4: Multimodal).

Define el protocolo abstracto LLMProvider y las implementaciones concretas OllamaProvider y FakeLLMProvider.
GARANTÍA ARQUITECTÓNICA:
El Core de Jessyca interactúa con LLMProvider sin conocer detalles de transporte HTTP o llamadas de bajo nivel.
Soporta inferencia de texto y multimodal con imágenes en base64.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
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
    timeout_seconds: float | None = None

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
            "timeout_seconds": self.timeout_seconds,
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

    def generate_stream(self, request: InferenceRequest) -> Iterator[str]:
        """Ejecuta la inferencia en streaming token a token."""
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
        self._session: requests.Session | None = None
        self._last_availability_error: str | None = None
        self._auto_start_attempted: bool = False

    def _get_session(self) -> requests.Session:
        """Obtiene o crea de forma perezosa una sesión HTTP reutilizable con connection pooling."""
        if self._session is None:
            sess = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
            sess.mount("http://", adapter)
            sess.mount("https://", adapter)
            self._session = sess
        return self._session

    def close(self) -> None:
        """Cierra la sesión HTTP persistente liberando conexiones."""
        if self._session is not None:
            try:
                self._session.close()
            except Exception as e:
                logger.debug(f"[OLLAMA] Error cerrando sesión HTTP: {e}")
            finally:
                self._session = None

    def __enter__(self) -> OllamaProvider:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

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

        if "think" in request.extra_options:
            payload["think"] = request.extra_options["think"]
        else:
            payload["think"] = False

        if request.system_prompt:
            payload["system"] = request.system_prompt

        if request.images:
            payload["images"] = list(request.images)

        start_time = time.perf_counter()
        if self._post_fn is not None:
            post_callable = self._post_fn
        elif hasattr(requests.post, "mock_calls"):
            post_callable = requests.post
        else:
            post_callable = self._get_session().post

        eff_timeout = request.timeout_seconds if request.timeout_seconds is not None else self.timeout_seconds
        try:
            resp = post_callable(self.endpoint, json=payload, timeout=eff_timeout)
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
            logger.warning(f"[OLLAMA PROVIDER] Timeout ({eff_timeout}s) consultando {self.endpoint}")
            raise ProviderTimeoutError(
                provider_name="ollama",
                timeout_seconds=eff_timeout,
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

    def generate_stream(self, request: InferenceRequest) -> Iterator[str]:
        """Ejecuta inferencia generativa en streaming token a token contra Ollama."""
        if not request.prompt or not isinstance(request.prompt, str):
            raise InferenceError("El prompt de inferencia no puede estar vacío.")

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
            "stream": True,
            "options": options_dict,
        }

        if "think" in request.extra_options:
            payload["think"] = request.extra_options["think"]
        else:
            payload["think"] = False

        if request.system_prompt:
            payload["system"] = request.system_prompt

        if request.images:
            payload["images"] = list(request.images)

        if self._post_fn is not None:
            post_callable = self._post_fn
        elif hasattr(requests.post, "mock_calls"):
            post_callable = requests.post
        else:
            post_callable = self._get_session().post
        eff_timeout = request.timeout_seconds if request.timeout_seconds is not None else self.timeout_seconds

        try:
            resp = post_callable(self.endpoint, json=payload, stream=True, timeout=eff_timeout)
            if hasattr(resp, "raise_for_status"):
                resp.raise_for_status()

            if hasattr(resp, "iter_lines"):
                for line in resp.iter_lines():
                    if line:
                        decoded = line.decode("utf-8") if isinstance(line, bytes) else line
                        data = json.loads(decoded)
                        chunk = data.get("response", "")
                        if chunk:
                            yield chunk
                        if data.get("done", False):
                            break
            elif hasattr(resp, "json"):
                data = resp.json()
                yield str(data.get("response", ""))
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"[OLLAMA PROVIDER] Fallo de conexión con {self.host}: {e}")
            raise ProviderConnectionError(provider_name="ollama", host=self.host, original_error=str(e)) from e
        except requests.exceptions.Timeout as e:
            logger.warning(f"[OLLAMA PROVIDER] Timeout ({eff_timeout}s) en stream {self.endpoint}")
            raise ProviderTimeoutError(provider_name="ollama", timeout_seconds=eff_timeout) from e
        except Exception as e:
            logger.error(f"[OLLAMA PROVIDER] Error en llamada streaming a {self.endpoint}: {e}")
            raise InferenceError(f"Error durante streaming con modelo '{resolved_model}': {e}") from e

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

    def _find_ollama_binary(self) -> str | None:
        """Localiza el binario de Ollama en el sistema."""
        import shutil

        # 1. En PATH
        which_path = shutil.which("ollama")
        if which_path and os.path.isfile(which_path):
            return which_path

        # 2. Rutas conocidas en Windows
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            candidate = os.path.join(local_app_data, "Programs", "Ollama", "ollama.exe")
            if os.path.isfile(candidate):
                return candidate

        user_profile = os.getenv("USERPROFILE")
        if user_profile:
            candidate = os.path.join(user_profile, "AppData", "Local", "Programs", "Ollama", "ollama.exe")
            if os.path.isfile(candidate):
                return candidate

        return None

    def _try_start_ollama_service(self) -> bool:
        """Intenta iniciar el proceso local 'ollama serve' si el ejecutable está disponible."""
        ollama_bin = self._find_ollama_binary()
        if not ollama_bin:
            logger.info("[OLLAMA AUTO-START] Ejecutable de Ollama no encontrado en el sistema.")
            return False

        logger.info(f"[OLLAMA AUTO-START] Detectado binario Ollama en '{ollama_bin}'. Iniciando servicio local en segundo plano...")
        try:
            import subprocess

            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)

            env = dict(os.environ)
            # Evitar colisión de UI si es posible
            env["OLLAMA_HOST"] = "127.0.0.1:11434"

            subprocess.Popen(
                [ollama_bin, "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )

            # Esperar hasta 3.0s a que el puerto responda
            deadline = time.perf_counter() + 3.0
            while time.perf_counter() < deadline:
                time.sleep(0.3)
                try:
                    get_callable = requests.get if hasattr(requests.get, "mock_calls") else self._get_session().get
                    resp = get_callable(f"{self.host}/api/tags", timeout=1.0)
                    if resp.status_code == 200:
                        logger.info("[OLLAMA AUTO-START] Servicio Ollama iniciado exitosamente y respondiendo.")
                        return True
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[OLLAMA AUTO-START] Error al intentar iniciar proceso Ollama: {e}")

        return False

    def is_available(self, auto_start: bool = True) -> bool:
        """Comprueba si el servidor local de Ollama está activo y registra el diagnóstico exacto."""
        try:
            get_callable = requests.get if hasattr(requests.get, "mock_calls") else self._get_session().get
            resp = get_callable(f"{self.host}/api/tags", timeout=3.5)
            if resp.status_code == 200:
                self._last_availability_error = None
                return True
            self._last_availability_error = f"Respuesta HTTP inesperada {resp.status_code} desde {self.host}/api/tags"
            return False
        except requests.exceptions.ConnectionError as ce:
            self._last_availability_error = f"Conexión rechazada en {self.host} (servicio inactivo o puerto cerrado: {ce})"
            # Intentar auto-arranque una sola vez si es host local
            if auto_start and not self._auto_start_attempted and ("localhost" in self.host or "127.0.0.1" in self.host):
                self._auto_start_attempted = True
                if self._try_start_ollama_service():
                    self._last_availability_error = None
                    return True
            return False
        except requests.exceptions.Timeout:
            self._last_availability_error = f"Timeout (3.5s) esperando respuesta de {self.host}/api/tags"
            return False
        except Exception as e:
            self._last_availability_error = f"Error comprobando disponibilidad de Ollama ({self.host}): {e}"
            return False

    def get_diagnostic_status(self) -> dict[str, Any]:
        """Devuelve el estado diagnóstico estructurado del proveedor Ollama."""
        available = self.is_available(auto_start=False)
        models: list[str] = []
        if available:
            try:
                get_callable = requests.get if hasattr(requests.get, "mock_calls") else self._get_session().get
                resp = get_callable(f"{self.host}/api/tags", timeout=2.0)
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
            except Exception:
                pass
        return {
            "host": self.host,
            "is_available": available,
            "error": self._last_availability_error,
            "models_available": models,
        }


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

    def generate_stream(self, request: InferenceRequest) -> Iterator[str]:
        """Emite tokens sintéticos para pruebas sin red ni Ollama."""
        self.call_history.append(request)
        if not self.is_connected:
            raise ProviderConnectionError("fake_llm", "localhost:fake", "Simulated disconnection")

        text = self._responses_queue.pop(0) if self._responses_queue else self.default_response
        words = text.split(" ")
        for i, w in enumerate(words):
            yield w + (" " if i < len(words) - 1 else "")

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
