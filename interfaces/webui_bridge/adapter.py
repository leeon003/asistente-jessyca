"""Adaptador determinista para traducir el protocolo OpenAI a JESSYCA Core.

Traduce solicitudes externas Chat Completions a JessycaRequest y mapea
la respuesta resultante de JessycaLocalAgent a estructuras compatibles con OpenAI.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections.abc import AsyncGenerator, Mapping
from typing import Any

from fastapi.responses import JSONResponse

from core.local_agent.local_agent_models import InputModality, JessycaRequest, JessycaResponse
from interfaces.webui_bridge.models import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ChatMessage,
    OpenAIErrorBody,
    OpenAIErrorResponse,
)

PUBLIC_MODEL_NAME = "jessyca"


def resolve_session_id(
    payload: ChatCompletionRequest,
    headers: Mapping[str, str] | None = None,
) -> str:
    """Resuelve un identificador de sesión único y determinista para JESSYCA.

    Prioridad:
    1. Campo 'chat_id' explícito en el cuerpo JSON de la petición.
    2. Campo 'chat_id' en metadata o campos extra del modelo Pydantic.
    3. Encabezado HTTP 'X-OpenWebUI-Chat-Id'.
    4. Encabezado HTTP 'X-Session-Id'.
    5. Fallback determinista basado en el contenido del primer mensaje de usuario.
    """
    normalized_headers: dict[str, str] = {}
    if headers:
        normalized_headers = {k.lower(): v for k, v in headers.items()}

    # 1. chat_id en body
    if payload.chat_id and str(payload.chat_id).strip():
        raw_id = str(payload.chat_id).strip()
        return raw_id if raw_id.startswith("owui-") else f"owui-{raw_id}"

    # 2. metadata o campos extra en el request
    if payload.model_extra:
        extra_chat = payload.model_extra.get("chat_id")
        if extra_chat and str(extra_chat).strip():
            raw_id = str(extra_chat).strip()
            return raw_id if raw_id.startswith("owui-") else f"owui-{raw_id}"

        metadata = payload.model_extra.get("metadata")
        if isinstance(metadata, dict) and metadata.get("chat_id"):
            raw_id = str(metadata["chat_id"]).strip()
            return raw_id if raw_id.startswith("owui-") else f"owui-{raw_id}"

    # 3. Header X-OpenWebUI-Chat-Id
    h_chat_id = normalized_headers.get("x-openwebui-chat-id")
    if h_chat_id and h_chat_id.strip():
        raw_id = h_chat_id.strip()
        return raw_id if raw_id.startswith("owui-") else f"owui-{raw_id}"

    # 4. Header X-Session-Id
    h_session_id = normalized_headers.get("x-session-id")
    if h_session_id and h_session_id.strip():
        raw_id = h_session_id.strip()
        return raw_id if raw_id.startswith("owui-") else f"owui-{raw_id}"

    # 5. Fallback determinista
    first_user_text = ""
    for msg in payload.messages:
        if str(msg.role).strip().lower() == "user" and msg.content:
            first_user_text = msg.content.strip()
            break

    if first_user_text:
        digest = hashlib.sha256(first_user_text.encode("utf-8")).hexdigest()[:12]
        return f"owui-h-{digest}"

    return "owui-session-default"


def extract_last_user_message(messages: list[ChatMessage]) -> str:
    """Extrae el último mensaje con rol 'user' de la lista de mensajes.

    Ignora de forma estricta los mensajes con rol 'system', 'assistant' o 'tool'.
    """
    for msg in reversed(messages):
        if str(msg.role).strip().lower() == "user":
            content = msg.content or ""
            cleaned = content.strip()
            if cleaned:
                return cleaned

    raise ValueError("La solicitud no contiene ningún mensaje de usuario válido con contenido de texto.")


def normalize_conversation_messages(messages: list[ChatMessage]) -> list[dict[str, str]]:
    """Normaliza y sanitiza los mensajes del historial enviados por el cliente OpenAI / Open WebUI.

    Conserva únicamente los roles 'user', 'assistant' y 'system', preservando su orden cronológico.
    """
    normalized: list[dict[str, str]] = []
    for msg in messages:
        role = str(msg.role or "").strip().lower()
        if role not in ("user", "assistant", "system"):
            continue
        content = (msg.content or "").strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def build_jessyca_request(
    user_input: str,
    session_id: str,
    chat_id: str | None = None,
    conversation_context: list[dict[str, str]] | None = None,
) -> JessycaRequest:
    """Construye la instancia oficial de JessycaRequest respetando el Core de JESSYCA."""
    return JessycaRequest(
        session_id=session_id,
        modality=InputModality.TEXT,
        user_input=user_input,
        conversation_context=list(conversation_context or []),
        metadata={
            "source": "open_webui",
            "chat_id": chat_id or session_id,
        },
    )


def convert_to_openai_response(
    res: JessycaResponse,
    model: str = PUBLIC_MODEL_NAME,
    completion_id: str | None = None,
) -> ChatCompletionResponse:
    """Transforma la respuesta del Core en un objeto ChatCompletionResponse de OpenAI."""
    c_id = completion_id or f"chatcmpl-{res.request_id or uuid.uuid4().hex[:12]}"
    content_text = res.response_text or ""

    # Estimación simple de tokens para compatibilidad con UIs
    prompt_tokens = max(1, len(content_text.split()))
    completion_tokens = prompt_tokens

    return ChatCompletionResponse(
        id=c_id,
        object="chat.completion",
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(
                    role="assistant",
                    content=content_text,
                ),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


async def generate_sse_stream(
    res: JessycaResponse,
    model: str = PUBLIC_MODEL_NAME,
    completion_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Generador asíncrono de eventos Server-Sent Events (SSE) para pseudo-streaming.

    Fragmenta el response_text consolidado en deltas de tokens para proveer
    la animación visual fluida en Open WebUI culminando en [DONE].
    """
    c_id = completion_id or f"chatcmpl-{res.request_id or uuid.uuid4().hex[:12]}"
    content_text = res.response_text or ""

    # 1. Primer chunk con rol 'assistant'
    first_chunk = ChatCompletionChunk(
        id=c_id,
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionChunkDelta(role="assistant", content=""),
                finish_reason=None,
            )
        ],
    )
    yield f"data: {json.dumps(first_chunk.model_dump())}\n\n"

    # 2. Fragmentación por palabras o bloques naturales
    tokens = re.split(r"(\s+)", content_text)
    for token in tokens:
        if not token:
            continue
        chunk = ChatCompletionChunk(
            id=c_id,
            created=int(time.time()),
            model=model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionChunkDelta(content=token),
                    finish_reason=None,
                )
            ],
        )
        yield f"data: {json.dumps(chunk.model_dump())}\n\n"

    # 3. Chunk final con finish_reason 'stop'
    final_chunk = ChatCompletionChunk(
        id=c_id,
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionChunkDelta(),
                finish_reason="stop",
            )
        ],
    )
    yield f"data: {json.dumps(final_chunk.model_dump())}\n\n"

    # 4. Señal de terminación de flujo SSE
    yield "data: [DONE]\n\n"


def openai_error(
    message: str,
    error_type: str,
    status_code: int,
    code: str | None = None,
    param: str | None = None,
) -> JSONResponse:
    """Helper unificado para generar respuestas de error compatibles con el estándar OpenAI."""
    error_payload = OpenAIErrorResponse(
        error=OpenAIErrorBody(
            message=message,
            type=error_type,
            param=param,
            code=code,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=error_payload.model_dump(),
    )


def classify_openwebui_internal_task(messages: list[ChatMessage]) -> str | None:
    """Detecta si una solicitud de Open WebUI corresponde a una tarea interna en segundo plano.

    Tareas internas reconocidas:
    - 'title': Auto-Title generation
    - 'tags': Auto-Tags generation
    - 'follow_up': Follow-up questions generation
    - 'summary': Auto-summarization
    """
    for msg in messages:
        content = (msg.content or "").strip().lower()
        if not content:
            continue

        # Auto-Title
        if (
            ("generate a concise" in content and "title" in content)
            or "task generate a concise title" in content
            or "generate a 3-5 word title" in content
            or "title for the following conversation" in content
            or "title generation" in content
            or (("título" in content or "titulo" in content or "title" in content) and any(w in content for w in ("genera", "generar", "crea", "crear", "resume", "resumen", "corto para", "generate")))
        ):
            return "title"

        # Auto-Tags
        if (
            "generate 1-3 broad tags" in content
            or "task generate 1-3 broad tags" in content
            or "broad tags categorizing" in content
            or "generate tags for" in content
            or "tags generation" in content
            or (("etiqueta" in content or "tags" in content) and any(w in content for w in ("genera", "generar", "crea", "crear", "para", "generate")))
        ):
            return "tags"

        # Follow-up
        if (
            "follow-up questions" in content
            or "generate follow up" in content
            or "suggest 3 follow-up" in content
            or "preguntas de seguimiento" in content
        ):
            return "follow_up"

        # Summarize
        if (
            "summarize the following conversation" in content
            or "summarize the chat" in content
            or (("resume" in content or "resumen" in content) and "conversación" in content)
        ):
            return "summary"

    return None


def generate_internal_task_response(
    task_type: str,
    messages: list[ChatMessage],
    model: str = PUBLIC_MODEL_NAME,
    completion_id: str | None = None,
) -> ChatCompletionResponse:
    """Genera una respuesta inmediata, sintética y segura para tareas internas de Open WebUI.

    Evita invocar al LLM o a los Skills físicos de JESSYCA, protegiendo el sistema de falsas
    ejecuciones y reduciendo la latencia de 10-20s a <1ms.
    """
    c_id = completion_id or f"chatcmpl-internal-{uuid.uuid4().hex[:8]}"

    if task_type == "title":
        content = "Conversación JESSYCA"
    elif task_type == "tags":
        content = '["asistente", "jessyca"]'
    elif task_type == "follow_up":
        content = ""
    else:
        content = ""

    return ChatCompletionResponse(
        id=c_id,
        object="chat.completion",
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        ),
    )


async def generate_internal_task_stream(
    task_type: str,
    model: str = PUBLIC_MODEL_NAME,
    completion_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Flujo SSE inmediato para tareas internas en modo streaming."""
    c_id = completion_id or f"chatcmpl-internal-{uuid.uuid4().hex[:8]}"
    if task_type == "title":
        content = "Conversación JESSYCA"
    elif task_type == "tags":
        content = '["asistente", "jessyca"]'
    else:
        content = ""

    first_chunk = ChatCompletionChunk(
        id=c_id,
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionChunkDelta(role="assistant", content=content),
                finish_reason=None,
            )
        ],
    )
    yield f"data: {json.dumps(first_chunk.model_dump())}\n\n"

    final_chunk = ChatCompletionChunk(
        id=c_id,
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionChunkDelta(),
                finish_reason="stop",
            )
        ],
    )
    yield f"data: {json.dumps(final_chunk.model_dump())}\n\n"
    yield "data: [DONE]\n\n"


async def generate_live_sse_stream(
    token_generator: Any,
    model: str = PUBLIC_MODEL_NAME,
    completion_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Generador asíncrono SSE que emite tokens en tiempo real provenientes del generador del Core."""
    import asyncio
    import threading

    c_id = completion_id or f"chatcmpl-{uuid.uuid4().hex[:12]}"

    first_chunk = ChatCompletionChunk(
        id=c_id,
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionChunkDelta(role="assistant", content=""),
                finish_reason=None,
            )
        ],
    )
    yield f"data: {json.dumps(first_chunk.model_dump())}\n\n"

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _producer() -> None:
        try:
            for token in token_generator:
                if token:
                    loop.call_soon_threadsafe(queue.put_nowait, token)
        except Exception:
            pass
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    prod_thread = threading.Thread(target=_producer, daemon=True)
    prod_thread.start()

    while True:
        tok = await queue.get()
        if tok is None:
            break
        chunk = ChatCompletionChunk(
            id=c_id,
            created=int(time.time()),
            model=model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionChunkDelta(content=tok),
                    finish_reason=None,
                )
            ],
        )
        yield f"data: {json.dumps(chunk.model_dump())}\n\n"

    final_chunk = ChatCompletionChunk(
        id=c_id,
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionChunkDelta(),
                finish_reason="stop",
            )
        ],
    )
    yield f"data: {json.dumps(final_chunk.model_dump())}\n\n"
    yield "data: [DONE]\n\n"

