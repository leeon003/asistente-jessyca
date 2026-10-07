"""Aplicación FastAPI para JESSYCA Mobile API Bridge (JESSYCA 4.0 Core ↔ Mobile).

Expone endpoints HTTP asíncronos para comunicación con el cliente Android,
delegando el procesamiento al agente local unificado sin bloquear el loop de eventos.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.manager import get_settings
from config.settings import AppSettings
from core.execution.operation_manager import (
    ConcurrencyLimitError,
    IdempotencyConflictError,
    OperationStatus,
    SessionIsolationError,
    get_operation_manager,
)
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import InputModality, JessycaRequest
from core.logger import get_logger
from interfaces.mobile_api.models import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthResponse,
    OperationStatusResponse,
)

logger = get_logger("jessyca.mobile_api")

INSECURE_DEV_TOKENS = frozenset({
    "jessyca-dev-token-insecure",
})


def validate_mobile_api_token(token: str | None) -> str:
    """Valida la presencia y seguridad del token de Mobile API antes de cualquier efecto.

    Raises:
        ValueError: Si el token es nulo, vacío, solo espacios o el valor inseguro conocido de desarrollo.
    """
    if token is None or not isinstance(token, str):
        raise ValueError(
            "MOBILE_API_AUTH_TOKEN es obligatorio y no está configurado. "
            "Por seguridad, Mobile API requiere un token de autenticación obligatorio para iniciar."
        )
    cleaned = token.strip()
    if not cleaned:
        raise ValueError(
            "MOBILE_API_AUTH_TOKEN es obligatorio y no puede estar vacío ni contener únicamente espacios en blanco."
        )
    if cleaned.lower() in INSECURE_DEV_TOKENS:
        raise ValueError(
            f"El valor de token '{cleaned}' es un token de desarrollo inseguro conocido y está "
            "terminantemente prohibido en ejecución normal. Configure un token secreto robusto."
        )
    return cleaned


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
    try:
        op_manager = get_operation_manager()
        await op_manager.shutdown(grace_period=2.0)
    except Exception as exc:
        logger.warning(f"[Mobile API] Error en shutdown de OperationManager: {exc}")



def create_mobile_api_app(
    settings: AppSettings | None = None,
    auth_token: str | None = None,
    enable_docs: bool | None = None,
) -> FastAPI:
    """Fábrica de la aplicación FastAPI para Mobile API Bridge.

    Valida estrictamente el token antes de instanciar la aplicación o inicializar el agente.
    """
    import os

    active_settings = settings or get_settings()

    token_candidate = auth_token
    if token_candidate is None:
        token_candidate = getattr(active_settings, "MOBILE_API_AUTH_TOKEN", "")
        if not token_candidate:
            token_candidate = os.getenv("MOBILE_API_AUTH_TOKEN", "")

    # 1. Validación estricta inmediata antes de cualquier efecto secundario
    configured_token = validate_mobile_api_token(token_candidate)

    # 2. Exposición controlada de documentación OpenAPI
    docs_allowed = (
        enable_docs
        if enable_docs is not None
        else getattr(active_settings, "MOBILE_API_DOCS_ENABLED", False)
    )
    docs_url = "/docs" if docs_allowed else None
    redoc_url = "/redoc" if docs_allowed else None
    openapi_url = "/openapi.json" if docs_allowed else None

    # Endpoints exentos de autenticación (docs siempre exentos para permitir 404 nativo si están desactivados)
    public_paths = {"/api/v1/health", "/docs", "/openapi.json", "/redoc"}

    app = FastAPI(
        title="JESSYCA Mobile API Bridge",
        description="Puente HTTP/REST para integración oficial entre JESSYCA Core y Android.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    # 3. Configuración CORS defensiva (sin comodín con credenciales)
    cors_origins = list(getattr(active_settings, "MOBILE_API_CORS_ORIGINS", []))
    if cors_origins:
        has_wildcard = "*" in cors_origins
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=not has_wildcard,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

    # ── MIDDLEWARE DE AUTENTICACIÓN ──
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """Verifica el token de autorización en el encabezado X-Jessyca-Token usando comparación constante."""
        if request.url.path in public_paths or request.method == "OPTIONS":
            return await call_next(request)

        client_token = request.headers.get("X-Jessyca-Token")

        # Rechazar si no se provee token o si no coincide (comparación en tiempo constante)
        if not client_token or not secrets.compare_digest(client_token, configured_token):
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
            409: {"model": ErrorResponse, "description": "Conflicto de clave de idempotencia"},
            422: {"model": ErrorResponse, "description": "Error de validación"},
            429: {"model": ErrorResponse, "description": "Límite de concurrencia excedido"},
            500: {"model": ErrorResponse, "description": "Error interno del servidor"},
            504: {"model": ErrorResponse, "description": "Timeout al procesar la solicitud"},
        },
        summary="Canal conversacional oficial para cliente móvil",
        description="Transforma la solicitud a JessycaRequest y delega a JessycaLocalAgent con deduplicación y timeout desacoplado.",
    )
    async def chat_endpoint(payload: ChatRequest, request: Request) -> Any:
        # 1. Determinar clave de idempotencia e identidad estable
        op_key = (
            request.headers.get("Idempotency-Key")
            or request.headers.get("X-Request-ID")
            or payload.idempotency_key
            or payload.request_id
            or f"req-{uuid.uuid4().hex[:12]}"
        ).strip()

        logger.info(
            f"[Mobile API CHAT] Petición recibida (session_id: {payload.session_id}, "
            f"operation_id: {op_key}, device_id: {payload.device_id or 'none'}, longitud: {len(payload.message)})"
        )

        payload_dict = {
            "session_id": payload.session_id,
            "message": payload.message,
            "device_id": payload.device_id,
        }

        op_manager = get_operation_manager()
        timeout_sec = float(active_settings.MOBILE_API_TIMEOUT or 30)

        # 2. Deduplicación atómica: verificar si la operación ya existe
        try:
            record, is_new = await op_manager.acquire_or_join(
                session_id=payload.session_id,
                operation_id=op_key,
                payload=payload_dict,
                max_execution_timeout=timeout_sec * 3,
            )
        except IdempotencyConflictError as conflict_err:
            logger.warning(
                f"[Mobile API CONFLICT] Idempotency key '{op_key}' reutilizada con payload distinto para sesión '{payload.session_id}': {conflict_err}"
            )
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "success": False,
                    "session_id": payload.session_id,
                    "operation_id": op_key,
                    "error": "Conflicto de idempotencia: La clave de operación ya fue utilizada con un payload diferente.",
                },
            )
        except ConcurrencyLimitError:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "success": False,
                    "session_id": payload.session_id,
                    "operation_id": op_key,
                    "error": "Límite de concurrencia excedido en JESSYCA Core. Intente más tarde.",
                },
            )

        # 3. Si es una nueva operación, lanzar worker protegido
        if is_new:
            def _execute_agent():
                req = JessycaRequest(
                    request_id=op_key,
                    session_id=payload.session_id,
                    user_input=payload.message,
                    modality=InputModality.TEXT,
                    metadata={
                        "source": "mobile_android",
                        "device_id": payload.device_id,
                        "operation_record": record,
                    },
                    monotonic_deadline=record.monotonic_deadline,
                )
                agent = JessycaLocalAgent.get_instance()
                try:
                    return agent.interact(req, cancellation_token=record.cancellation_token)
                except TypeError:
                    return agent.interact(req)

            op_manager.run_operation(record, _execute_agent)


        # 4. Esperar hasta el deadline HTTP desacoplado del ciclo de ejecución
        # Si la operación ya estaba completa (idempotent replay)
        if record.status == OperationStatus.COMPLETED and record.result is not None:
            res = record.result
        elif record.status == OperationStatus.FAILED:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "success": False,
                    "session_id": payload.session_id,
                    "operation_id": op_key,
                    "error": record.error or "La operación falló en JESSYCA Core.",
                },
            )
        elif record.status == OperationStatus.CANCELLED:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "session_id": payload.session_id,
                    "operation_id": op_key,
                    "status": "CANCELLED",
                    "error": "La operación fue cancelada antes de su ejecución.",
                },
            )
        else:
            if record.task is None:
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={"success": False, "error": "Estado de tarea inconsistente."},
                )

            try:
                res = await asyncio.wait_for(
                    asyncio.shield(record.task),
                    timeout=timeout_sec,
                )
            except TimeoutError:
                # El deadline HTTP expiró; la tarea en segundo plano CONTINÚA ejecutándose
                logger.error(
                    f"[Mobile API CHAT] Timeout HTTP de {timeout_sec}s excedido para session_id "
                    f"'{payload.session_id}', operation_id '{op_key}'. La operación continúa en segundo plano."
                )
                return JSONResponse(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    content={
                        "success": False,
                        "session_id": payload.session_id,
                        "operation_id": op_key,
                        "status": record.status.value,
                        "error": f"Tiempo de espera HTTP ({timeout_sec}s) excedido. La tarea continúa en segundo plano.",
                        "poll_url": f"/api/v1/operations/{op_key}?session_id={payload.session_id}",
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
                        "operation_id": op_key,
                        "error": "Ocurrió un error interno al procesar tu solicitud en JESSYCA Core.",
                    },
                )

        # 5. Mapear respuesta completa respetando contratos y estados
        contract_dict = None
        if getattr(res, "action_intent_contract", None) is not None:
            contract = res.action_intent_contract
            if hasattr(contract, "to_dict"):
                contract_dict = contract.to_dict()

        status_str = getattr(res.status, "value", str(res.status)) if hasattr(res, "status") else "COMPLETED"

        logger.info(
            f"[Mobile API CHAT] Respuesta generada con éxito (session_id: {payload.session_id}, "
            f"operation_id: {op_key}, status: {status_str}, intent: {getattr(res, 'intent', 'unknown')})"
        )

        return ChatResponse(
            success=getattr(res, "success", True),
            session_id=payload.session_id,
            response_text=getattr(res, "response_text", "") or "",
            requires_confirmation=bool(getattr(res, "requires_confirmation", False)),
            requires_clarification=bool(getattr(res, "requires_clarification", False)),
            clarification_question=getattr(res, "clarification_question", None),
            status=status_str,
            intent=str(getattr(res, "intent", "unknown")),
            action_contract=contract_dict,
            operation_id=op_key,
            error=getattr(res, "error", None),
        )

    @app.get(
        "/api/v1/operations/{operation_id}",
        response_model=OperationStatusResponse,
        summary="Consulta el estado y resultado de una operación",
        description="Permite consultar el estado (PENDING, RUNNING, COMPLETED, CANCELLED, UNKNOWN) respetando aislamiento de sesión.",
    )
    async def get_operation_endpoint(operation_id: str, request: Request) -> Any:
        session_id = request.query_params.get("session_id") or request.headers.get("X-Session-ID") or ""
        op_manager = get_operation_manager()
        try:
            record = op_manager.get_operation(session_id=session_id, operation_id=operation_id)
        except SessionIsolationError:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "success": False,
                    "error": "Acceso denegado: Violación de aislamiento de sesión.",
                },
            )

        if record is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "success": False,
                    "error": f"Operación '{operation_id}' no encontrada.",
                },
            )

        rec_dict = record.to_dict()
        return OperationStatusResponse(
            success=True,
            operation_id=record.operation_id,
            session_id=record.session_id,
            status=record.status.value,
            effect_started=record.effect_started,
            created_at=record.created_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
            result=rec_dict.get("result"),
            error=record.error,
        )

    @app.post(
        "/api/v1/operations/{operation_id}/cancel",
        response_model=OperationStatusResponse,
        summary="Solicita la cancelación cooperativa de una operación",
        description="Emite señal de cancelación al CancellationToken de la operación respetando aislamiento.",
    )
    async def cancel_operation_endpoint(operation_id: str, request: Request) -> Any:
        session_id = request.query_params.get("session_id") or request.headers.get("X-Session-ID") or ""
        op_manager = get_operation_manager()
        try:
            record = op_manager.cancel_operation(session_id=session_id, operation_id=operation_id)
        except SessionIsolationError:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "success": False,
                    "error": "Acceso denegado: Violación de aislamiento de sesión.",
                },
            )
        except KeyError:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "success": False,
                    "error": f"Operación '{operation_id}' no encontrada.",
                },
            )

        rec_dict = record.to_dict()
        return OperationStatusResponse(
            success=True,
            operation_id=record.operation_id,
            session_id=record.session_id,
            status=record.status.value,
            effect_started=record.effect_started,
            created_at=record.created_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
            result=rec_dict.get("result"),
            error=record.error,
            message="Cancelación solicitada cooperativamente.",
        )

    return app
