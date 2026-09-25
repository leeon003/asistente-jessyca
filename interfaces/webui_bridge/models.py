"""Modelos de datos Pydantic para JESSYCA Web Bridge (OpenAI-Compatible).

Define los esquemas estándar compatibles con la API de OpenAI (Chat Completions y Models)
utilizados por Open WebUI y otros clientes web.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """Mensaje individual en una conversación según especificación OpenAI."""

    model_config = ConfigDict(extra="allow")

    role: str = Field(..., description="Rol del emisor: system, user, assistant o tool.")
    content: str | None = Field(default="", description="Contenido textual del mensaje.")


class ChatCompletionRequest(BaseModel):
    """Solicitud de completado de chat compatible con OpenAI."""

    model_config = ConfigDict(extra="allow")

    model: str = Field(..., description="Identificador del modelo solicitado (debe ser 'jessyca').")
    messages: list[ChatMessage] = Field(..., min_length=1, description="Historial de mensajes de la conversación.")
    stream: bool = Field(default=False, description="Indica si la respuesta debe enviarse vía Server-Sent Events (SSE).")
    temperature: float | None = Field(default=None, description="Parámetro opcional de muestreo.")
    chat_id: str | None = Field(default=None, description="Identificador de conversación emitido por Open WebUI.")
    max_tokens: int | None = Field(default=None, description="Límite máximo de tokens.")
    top_p: float | None = Field(default=None, description="Parámetro de probabilidad acumulada.")


class ChatCompletionChoiceMessage(BaseModel):
    """Mensaje devuelto por el asistente en una respuesta completada."""

    model_config = ConfigDict(extra="ignore")

    role: str = "assistant"
    content: str


class ChatCompletionChoice(BaseModel):
    """Opción de completado de chat."""

    model_config = ConfigDict(extra="ignore")

    index: int = 0
    message: ChatCompletionChoiceMessage
    finish_reason: str | None = "stop"


class ChatCompletionUsage(BaseModel):
    """Métricas de uso de tokens estimadas para compatibilidad con clientes OpenAI."""

    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    """Estructura de respuesta no-stream compatible con OpenAI."""

    model_config = ConfigDict(extra="ignore")

    id: str
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = "jessyca"
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage = Field(default_factory=ChatCompletionUsage)


class ChatCompletionChunkDelta(BaseModel):
    """Fragmento de delta para respuestas Server-Sent Events (SSE)."""

    model_config = ConfigDict(extra="ignore")

    role: str | None = None
    content: str | None = None


class ChatCompletionChunkChoice(BaseModel):
    """Opción de fragmento individual en streaming SSE."""

    model_config = ConfigDict(extra="ignore")

    index: int = 0
    delta: ChatCompletionChunkDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    """Fragmento SSE emitido para cada evento en modo streaming."""

    model_config = ConfigDict(extra="ignore")

    id: str
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = "jessyca"
    choices: list[ChatCompletionChunkChoice]


class ModelPermissionItem(BaseModel):
    """Permisos del modelo para el catálogo OpenAI."""

    model_config = ConfigDict(extra="ignore")

    id: str = "modelperm-jessyca"
    object: str = "model_permission"
    created: int = 1727140000
    allow_create_engine: bool = False
    allow_sampling: bool = True
    allow_logprobs: bool = False
    allow_search_indices: bool = False
    allow_view: bool = True
    allow_fine_tuning: bool = False
    organization: str = "*"
    group: str | None = None
    is_blocking: bool = False


class ModelItem(BaseModel):
    """Entrada individual de modelo en el endpoint /v1/models."""

    model_config = ConfigDict(extra="ignore")

    id: str = "jessyca"
    object: str = "model"
    created: int = 1727140000
    owned_by: str = "jessyca-project"
    root: str = "jessyca"
    parent: str | None = None
    permission: list[ModelPermissionItem] = Field(default_factory=lambda: [ModelPermissionItem()])


class ModelsResponse(BaseModel):
    """Respuesta para listar modelos disponibles en /v1/models."""

    model_config = ConfigDict(extra="ignore")

    object: str = "list"
    data: list[ModelItem] = Field(default_factory=lambda: [ModelItem()])


class OpenAIErrorBody(BaseModel):
    """Cuerpo de error conforme al estándar OpenAI."""

    model_config = ConfigDict(extra="ignore")

    message: str
    type: str = "invalid_request_error"
    param: str | None = None
    code: str | None = None


class OpenAIErrorResponse(BaseModel):
    """Contenedor de error estándar OpenAI."""

    model_config = ConfigDict(extra="ignore")

    error: OpenAIErrorBody


class HealthResponse(BaseModel):
    """Respuesta para el endpoint de verificación de salud del Bridge."""

    model_config = ConfigDict(extra="ignore")

    status: str = "ok"
    service: str = "jessyca-webui-bridge"
