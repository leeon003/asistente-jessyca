"""Modelos de datos para JESSYCA Mobile API Bridge (JESSYCA 4.0 Core ↔ Mobile).

Define esquemas Pydantic para solicitudes, respuestas y validaciones de salud y chat.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HealthResponse(BaseModel):
    """Modelo de respuesta para el endpoint de verificación de salud."""

    model_config = ConfigDict(extra="ignore")

    success: bool = True
    service: str = "jessyca-mobile-api"
    status: str = "online"


class ChatRequest(BaseModel):
    """Modelo de solicitud para interactuar con el asistente desde el cliente Android."""

    model_config = ConfigDict(extra="ignore")

    session_id: str = Field(
        default_factory=lambda: f"android-{uuid.uuid4().hex[:8]}",
        description="Identificador único de la sesión conversacional móvil.",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Texto o comando emitido por el usuario en el cliente móvil.",
    )
    device_id: str | None = Field(
        default=None,
        description="Identificador opcional del dispositivo Android emisor.",
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("El mensaje no puede estar compuesto únicamente de espacios en blanco.")
        return cleaned


class ChatResponse(BaseModel):
    """Modelo de respuesta unificada emitido al cliente móvil tras procesar en el Core."""

    model_config = ConfigDict(extra="ignore")

    success: bool
    session_id: str
    response_text: str
    requires_confirmation: bool = False
    requires_clarification: bool = False
    clarification_question: str | None = None
    status: str = "COMPLETED"
    intent: str = "unknown"
    action_contract: dict[str, Any] | None = None
    error: str | None = None


class ErrorResponse(BaseModel):
    """Modelo estructurado para errores de la API móvil."""

    model_config = ConfigDict(extra="ignore")

    success: bool = False
    error: str
    detail: str | None = None
