"""Suite de pruebas unitarias y de integración para JESSYCA Mobile API Bridge.

Valida:
- Health check (/api/v1/health) responde HTTP 200 sin invocar al LLM.
- Autenticación básica con X-Jessyca-Token (rechazo ante token ausente o inválido).
- Validación estricta de payloads (rechazo de mensaje ausente o vacío).
- Delegación correcta hacia JessycaLocalAgent.interact() mediante JessycaRequest oficial.
- Conservación íntegra de confirmaciones, aclaraciones y contratos de acción.
- Manejo controlado de excepciones del Core sin filtrar stack traces al cliente.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from config.settings import AppSettings
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
    JessycaResponse,
)
from interfaces.mobile_api.app import create_mobile_api_app
from interfaces.mobile_api.models import ChatResponse, HealthResponse
from main import parse_arguments


@pytest.fixture
def mock_settings() -> AppSettings:
    """Configuración de prueba para aislar tests."""
    return AppSettings(
        MOBILE_API_ENABLED=True,
        MOBILE_API_HOST="127.0.0.1",
        MOBILE_API_PORT=8765,
        MOBILE_API_AUTH_TOKEN="test-secret-token",
        MOBILE_API_TIMEOUT=5,
    )


@pytest.fixture
def test_client(mock_settings: AppSettings) -> TestClient:
    """Cliente de prueba de FastAPI configurado con settings mockeados."""
    app = create_mobile_api_app(settings=mock_settings)
    # Ignoramos lifespan para tests unitarios rápidos y aislados
    return TestClient(app, raise_server_exceptions=False)


# ── TEST 1: HEALTH CHECK ──


def test_01_health_check_endpoint(test_client: TestClient) -> None:
    """Verifica que /api/v1/health responda HTTP 200 y el estado esperado sin requerir auth."""
    response = test_client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    validated = HealthResponse.model_validate(data)
    assert validated.success is True
    assert validated.service == "jessyca-mobile-api"
    assert validated.status == "online"


# ── TEST 2: AUTENTICACIÓN ──


def test_02_auth_missing_token_rejected(test_client: TestClient) -> None:
    """Verifica que una solicitud sin el encabezado X-Jessyca-Token sea rechazada con 401."""
    response = test_client.post(
        "/api/v1/chat",
        json={"session_id": "test-session", "message": "Hola"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert "Token de autenticación inválido o ausente" in data["error"]


def test_03_auth_invalid_token_rejected(test_client: TestClient) -> None:
    """Verifica que un token incorrecto sea rechazado con 401."""
    response = test_client.post(
        "/api/v1/chat",
        headers={"X-Jessyca-Token": "token-totalmente-erroneo"},
        json={"session_id": "test-session", "message": "Hola"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False


# ── TEST 3: VALIDACIÓN DE PAYLOAD ──


def test_04_validation_missing_message_rejected(test_client: TestClient, mock_settings: AppSettings) -> None:
    """Verifica que un payload sin el campo requerido 'message' sea rechazado con 422."""
    response = test_client.post(
        "/api/v1/chat",
        headers={"X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN},
        json={"session_id": "test-session"},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert "Error de validación" in data["error"]


def test_05_validation_empty_whitespace_message_rejected(
    test_client: TestClient, mock_settings: AppSettings
) -> None:
    """Verifica que un mensaje compuesto solo de espacios en blanco sea rechazado con 422."""
    response = test_client.post(
        "/api/v1/chat",
        headers={"X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN},
        json={"session_id": "test-session", "message": "    "},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False


# ── TEST 4: DELEGACIÓN Y PROCESAMIENTO CON CORE ──


def test_06_chat_delegation_to_core_pipeline(test_client: TestClient, mock_settings: AppSettings) -> None:
    """Verifica que la petición se transforme en JessycaRequest oficial y se invoque agent.interact()."""
    mock_agent_response = JessycaResponse(
        request_id="req-test-123",
        session_id="android-session-001",
        success=True,
        status=AgentExecutionState.COMPLETED,
        response_text="Hola, soy Jessyca. ¿En qué puedo colaborarte hoy?",
        intent="conversational.greeting",
        requires_confirmation=False,
        requires_clarification=False,
    )

    with patch("interfaces.mobile_api.app.JessycaLocalAgent.get_instance") as mock_get_instance:
        mock_agent = MagicMock()
        mock_agent.interact.return_value = mock_agent_response
        mock_get_instance.return_value = mock_agent

        response = test_client.post(
            "/api/v1/chat",
            headers={"X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN},
            json={
                "session_id": "android-session-001",
                "message": "Hola Jessyca",
                "device_id": "pixel-7-pro",
            },
        )

        assert response.status_code == 200
        data = response.json()
        validated = ChatResponse.model_validate(data)

        assert validated.success is True
        assert validated.session_id == "android-session-001"
        assert validated.response_text == "Hola, soy Jessyca. ¿En qué puedo colaborarte hoy?"
        assert validated.requires_confirmation is False
        assert validated.requires_clarification is False
        assert validated.intent == "conversational.greeting"
        assert validated.status == "COMPLETED"

        # Validar la construcción exacta del objeto JessycaRequest
        mock_agent.interact.assert_called_once()
        invoked_req = mock_agent.interact.call_args[0][0]
        assert isinstance(invoked_req, JessycaRequest)
        assert invoked_req.session_id == "android-session-001"
        assert invoked_req.user_input == "Hola Jessyca"
        assert invoked_req.modality == InputModality.TEXT
        assert invoked_req.metadata["source"] == "mobile_android"
        assert invoked_req.metadata["device_id"] == "pixel-7-pro"


# ── TEST 5: PRESERVACIÓN DE ESTADOS CRÍTICOS (CONFIRMACIÓN Y CLARIFICACIÓN) ──


def test_07_chat_preserves_confirmation_and_clarification(
    test_client: TestClient, mock_settings: AppSettings
) -> None:
    """Verifica que si la acción requiere confirmación o clarificación, no se pierdan los estados."""
    mock_agent_response = JessycaResponse(
        request_id="req-confirm-123",
        session_id="android-danger-session",
        success=True,
        status=AgentExecutionState.AWAITING_CONFIRMATION,
        response_text="¿Deseas realmente cerrar todos los procesos de bloc de notas?",
        intent="system.apps.close",
        requires_confirmation=True,
        requires_clarification=True,
        clarification_question="Por favor confirma 'si' o 'no'.",
    )

    with patch("interfaces.mobile_api.app.JessycaLocalAgent.get_instance") as mock_get_instance:
        mock_agent = MagicMock()
        mock_agent.interact.return_value = mock_agent_response
        mock_get_instance.return_value = mock_agent

        response = test_client.post(
            "/api/v1/chat",
            headers={"X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN},
            json={
                "session_id": "android-danger-session",
                "message": "cierra el bloc de notas",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["requires_confirmation"] is True
        assert data["requires_clarification"] is True
        assert data["clarification_question"] == "Por favor confirma 'si' o 'no'."
        assert data["status"] == "AWAITING_CONFIRMATION"


# ── TEST 6: MANEJO CONTROLADO DE ERRORES DEL CORE ──


def test_08_core_exception_returns_controlled_500_without_traceback(
    test_client: TestClient, mock_settings: AppSettings
) -> None:
    """Verifica que una falla no capturada en el Core devuelva HTTP 500 sin exponer tracebacks."""
    with patch("interfaces.mobile_api.app.JessycaLocalAgent.get_instance") as mock_get_instance:
        mock_agent = MagicMock()
        mock_agent.interact.side_effect = RuntimeError("Fallo crítico en base de datos interna o LLM")
        mock_get_instance.return_value = mock_agent

        response = test_client.post(
            "/api/v1/chat",
            headers={"X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN},
            json={"session_id": "session-fail", "message": "Hola"},
        )

        assert response.status_code == 500
        data = response.json()
        assert data["success"] is False
        assert "Ocurrió un error interno" in data["error"]
        # Asegurar que el mensaje técnico de la excepción NO se filtre al cliente
        assert "Fallo crítico en base de datos" not in str(data)
        assert "Traceback" not in str(data)


# ── TEST 7: CLI LAUNCHER (main.py --mobile) ──


def test_09_cli_mobile_flag_parsing() -> None:
    """Verifica que el argumento --mobile sea reconocido exclusivamente por el launcher."""
    args = parse_arguments(["--mobile"])
    assert args.mobile is True
    assert args.demo is False
    assert args.mcp is False
    assert args.voice is False


def test_10_cli_mobile_with_custom_host_and_port() -> None:
    """Verifica que --mobile acepte flags opcionales --host y --port."""
    args = parse_arguments(["--mobile", "--host", "192.168.1.50", "--port", "9000"])
    assert args.mobile is True
    assert args.host == "192.168.1.50"
    assert args.port == 9000


# ── TEST 8: SEGURIDAD DE TOKEN OBLIGATORIO Y RECHAZO DE VALORES INSEGUROS ──


def test_11_factory_fails_without_secret_before_effects() -> None:
    """Verifica que create_mobile_api_app falle inmediatamente si el token no está configurado."""
    empty_settings = AppSettings(
        MOBILE_API_ENABLED=True,
        MOBILE_API_AUTH_TOKEN="",
    )
    with patch("interfaces.mobile_api.app.JessycaLocalAgent.get_instance") as mock_agent_get:
        with pytest.raises(ValueError, match="MOBILE_API_AUTH_TOKEN es obligatorio"):
            create_mobile_api_app(settings=empty_settings)
        # Garantizar que no hubo efectos secundarios ni instanciación del agente
        mock_agent_get.assert_not_called()


def test_12_factory_fails_with_whitespace_secret_before_effects() -> None:
    """Verifica que create_mobile_api_app rechace tokens compuestos solo de espacios en blanco."""
    whitespace_settings = AppSettings(
        MOBILE_API_ENABLED=True,
        MOBILE_API_AUTH_TOKEN="    ",
    )
    with patch("interfaces.mobile_api.app.JessycaLocalAgent.get_instance") as mock_agent_get:
        with pytest.raises(ValueError, match="espacios en blanco"):
            create_mobile_api_app(settings=whitespace_settings)
        mock_agent_get.assert_not_called()


def test_13_factory_fails_with_insecure_dev_token_before_effects() -> None:
    """Verifica que create_mobile_api_app rechace el valor inseguro de desarrollo conocido."""
    dev_token_settings = AppSettings(
        MOBILE_API_ENABLED=True,
        MOBILE_API_AUTH_TOKEN="jessyca-dev-token-insecure",
    )
    with patch("interfaces.mobile_api.app.JessycaLocalAgent.get_instance") as mock_agent_get:
        with pytest.raises(ValueError, match="token de desarrollo inseguro conocido"):
            create_mobile_api_app(settings=dev_token_settings)
        mock_agent_get.assert_not_called()


# ── TEST 9: ARRANQUE DEL SERVIDOR (run_mobile_server) ──


def test_14_run_mobile_server_aborts_without_valid_secret() -> None:
    """Verifica que run_mobile_server retorne código 1 sin iniciar uvicorn si el token es inválido."""
    bad_settings = AppSettings(
        MOBILE_API_ENABLED=True,
        MOBILE_API_AUTH_TOKEN="jessyca-dev-token-insecure",
    )
    from interfaces.mobile_api.server import run_mobile_server
    with patch("uvicorn.Server.run") as mock_run:
        exit_code = run_mobile_server(settings=bad_settings)
        assert exit_code == 1
        mock_run.assert_not_called()


def test_15_disabled_flag_prevents_server_start_unless_forced() -> None:
    """Verifica que MOBILE_API_ENABLED=False impida arrancar a menos que force=True."""
    from interfaces.mobile_api.server import run_mobile_server
    disabled_settings = AppSettings(
        MOBILE_API_ENABLED=False,
        MOBILE_API_AUTH_TOKEN="valid-production-secret-token-32ch",
    )
    with patch("uvicorn.Server.run") as mock_run:
        # 1. Sin force -> aborta con 1
        exit_code = run_mobile_server(settings=disabled_settings, force=False)
        assert exit_code == 1
        mock_run.assert_not_called()

        # 2. Con force -> procede a ejecutar el servidor
        exit_code_forced = run_mobile_server(settings=disabled_settings, force=True)
        assert exit_code_forced == 0
        mock_run.assert_called_once()


# ── TEST 10: POLÍTICA DE RED (LOOPBACK POR DEFECTO Y ADVERTENCIA LAN) ──


def test_16_network_options_default_loopback_and_lan_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Verifica que el host por defecto sea loopback y que escuchar en LAN emita una advertencia."""
    settings = AppSettings(MOBILE_API_AUTH_TOKEN="valid-production-secret-token-32ch")
    assert settings.MOBILE_API_HOST == "127.0.0.1"

    from interfaces.mobile_api.server import run_mobile_server
    with patch("uvicorn.Server.run"):
        with caplog.at_level("WARNING"):
            # Escucha en LAN 0.0.0.0
            run_mobile_server(host="0.0.0.0", settings=settings)
            assert any("ADVERTENCIA DE RED" in r.message for r in caplog.records)


# ── TEST 11: CONFIGURACIÓN DEFENSIVA DE CORS ──


def test_17_cors_unauthorized_origin_denied() -> None:
    """Verifica que orígenes no autorizados no reciban permisos CORS y orígenes autorizados sí."""
    cors_settings = AppSettings(
        MOBILE_API_ENABLED=True,
        MOBILE_API_AUTH_TOKEN="valid-production-secret-token-32ch",
        MOBILE_API_CORS_ORIGINS=["https://app.jessyca.internal"],
    )
    app = create_mobile_api_app(settings=cors_settings)
    client = TestClient(app, raise_server_exceptions=False)

    # 1. Origen no autorizado
    res_unauth = client.get("/api/v1/health", headers={"Origin": "https://malicious.evil.com"})
    assert res_unauth.status_code == 200
    assert "access-control-allow-origin" not in res_unauth.headers

    # 2. Origen autorizado
    res_auth = client.get("/api/v1/health", headers={"Origin": "https://app.jessyca.internal"})
    assert res_auth.status_code == 200
    assert res_auth.headers.get("access-control-allow-origin") == "https://app.jessyca.internal"
    assert res_auth.headers.get("access-control-allow-credentials") == "true"


def test_18_cors_no_wildcard_combined_with_credentials() -> None:
    """Verifica que si se configura comodín '*', allow_credentials sea estrictamente False."""
    wildcard_settings = AppSettings(
        MOBILE_API_ENABLED=True,
        MOBILE_API_AUTH_TOKEN="valid-production-secret-token-32ch",
        MOBILE_API_CORS_ORIGINS=["*"],
    )
    app = create_mobile_api_app(settings=wildcard_settings)
    client = TestClient(app, raise_server_exceptions=False)

    res = client.get("/api/v1/health", headers={"Origin": "https://anywhere.org"})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "*"
    assert res.headers.get("access-control-allow-credentials") is None


def test_19_docs_and_schema_exposure_toggle(mock_settings: AppSettings) -> None:
    """Verifica el control explícito de exposición de /docs y /openapi.json."""
    # Por defecto en producción: deshabilitado
    app_no_docs = create_mobile_api_app(settings=mock_settings, enable_docs=False)
    client_no_docs = TestClient(app_no_docs, raise_server_exceptions=False)
    assert client_no_docs.get("/docs").status_code == 404
    assert client_no_docs.get("/openapi.json").status_code == 404

    # Habilitado explícitamente
    app_with_docs = create_mobile_api_app(settings=mock_settings, enable_docs=True)
    client_with_docs = TestClient(app_with_docs, raise_server_exceptions=False)
    assert client_with_docs.get("/docs").status_code == 200
    assert client_with_docs.get("/openapi.json").status_code == 200


def test_20_cli_mobile_with_force_flag() -> None:
    """Verifica que el argumento --force sea parseado correctamente junto con --mobile."""
    args = parse_arguments(["--mobile", "--force"])
    assert args.mobile is True
    assert args.force is True

