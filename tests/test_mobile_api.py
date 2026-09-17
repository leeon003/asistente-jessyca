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
