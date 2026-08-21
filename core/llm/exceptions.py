"""Jerarquía de excepciones tipadas para la capa LLM en Jessyca Windows MCP (Fase 1: Multi-LLM Foundation).

Proporciona excepciones explícitas e independientes de proveedores para gestionar errores de modelos,
registro, inferencia, configuración y conectividad con proveedores locales y remotos.
"""

from __future__ import annotations

from typing import Any

from core.exceptions import MCPError


class LLMError(MCPError):
    """Excepción base para todos los errores en la capa LLM de Jessyca."""

    pass


class ModelNotFoundError(LLMError):
    """Excepción emitida cuando se intenta acceder o utilizar un modelo no registrado en el ModelRegistry."""

    def __init__(self, model_name: str, details: dict[str, Any] | None = None) -> None:
        msg = f"El modelo LLM '{model_name}' no se encuentra registrado en el ModelRegistry."
        extra = details or {}
        extra["requested_model"] = model_name
        super().__init__(message=msg, code="MODEL_NOT_FOUND", details=extra)


class ModelRegistrationError(LLMError):
    """Excepción emitida cuando ocurre un error al validar o registrar un ModelProfile."""

    pass


class DuplicateModelError(ModelRegistrationError):
    """Excepción emitida al intentar registrar un modelo con un identificador ya existente sin sobrescritura explícita."""

    def __init__(self, model_name: str) -> None:
        super().__init__(
            message=f"El modelo '{model_name}' ya se encuentra registrado en el catálogo.",
            code="DUPLICATE_MODEL",
            details={"model_name": model_name},
        )


class InferenceError(LLMError):
    """Excepción emitida cuando falla la ejecución de una inferencia LLM."""

    pass


class ProviderError(LLMError):
    """Excepción base para errores originados en el proveedor de inferencia (e.g. Ollama, FakeProvider)."""

    pass


class ProviderConnectionError(ProviderError):
    """Excepción emitida cuando no es posible establecer conexión con el endpoint del proveedor LLM."""

    def __init__(self, provider_name: str, host: str, original_error: str | None = None) -> None:
        msg = f"No se pudo conectar con el proveedor '{provider_name}' en '{host}'."
        details = {"provider": provider_name, "host": host}
        if original_error:
            details["original_error"] = original_error
        super().__init__(message=msg, code="PROVIDER_CONNECTION_ERROR", details=details)


class ProviderTimeoutError(ProviderError):
    """Excepción emitida cuando una petición de inferencia al proveedor supera el tiempo límite configurado."""

    def __init__(self, provider_name: str, timeout_seconds: float) -> None:
        msg = f"Tiempo de espera agotado ({timeout_seconds}s) al consultar el proveedor '{provider_name}'."
        super().__init__(
            message=msg,
            code="PROVIDER_TIMEOUT",
            details={"provider": provider_name, "timeout_seconds": timeout_seconds},
        )
