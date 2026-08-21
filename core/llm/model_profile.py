"""Perfil descriptivo tipado e inmutable para modelos LLM (ModelProfile - Fase 1: Multi-LLM Foundation).

GARANTÍA ARQUITECTÓNICA:
Este módulo contiene ÚNICAMENTE estructuras descriptivas y metadatos sobre modelos LLM.
NO ejecuta lógica de inferencia, NO invoca librerías de red, NO llama a Ollama ni realiza acciones del sistema operativo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.llm.exceptions import ModelRegistrationError


@dataclass(frozen=True)
class ModelProfile:
    """Perfil declarativo, tipado e inmutable de un modelo LLM registrado en Jessyca."""

    model_id: str = ""
    name: str = ""
    provider: str = "ollama"
    capabilities: tuple[str, ...] = ("completion",)
    context_length: int | None = None
    max_context_length: int | None = None
    input_modalities: tuple[str, ...] = ("text",)
    output_modalities: tuple[str, ...] = ("text",)
    vision: bool = False
    supports_vision: bool = False
    tool_calling: bool = False
    supports_tools: bool = False
    reasoning: bool = False
    priority: int = 1
    vram_estimate_mb: int | None = None
    enabled: bool = True
    default_parameters: dict[str, Any] = field(default_factory=lambda: {"temperature": 0.1})
    description: str = ""

    def __post_init__(self) -> None:
        """Normaliza y valida la integridad de los campos del perfil."""
        # Unificar model_id y name
        effective_id = self.model_id or self.name
        if not effective_id or not isinstance(effective_id, str) or not effective_id.strip():
            raise ModelRegistrationError(
                message="El identificador (model_id / name) del modelo no puede estar vacío.",
                code="INVALID_MODEL_NAME",
            )
        object.__setattr__(self, "model_id", effective_id.strip())
        object.__setattr__(self, "name", effective_id.strip())

        # Unificar provider
        if not self.provider or not isinstance(self.provider, str) or not self.provider.strip():
            raise ModelRegistrationError(
                message="El proveedor del modelo no puede estar vacío.",
                code="INVALID_PROVIDER_NAME",
            )
        object.__setattr__(self, "provider", self.provider.strip())

        # Unificar context_length
        effective_ctx = self.context_length if self.context_length is not None else self.max_context_length
        if effective_ctx is not None and effective_ctx <= 0:
            raise ModelRegistrationError(
                message=f"El contexto máximo debe ser un entero positivo, recibido: {effective_ctx}",
                code="INVALID_CONTEXT_LENGTH",
            )
        object.__setattr__(self, "context_length", effective_ctx)
        object.__setattr__(self, "max_context_length", effective_ctx)

        # Unificar flags booleanos
        effective_vision = self.vision or self.supports_vision
        object.__setattr__(self, "vision", effective_vision)
        object.__setattr__(self, "supports_vision", effective_vision)

        effective_tools = self.tool_calling or self.supports_tools
        object.__setattr__(self, "tool_calling", effective_tools)
        object.__setattr__(self, "supports_tools", effective_tools)

        effective_reasoning = self.reasoning or ("thinking" in self.capabilities or "reasoning" in self.capabilities)
        object.__setattr__(self, "reasoning", effective_reasoning)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el perfil del modelo a un diccionario."""
        return {
            "model_id": self.model_id,
            "name": self.name,
            "provider": self.provider,
            "capabilities": list(self.capabilities),
            "context_length": self.context_length,
            "max_context_length": self.max_context_length,
            "input_modalities": list(self.input_modalities),
            "output_modalities": list(self.output_modalities),
            "vision": self.vision,
            "supports_vision": self.supports_vision,
            "tool_calling": self.tool_calling,
            "supports_tools": self.supports_tools,
            "reasoning": self.reasoning,
            "priority": self.priority,
            "vram_estimate_mb": self.vram_estimate_mb,
            "enabled": self.enabled,
            "default_parameters": dict(self.default_parameters),
            "description": self.description,
        }
