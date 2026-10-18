"""Proveedor desacoplado para inferencia remota con NVIDIA Nemotron 3 Ultra (nemotron_provider.py).

Implementa el protocolo LLMProvider contra la API OpenAI-compatible de NVIDIA NIM / Cloud Functions.
GARANTÍAS ARQUITECTÓNICAS Y DE SEGURIDAD:
1. Feature flag estricto (NEMOTRON_ENABLED=false por defecto).
2. Protección de credenciales: La API key NUNCA se registra en logs ni excepciones.
3. Desacoplamiento total: No ejecuta herramientas ni acciones del sistema operativo.
4. Cero impacto en VRAM local: El modelo se consume de forma 100% remota.
5. Tolerancia a fallos: Timeouts granulares (connect/read), reintentos con backoff exponencial y mapeo de excepciones estándar.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import requests

from core.llm.exceptions import (
    InferenceError,
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
)
from core.llm.inference import InferenceRequest, InferenceResponse, LLMProvider
from core.logger import get_logger

logger = get_logger("jessyca.llm.nemotron")

DEFAULT_NEMOTRON_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NEMOTRON_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
DEFAULT_NEMOTRON_TIMEOUT = 30.0
DEFAULT_NEMOTRON_CONNECT_TIMEOUT = 5.0
DEFAULT_NEMOTRON_MAX_RETRIES = 2


class NemotronProvider(LLMProvider):
    """Proveedor concreto para consumir NVIDIA Nemotron 3 Ultra vía API remota OpenAI-compatible."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        enabled: bool | None = None,
        timeout_seconds: float | None = None,
        connect_timeout_seconds: float | None = None,
        max_retries: int | None = None,
        post_fn: Callable[..., Any] | None = None,
        get_fn: Callable[..., Any] | None = None,
    ) -> None:
        # Resolución de habilitación por Feature Flag (argumento > os.environ > AppSettings > fallback)
        if enabled is not None:
            self.enabled = bool(enabled)
        elif "NEMOTRON_ENABLED" in os.environ:
            env_enabled = os.environ["NEMOTRON_ENABLED"].strip().lower()
            self.enabled = env_enabled in ("true", "1", "yes", "on")
        else:
            try:
                from config.manager import get_settings
                self.enabled = bool(get_settings().NEMOTRON_ENABLED)
            except Exception:
                self.enabled = False

        # Resolución de API Key (argumento > os.environ > AppSettings > fallback)
        if api_key is not None:
            raw_key = api_key
        elif "NEMOTRON_API_KEY" in os.environ:
            raw_key = os.environ["NEMOTRON_API_KEY"]
        else:
            try:
                from config.manager import get_settings
                raw_key = get_settings().NEMOTRON_API_KEY
            except Exception:
                raw_key = ""
        self.api_key = str(raw_key).strip()

        # Configuración de URLs y modelo
        if base_url is not None:
            resolved_base = base_url
        elif "NEMOTRON_BASE_URL" in os.environ:
            resolved_base = os.environ["NEMOTRON_BASE_URL"]
        else:
            try:
                from config.manager import get_settings
                resolved_base = get_settings().NEMOTRON_BASE_URL
            except Exception:
                resolved_base = DEFAULT_NEMOTRON_BASE_URL
        self.base_url = str(resolved_base).rstrip("/")

        if model_name is not None:
            resolved_model = model_name
        elif "NEMOTRON_MODEL" in os.environ:
            resolved_model = os.environ["NEMOTRON_MODEL"]
        else:
            try:
                from config.manager import get_settings
                resolved_model = get_settings().NEMOTRON_MODEL
            except Exception:
                resolved_model = DEFAULT_NEMOTRON_MODEL
        self.model_name = str(resolved_model).strip()

        # Timeouts y reintentos
        if timeout_seconds is not None:
            resolved_timeout = timeout_seconds
        elif "NEMOTRON_TIMEOUT_SECONDS" in os.environ:
            resolved_timeout = os.environ["NEMOTRON_TIMEOUT_SECONDS"]
        else:
            try:
                from config.manager import get_settings
                resolved_timeout = get_settings().NEMOTRON_TIMEOUT_SECONDS
            except Exception:
                resolved_timeout = DEFAULT_NEMOTRON_TIMEOUT
        self.timeout_seconds = float(resolved_timeout)

        if connect_timeout_seconds is not None:
            resolved_connect = connect_timeout_seconds
        elif "NEMOTRON_CONNECT_TIMEOUT_SECONDS" in os.environ:
            resolved_connect = os.environ["NEMOTRON_CONNECT_TIMEOUT_SECONDS"]
        else:
            try:
                from config.manager import get_settings
                resolved_connect = get_settings().NEMOTRON_CONNECT_TIMEOUT_SECONDS
            except Exception:
                resolved_connect = DEFAULT_NEMOTRON_CONNECT_TIMEOUT
        self.connect_timeout_seconds = float(resolved_connect)

        if max_retries is not None:
            resolved_retries = max_retries
        elif "NEMOTRON_MAX_RETRIES" in os.environ:
            resolved_retries = os.environ["NEMOTRON_MAX_RETRIES"]
        else:
            try:
                from config.manager import get_settings
                resolved_retries = get_settings().NEMOTRON_MAX_RETRIES
            except Exception:
                resolved_retries = DEFAULT_NEMOTRON_MAX_RETRIES
        self.max_retries = int(resolved_retries)

        # Inyección de transporte HTTP para pruebas unitarias deterministas
        self._post_fn = post_fn
        self._get_fn = get_fn
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        """Obtiene o crea de forma perezosa una sesión HTTP reutilizable con connection pooling."""
        if self._session is None:
            sess = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
            sess.mount("https://", adapter)
            sess.mount("http://", adapter)
            self._session = sess
        return self._session

    def close(self) -> None:
        """Cierra la sesión HTTP persistente liberando conexiones subyacentes."""
        if self._session is not None:
            try:
                self._session.close()
            except Exception as e:
                logger.debug(f"[NEMOTRON] Error cerrando sesión HTTP: {e}")
            finally:
                self._session = None

    def __enter__(self) -> NemotronProvider:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    @property
    def endpoint(self) -> str:
        """Endpoint completo de Chat Completions según estándar OpenAI/NVIDIA."""
        return f"{self.base_url}/chat/completions"

    def is_available(self) -> bool:
        """Verifica de forma no bloqueante si el proveedor está habilitado, configurado y la API responde."""
        if not self.enabled:
            logger.debug("[NEMOTRON] is_available=False: Feature flag NEMOTRON_ENABLED está desactivado.")
            return False

        if not self.api_key:
            logger.debug("[NEMOTRON] is_available=False: NEMOTRON_API_KEY no está configurada.")
            return False

        models_endpoint = f"{self.base_url}/models"
        if self._get_fn is not None:
            get_callable = self._get_fn
        elif hasattr(requests.get, "mock_calls"):
            get_callable = requests.get
        else:
            get_callable = self._get_session().get

        try:
            resp = get_callable(
                models_endpoint,
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                timeout=(self.connect_timeout_seconds, min(5.0, self.timeout_seconds)),
            )
            return bool(getattr(resp, "status_code", 0) == 200)
        except Exception as e:
            logger.warning(f"[NEMOTRON] Comprobación de salud fallida contra {self.base_url}: {type(e).__name__}")
            return False

    def generate(self, request: InferenceRequest) -> InferenceResponse:
        """Ejecuta una petición de inferencia contra la API de NVIDIA Nemotron 3 Ultra."""
        if not self.enabled:
            raise ProviderError(
                message="El proveedor remoto Nemotron está desactivado (NEMOTRON_ENABLED=false).",
                code="NEMOTRON_DISABLED",
            )

        if not self.api_key:
            raise ProviderError(
                message="NEMOTRON_API_KEY no se encuentra configurada en el entorno.",
                code="MISSING_API_KEY",
            )

        if not request.prompt or not isinstance(request.prompt, str):
            raise InferenceError("El prompt de inferencia no puede estar vacío.")

        resolved_model = request.model_name or self.model_name

        # Construcción del historial de mensajes estilo OpenAI
        messages: list[dict[str, Any]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})

        user_content: Any = request.prompt
        # Soporte multimodal opcional si se proporcionaron imágenes en base64
        if request.images:
            content_list: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
            for img in request.images:
                content_list.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img}"},
                })
            user_content = content_list

        messages.append({"role": "user", "content": user_content})

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "temperature": request.temperature,
            "stream": request.stream,
        }

        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        if request.extra_options:
            payload.update(request.extra_options)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        timeout_tuple = (self.connect_timeout_seconds, self.timeout_seconds)
        if self._post_fn is not None:
            post_callable = self._post_fn
        elif hasattr(requests.post, "mock_calls"):
            post_callable = requests.post
        else:
            post_callable = self._get_session().post

        # Resolver reintentos respetando explícitamente el valor 0 (evitar or que ignore 0)
        effective_max_retries = self.max_retries
        if request.extra_options and "max_retries" in request.extra_options:
            opt_retries = request.extra_options.get("max_retries")
            if opt_retries is not None:
                effective_max_retries = int(opt_retries)

        attempt = 0
        last_exception: Exception | None = None
        data: dict[str, Any] = {}
        start_time = time.perf_counter()

        while attempt <= effective_max_retries:
            attempt += 1
            try:
                resp = post_callable(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=timeout_tuple,
                )

                status_code = getattr(resp, "status_code", 200)

                # Control de códigos HTTP de autenticación
                if status_code in (401, 403):
                    logger.error(
                        f"[NEMOTRON] Error de autenticación HTTP {status_code} al consultar {self.endpoint} "
                        "(API key rechazada o sin permisos)."
                    )
                    raise InferenceError(
                        message=f"Autenticación denegada por NVIDIA API (HTTP {status_code}). Verifica tu NEMOTRON_API_KEY.",
                        code="AUTHENTICATION_FAILED",
                    )

                # Reintentos controlados para 429 (rate limit) o 5xx (server error)
                if status_code in (429, 500, 502, 503, 504):
                    if attempt <= effective_max_retries:
                        backoff = 0.5 * (2 ** (attempt - 1))
                        logger.warning(
                            f"[NEMOTRON] HTTP {status_code} recibido. Reintentando ({attempt}/{effective_max_retries}) en {backoff:.1f}s..."
                        )
                        time.sleep(backoff)
                        continue
                    else:
                        raise InferenceError(
                            message=f"NVIDIA API retornó código HTTP {status_code} tras {effective_max_retries} reintentos.",
                            code="HTTP_SERVER_ERROR",
                        )

                if hasattr(resp, "raise_for_status"):
                    resp.raise_for_status()

                data = resp.json() if hasattr(resp, "json") else {}
                break  # Petición exitosa

            except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.Timeout) as e:
                last_exception = e
                if attempt <= effective_max_retries:
                    backoff = 0.5 * (2 ** (attempt - 1))
                    logger.warning(f"[NEMOTRON] Timeout en intento {attempt}. Reintentando en {backoff:.1f}s...")
                    time.sleep(backoff)
                    continue
                logger.error(f"[NEMOTRON] Timeout definitivo ({self.timeout_seconds}s) consultando {self.endpoint}.")
                raise ProviderTimeoutError(
                    provider_name="nemotron",
                    timeout_seconds=self.timeout_seconds,
                ) from e

            except requests.exceptions.ConnectionError as e:
                last_exception = e
                if attempt <= effective_max_retries:
                    backoff = 0.5 * (2 ** (attempt - 1))
                    logger.warning(f"[NEMOTRON] Error de conexión en intento {attempt}. Reintentando en {backoff:.1f}s...")
                    time.sleep(backoff)
                    continue
                logger.error(f"[NEMOTRON] Fallo de conexión contra {self.base_url}.")
                raise ProviderConnectionError(
                    provider_name="nemotron",
                    host=self.base_url,
                    original_error=str(e),
                ) from e

            except (InferenceError, ProviderError):
                raise

            except Exception as e:
                # Errores de ejecución de herramientas o de MCP no deben confundirse ni reintentarse como inferencia
                from core.exceptions import MCPError, ToolExecutionError
                if isinstance(e, (ToolExecutionError, MCPError)):
                    raise
                logger.error(f"[NEMOTRON] Error no esperado durante inferencia remota: {type(e).__name__}: {e}")
                raise InferenceError(f"Error procesando inferencia remota con Nemotron: {e}") from e

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Extracción segura del contenido y tokens
        choices = data.get("choices", [])
        if not choices:
            raise InferenceError("Respuesta de la API de NVIDIA no contiene opciones válidas ('choices').")

        first_choice = choices[0]
        message_data = first_choice.get("message", {})
        content = message_data.get("content", "")

        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens") or usage.get("completion_tokens")

        # Logging estructurado y seguro (NUNCA exponer api_key ni headers)
        logger.info(
            f"[NEMOTRON INFERENCE] Modelo: '{resolved_model}' | Latencia: {duration_ms:.1f}ms | "
            f"Tokens: {total_tokens} | Status: OK"
        )

        return InferenceResponse(
            content=str(content),
            model_name=resolved_model,
            duration_ms=duration_ms,
            tokens_used=total_tokens,
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
        """Atajo de conveniencia para generar directamente texto a partir de un prompt."""
        req = InferenceRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            model_name=model_name or self.model_name,
            extra_options=options or {},
        )
        res = self.generate(req)
        return res.content
