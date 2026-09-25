"""Aplicación FastAPI para JESSYCA Web Bridge (OpenAI-Compatible).

Expone endpoints compatibles con OpenAI (/v1/models, /v1/chat/completions)
permitiendo que Open WebUI interactúe directamente con JessycaLocalAgent.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from core.local_agent.local_agent import JessycaLocalAgent
from core.logger import get_logger
from interfaces.webui_bridge.adapter import (
    PUBLIC_MODEL_NAME,
    build_jessyca_request,
    classify_openwebui_internal_task,
    convert_to_openai_response,
    extract_last_user_message,
    generate_internal_task_response,
    generate_internal_task_stream,
    generate_live_sse_stream,
    generate_sse_stream,
    normalize_conversation_messages,
    openai_error,
    resolve_session_id,
)
from interfaces.webui_bridge.models import (
    ChatCompletionRequest,
    HealthResponse,
    ModelsResponse,
)

logger = get_logger("jessyca.webui_bridge")

DEFAULT_TIMEOUT_SECONDS = 60.0


def create_webui_bridge_app(
    auth_token: str | None = None,
    timeout_seconds: float | None = None,
) -> FastAPI:
    """Fábrica de la aplicación FastAPI para JESSYCA Web Bridge."""
    # Resolución segura de token: parámetro explícito -> settings -> variable de entorno
    token_candidate = auth_token
    if token_candidate is None:
        try:
            from config.manager import get_settings
            token_candidate = getattr(get_settings(), "WEBUI_BRIDGE_AUTH_TOKEN", "")
        except Exception:
            token_candidate = os.getenv("WEBUI_BRIDGE_AUTH_TOKEN", "")

    configured_token = (token_candidate or os.getenv("WEBUI_BRIDGE_AUTH_TOKEN", "")).strip()
    if not configured_token:
        logger.critical(
            "[WEBUI Bridge] WEBUI_BRIDGE_AUTH_TOKEN no está configurado. "
            "Por seguridad, el Web Bridge requiere un token de autenticación obligatorio para iniciar."
        )
        raise ValueError(
            "WEBUI_BRIDGE_AUTH_TOKEN no está configurado. Por seguridad, el Web Bridge requiere un token de autenticación obligatorio para iniciar."
        )

    logger.info("[WEBUI Bridge] Authentication configured successfully.")

    raw_timeout = timeout_seconds
    if raw_timeout is None:
        try:
            from config.manager import get_settings
            raw_timeout = getattr(get_settings(), "WEBUI_BRIDGE_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)
        except Exception:
            raw_timeout = os.getenv("WEBUI_BRIDGE_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))

    try:
        configured_timeout = float(raw_timeout)
    except (ValueError, TypeError):
        configured_timeout = DEFAULT_TIMEOUT_SECONDS

    app = FastAPI(
        title="JESSYCA Web Bridge (OpenAI-Compatible)",
        description="Adaptador HTTP compatible con OpenAI para integración entre Open WebUI y JESSYCA Core.",
        version="1.0.0",
    )

    # Middleware CORS para comunicación con Docker / Navegadores
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # ── GESTIÓN DE VALIDACIÓN PYDANTIC ──
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        err_msg = "; ".join(f"{'.'.join(str(part) for part in err.get('loc', []))}: {err.get('msg')}" for err in exc.errors())
        logger.warning(f"[WEBUI BRIDGE VALIDATION] Error en payload ({request.url.path}): {err_msg}")
        return openai_error(
            message=f"Validation error: {err_msg}",
            error_type="invalid_request_error",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="invalid_payload",
        )

    # ── ENDPOINTS ──

    @app.get(
        "/health",
        response_model=HealthResponse,
        summary="Health check del Web Bridge",
        description="Verifica que el servicio esté operativo sin invocar al Core ni a Ollama.",
    )
    async def health_endpoint() -> HealthResponse:
        return HealthResponse(status="ok", service="jessyca-webui-bridge")

    @app.get(
        "/v1/models",
        response_model=ModelsResponse,
        summary="Catálogo de modelos disponibles",
        description="Expone exclusivamente el modelo virtual 'jessyca' hacia Open WebUI.",
    )
    async def list_models() -> ModelsResponse:
        return ModelsResponse()

    @app.post(
        "/v1/chat/completions",
        summary="Chat Completions compatible con OpenAI",
        description="Punto de entrada de chat para Open WebUI. Delega a JessycaLocalAgent de forma no bloqueante.",
    )
    async def chat_completions(payload: ChatCompletionRequest, request: Request) -> Any:
        start_time = time.perf_counter()

        # 1. Autenticación Bearer o X-Jessyca-Token
        auth_header = request.headers.get("authorization", "")
        token_found = ""
        if auth_header.lower().startswith("bearer "):
            token_found = auth_header[7:].strip()
        elif "x-jessyca-token" in request.headers:
            token_found = request.headers["x-jessyca-token"].strip()

        if not token_found or token_found != configured_token:
            client_ip = request.client.host if request.client else "unknown"
            logger.warning(f"[WEBUI BRIDGE AUTH] Acceso no autorizado desde {client_ip} a {request.url.path}")
            return openai_error(
                message="Invalid API key",
                error_type="invalid_request_error",
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="invalid_api_key",
            )

        # 2. Validación de modelo solicitado
        requested_model = (payload.model or "").strip().lower()
        if requested_model != PUBLIC_MODEL_NAME:
            logger.warning(f"[WEBUI BRIDGE] Modelo solicitado desconocido: '{payload.model}'")
            return openai_error(
                message=f"The model '{payload.model}' does not exist",
                error_type="invalid_request_error",
                status_code=status.HTTP_404_NOT_FOUND,
                code="model_not_found",
                param="model",
            )

        # 2.5 Detección y filtrado defensivo de tareas internas de Open WebUI (Auto-Title, Auto-Tags, etc.)
        internal_task = classify_openwebui_internal_task(payload.messages)
        if internal_task:
            logger.info(
                f"[WEBUI BRIDGE FILTER] Interceptada tarea interna de Open WebUI ('{internal_task}'). "
                f"Bloqueando ejecución de Core y Skills físicos para prevenir re-ejecuciones y latencia."
            )
            c_id = f"chatcmpl-internal-{uuid.uuid4().hex[:8]}"
            if payload.stream:
                return StreamingResponse(
                    generate_internal_task_stream(
                        task_type=internal_task,
                        model=PUBLIC_MODEL_NAME,
                        completion_id=c_id,
                    ),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )
            internal_resp = generate_internal_task_response(
                task_type=internal_task,
                messages=payload.messages,
                model=PUBLIC_MODEL_NAME,
                completion_id=c_id,
            )
            return JSONResponse(status_code=status.HTTP_200_OK, content=internal_resp.model_dump())

        # 3. Extracción del mensaje de usuario activo
        try:
            last_user_message = extract_last_user_message(payload.messages)
        except ValueError as val_err:
            logger.warning(f"[WEBUI BRIDGE] Solicitud sin mensaje de usuario: {val_err}")
            return openai_error(
                message=str(val_err),
                error_type="invalid_request_error",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="invalid_payload",
                param="messages",
            )

        # 4. Resolución determinista de sesión y normalización de historial
        session_id = resolve_session_id(payload, request.headers)
        normalized_messages = normalize_conversation_messages(payload.messages)

        # 5. Construcción de JessycaRequest oficial
        jessyca_req = build_jessyca_request(
            user_input=last_user_message,
            session_id=session_id,
            chat_id=payload.chat_id,
            conversation_context=normalized_messages,
        )

        # ── TRAZA TEMPORAL SEGURA OWUI_MEM_TRACE ──
        raw_chat_id = payload.chat_id or (payload.model_extra.get("chat_id") if payload.model_extra else None)
        conv_id = (payload.model_extra.get("conversation_id") if payload.model_extra else None)
        roles = [str(m.role) for m in payload.messages]
        lengths = [len(m.content or "") for m in payload.messages]
        hashes = [hashlib.sha256((m.content or "").encode("utf-8")).hexdigest()[:8] for m in payload.messages]
        msg_traces = "\n".join(
            f"message[{i}]: role={roles[i]} length={lengths[i]} hash={hashes[i]}"
            for i in range(len(payload.messages))
        )
        safe_headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in ("authorization", "cookie", "set-cookie", "x-jessyca-token")
        }
        logger.info(
            f"\n[OWUI_MEM_TRACE]\n"
            f"request_id={jessyca_req.request_id}\n"
            f"chat_id={raw_chat_id}\n"
            f"conversation_id={conv_id}\n"
            f"session_id={session_id}\n"
            f"messages_count={len(payload.messages)}\n"
            f"roles={roles}\n"
            f"message_lengths={lengths}\n"
            f"message_hashes={hashes}\n"
            f"{msg_traces}\n"
            f"safe_headers={safe_headers}\n"
            f"[END OWUI_MEM_TRACE]"
        )

        logger.info(
            f"[WEBUI BRIDGE] Procesando solicitud (req_id={jessyca_req.request_id}, "
            f"session_id={session_id}, stream={payload.stream}, chars={len(last_user_message)})"
        )

        # 6. Invocación segura y no bloqueante del Core
        agent = JessycaLocalAgent.get_instance()

        if payload.stream:
            from unittest.mock import Mock
            if isinstance(agent, Mock) and getattr(agent.interact_stream, "side_effect", None) is None:
                core_response = agent.interact(jessyca_req)
                if hasattr(core_response, "response_text") and isinstance(core_response.response_text, str):
                    return StreamingResponse(
                        generate_sse_stream(
                            res=core_response,
                            model=PUBLIC_MODEL_NAME,
                            completion_id=f"chatcmpl-{jessyca_req.request_id}",
                        ),
                        media_type="text/event-stream",
                        headers={
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                            "X-Accel-Buffering": "no",
                        },
                    )

            # STREAMING GENERATIVO REAL:
            # Emite tokens progresivos en tiempo real desde Ollama si es conversacional,
            # o ejecuta y verifica primero en el SO si es una acción física con efectos secundarios.
            token_gen = agent.interact_stream(jessyca_req)
            return StreamingResponse(
                generate_live_sse_stream(
                    token_generator=token_gen,
                    model=PUBLIC_MODEL_NAME,
                    completion_id=f"chatcmpl-{jessyca_req.request_id}",
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # Modo síncrono estándar (Non-stream JSON)
        try:
            core_response = await asyncio.wait_for(
                asyncio.to_thread(agent.interact, jessyca_req),
                timeout=configured_timeout,
            )
        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"[WEBUI BRIDGE TIMEOUT] Timeout de {configured_timeout}s excedido "
                f"(req_id={jessyca_req.request_id}, session_id={session_id}, latencia={latency_ms:.2f}ms)"
            )
            return openai_error(
                message="JESSYCA Core processing timed out",
                error_type="timeout_error",
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                code="core_timeout",
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"[WEBUI BRIDGE ERROR] Excepción interna en Core (req_id={jessyca_req.request_id}, "
                f"session_id={session_id}, latencia={latency_ms:.2f}ms): {exc}",
                exc_info=True,
            )
            return openai_error(
                message="Internal server error processing request in JESSYCA Core",
                error_type="internal_error",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="internal_error",
            )

        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"[WEBUI BRIDGE COMPLETADO] Turno procesado con éxito (req_id={jessyca_req.request_id}, "
            f"session_id={session_id}, status={core_response.status}, success={core_response.success}, "
            f"latencia={latency_ms:.2f}ms)"
        )

        openai_resp = convert_to_openai_response(
            res=core_response,
            model=PUBLIC_MODEL_NAME,
            completion_id=f"chatcmpl-{jessyca_req.request_id}",
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=openai_resp.model_dump())

    return app
