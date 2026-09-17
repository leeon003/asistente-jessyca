"""Aplicación FastAPI para JESSYCA Mobile API Bridge (JESSYCA 4.0 Core ↔ Mobile).

Expone endpoints HTTP asíncronos para comunicación con el cliente Android,
delegando el procesamiento al agente local unificado sin bloquear el loop de eventos.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.manager import get_settings
from config.settings import AppSettings
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import InputModality, JessycaRequest
from core.logger import get_logger
from interfaces.mobile_api.models import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthResponse,
)

logger = get_logger("jessyca.mobile_api")

# Endpoints exentos del requisito de token de autenticación
PUBLIC_PATHS = frozenset({
    "/api/v1/health",
    "/docs",
    "/openapi.json",
    "/redoc",
})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestor de ciclo de vida para el servidor Mobile API."""
    logger.info("[Mobile API] Inicializando contexto de Mobile API Bridge...")
    try:
        # Pre-calentar la instancia singleton de JessycaLocalAgent
        JessycaLocalAgent.get_instance()
        logger.info("[Mobile API] Conexión con JessycaLocalAgent verificada.")
    except Exception as exc:
        logger.error(f"[Mobile API] Error al inicializar JessycaLocalAgent en lifespan: {exc}")
        raise

    yield

    logger.info("[Mobile API] Cerrando contexto de Mobile API Bridge limpiamente...")


def create_mobile_api_app(settings: AppSettings | None = None) -> FastAPI:
    """Fábrica de la aplicación FastAPI para Mobile API Bridge."""
    active_settings = settings or get_settings()

    app = FastAPI(
        title="JESSYCA Mobile API Bridge",
        description="Puente HTTP/REST para integración oficial entre JESSYCA Core y Android.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Middleware CORS para desarrollo local y emulador Android
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # ── MIDDLEWARE DE AUTENTICACIÓN ──
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """Verifica el token de autorización en el encabezado X-Jessyca-Token."""
        if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        expected_token = active_settings.MOBILE_API_AUTH_TOKEN
        client_token = request.headers.get("X-Jessyca-Token")

        # Rechazar si no se provee token o si no coincide
        if not client_token or client_token != expected_token:
            client_host = request.client.host if request.client else "unknown"
            logger.warning(
                f"[Mobile API AUTH] Intento de acceso no autorizado a '{request.url.path}' desde {client_host}"
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "success": False,
                    "error": "Token de autenticación inválido o ausente (X-Jessyca-Token requerido).",
                },
            )

        return await call_next(request)

    # ── GESTIÓN PERSONALIZADA DE VALIDACIÓN ──
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Devuelve formato JSON consistente ante errores de validación en request bodies."""
        errors_summary = [
            {"loc": err.get("loc"), "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        logger.warning(f"[Mobile API VALIDATION] Error en payload ({request.url.path}): {errors_summary}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "error": "Error de validación en la solicitud.",
                "details": errors_summary,
            },
        )

    # ── ENDPOINTS ──

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        summary="Health check del puente móvil",
        description="Verifica que el Core esté accesible desde la red local sin invocar al LLM.",
    )
    async def health_check() -> HealthResponse:
        return HealthResponse(
            success=True,
            service="jessyca-mobile-api",
            status="online",
        )

    @app.post(
        "/api/v1/chat",
        response_model=ChatResponse,
        responses={
            401: {"model": ErrorResponse, "description": "Token inválido o ausente"},
            422: {"model": ErrorResponse, "description": "Error de validación"},
            500: {"model": ErrorResponse, "description": "Error interno del servidor"},
            504: {"model": ErrorResponse, "description": "Timeout al procesar la solicitud"},
        },
        summary="Canal conversacional oficial para cliente móvil",
        description="Transforma la solicitud a JessycaRequest y delega a JessycaLocalAgent sin bloquear el loop.",
    )
    async def chat_endpoint(payload: ChatRequest) -> Any:
        logger.info(
            f"[Mobile API CHAT] Petición recibida (session_id: {payload.session_id}, "
            f"device_id: {payload.device_id or 'none'}, longitud: {len(payload.message)})"
        )

        # 1. Transformar a JessycaRequest oficial del Core
        req = JessycaRequest(
            session_id=payload.session_id,
            user_input=payload.message,
            modality=InputModality.TEXT,
            metadata={
                "source": "mobile_android",
                "device_id": payload.device_id,
            },
        )

        agent = JessycaLocalAgent.get_instance()
        timeout_sec = float(active_settings.MOBILE_API_TIMEOUT or 30)

        # 2. Ejecutar de forma no bloqueante con timeout
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(agent.interact, req),
                timeout=timeout_sec,
            )
        except TimeoutError:
            logger.error(
                f"[Mobile API CHAT] Timeout de {timeout_sec}s excedido procesando session_id {payload.session_id}"
            )
            return JSONResponse(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                content={
                    "success": False,
                    "session_id": payload.session_id,
                    "error": f"Tiempo de procesamiento excedido en JESSYCA Core ({timeout_sec}s).",
                },
            )
        except Exception as exc:
            logger.error(
                f"[Mobile API CHAT] Error interno procesando session_id {payload.session_id}: {exc}",
                exc_info=True,
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "success": False,
                    "session_id": payload.session_id,
                    "error": "Ocurrió un error interno al procesar tu solicitud en JESSYCA Core.",
                },
            )

        # 3. Mapear respuesta completa respetando contratos y estados
        contract_dict = None
        if getattr(res, "action_intent_contract", None) is not None:
            contract = res.action_intent_contract
            if hasattr(contract, "to_dict"):
                contract_dict = contract.to_dict()

        status_str = getattr(res.status, "value", str(res.status))

        logger.info(
            f"[Mobile API CHAT] Respuesta generada con éxito (session_id: {payload.session_id}, "
            f"status: {status_str}, intent: {res.intent})"
        )

        return ChatResponse(
            success=res.success,
            session_id=payload.session_id,
            response_text=res.response_text or "",
            requires_confirmation=bool(res.requires_confirmation),
            requires_clarification=bool(res.requires_clarification),
            clarification_question=res.clarification_question,
            status=status_str,
            intent=str(res.intent),
            action_contract=contract_dict,
            error=res.error,
        )

    return app
