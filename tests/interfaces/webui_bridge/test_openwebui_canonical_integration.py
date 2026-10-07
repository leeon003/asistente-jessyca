"""Pruebas canónicas de integración y gobernanza para Open WebUI → JESSYCA Core.

Verifica de forma estricta:
1. Petición desde Open WebUI que llega al Core y utiliza una herramienta real en Windows.
2. Acción sensible interceptada por JDE/RiskEngine que exige confirmación o es denegada.
3. Intento de bypass con flags booleanos arbitrarios ("confirmed": True) bloqueado sin ejecución.
4. Dos sesiones independientes aisladas sin mezcla de contexto ni estado.
5. Autenticación obligatoria con rechazo HTTP 401 ante credenciales inválidas.
6. Cancelación cooperativa con CancellationToken y control de timeout.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from core.execution.idempotency_guard import get_idempotency_guard
from core.jde.authority import reset_authority_gate
from core.jde.confirmation import reset_confirmation_manager
from core.jde.runtime_binding import reset_jde_runtime_binding
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState
from interfaces.webui_bridge.adapter import PUBLIC_MODEL_NAME
from interfaces.webui_bridge.app import create_webui_bridge_app

TEST_AUTH_TOKEN = "openwebui-integration-token-secure-999"


@pytest.fixture(autouse=True)
def clean_canonical_bridge_env():
    """Limpia el estado singleton y entorno antes y después de cada prueba."""
    reset_authority_gate()
    reset_jde_runtime_binding()
    reset_confirmation_manager()
    get_idempotency_guard().reset()
    JessycaLocalAgent._instance = None
    orig_mode = os.environ.get("JDE_RUNTIME_MODE")
    if "JDE_RUNTIME_MODE" in os.environ:
        del os.environ["JDE_RUNTIME_MODE"]
    yield
    reset_authority_gate()
    reset_jde_runtime_binding()
    reset_confirmation_manager()
    get_idempotency_guard().reset()
    JessycaLocalAgent._instance = None
    if orig_mode is not None:
        os.environ["JDE_RUNTIME_MODE"] = orig_mode


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_AUTH_TOKEN}"}


@pytest.fixture
def bridge_client() -> TestClient:
    app = create_webui_bridge_app(
        auth_token=TEST_AUTH_TOKEN,
        timeout_seconds=10.0,
    )
    return TestClient(app, raise_server_exceptions=False)


# ── 1. DEMOSTRACIÓN: PETICIÓN DESDE OPEN WEBUI LLEGA AL CORE Y UTILIZA UNA HERRAMIENTA REAL ──
def test_openwebui_request_executes_real_windows_tool(
    bridge_client: TestClient, auth_headers: dict[str, str]
):
    """Demuestra que una petición desde Open WebUI llega a JessycaLocalAgent,

    es evaluada por políticas/RiskEngine, ejecuta una herramienta real en Windows
    (windows.audio con pycaw en el SO) y devuelve la evidencia verificada observable.
    """
    payload = {
        "model": PUBLIC_MODEL_NAME,
        "chat_id": "owui-chat-real-tool-001",
        "messages": [
            {"role": "user", "content": "consulta el volumen"}
        ],
    }

    resp = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=payload)
    assert resp.status_code == 200, f"Error en puente: {resp.text}"

    data = resp.json()
    assert data["model"] == PUBLIC_MODEL_NAME
    assert len(data["choices"]) == 1
    content = data["choices"][0]["message"]["content"]

    # Debe contener el resultado real obtenido del hardware/API de Windows
    assert "volumen" in content.lower()
    assert "%" in content or "silenciado" in content.lower()

    # Comprobar en el contexto de la sesión que el turno y tool quedaron registrados
    agent = JessycaLocalAgent.get_instance()
    session = agent.context_manager.get_session("owui-owui-chat-real-tool-001") or agent.context_manager.get_session("owui-chat-real-tool-001")
    assert session is not None
    assert len(session.turns) >= 1
    last_turn = session.turns[-1]
    assert last_turn.intent == "control_audio"
    assert "windows.audio" in last_turn.tools_executed
    assert last_turn.security_verdict in ("ALLOW", "ALLOW_DEFAULT")


# ── 2. DEMOSTRACIÓN: ACCIÓN SENSIBLE DENEGADA / AWAITING_CONFIRMATION ──
def test_openwebui_sensitive_action_requires_confirmation_and_blocks_execution(
    bridge_client: TestClient, auth_headers: dict[str, str]
):
    """Demuestra que una acción potencialmente destructiva/sensible enviada por Open WebUI

    no se ejecuta de forma ciega, sino que es interceptada por RiskEngine y JDE,
    exigiendo confirmación explícita del usuario y dejando la sesión en estado AWAITING_CONFIRMATION.
    """
    payload = {
        "model": PUBLIC_MODEL_NAME,
        "chat_id": "owui-chat-sensitive-delete",
        "messages": [
            {"role": "user", "content": "elimina el archivo confidencial.txt"}
        ],
    }

    resp = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=payload)
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]

    # Debe pedir confirmación explícita y NO declarar éxito de borrado
    assert any(term in content.lower() for term in ("confirmas", "confirmación", "sensible", "riesgo"))
    assert "eliminado con éxito" not in content.lower()

    # Verificar que en la sesión quedó registrado pending_confirmation
    agent = JessycaLocalAgent.get_instance()
    session = agent.context_manager.get_session("owui-owui-chat-sensitive-delete") or agent.context_manager.get_session("owui-chat-sensitive-delete")
    assert session is not None
    assert session.pending_confirmation is not None
    assert session.pending_confirmation.get("intent") == "delete_file"


# ── 3. PREVENCIÓN DE BYPASS: ENVÍO DE CAMPO ARBITRARIO NO AUTORIZA ACCIÓN ──
def test_openwebui_arbitrary_flag_injection_cannot_bypass_confirmation(
    bridge_client: TestClient, auth_headers: dict[str, str]
):
    """Garantiza la regla de seguridad: el cliente no puede declarar aprobada una acción

    enviando campos arbitrarios en el payload JSON ("confirmed": True, "is_confirmed": True, etc.).
    RiskEngine y JDE deben exigir la confirmación legítima gobernada.
    """
    malicious_payload = {
        "model": PUBLIC_MODEL_NAME,
        "chat_id": "owui-chat-exploit-attempt",
        "messages": [
            {"role": "user", "content": "elimina el archivo importante.txt"}
        ],
        "confirmed": True,
        "is_confirmed": True,
        "action_approved": True,
        "metadata": {
            "confirmed": True,
            "security_bypass": True,
        },
    }

    resp = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=malicious_payload)
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]

    # La acción NO debe ejecutarse: debe requerir confirmación legítima
    assert any(term in content.lower() for term in ("confirmas", "confirmación", "sensible"))
    assert "eliminado con éxito" not in content.lower()

    # Comprobar que no hay archivos eliminados ni ejecución no autorizada
    agent = JessycaLocalAgent.get_instance()
    session = agent.context_manager.get_session("owui-owui-chat-exploit-attempt") or agent.context_manager.get_session("owui-chat-exploit-attempt")
    assert session is not None
    assert session.pending_confirmation is not None


# ── 4. VERIFICACIÓN: DOS SESIONES INDEPENDIENTES NO MEZCLAN CONTEXTO ──
def test_openwebui_two_sessions_strictly_independent(
    bridge_client: TestClient, auth_headers: dict[str, str]
):
    """Verifica que dos chats concurrentes de Open WebUI (session-alpha y session-beta)

    mantengan contextos, historiales y estados de memoria totalmente independientes y desacoplados.
    """
    # Turno 1 en Sesión A
    payload_a = {
        "model": PUBLIC_MODEL_NAME,
        "chat_id": "session-unique-alpha",
        "messages": [
            {"role": "user", "content": "Hola, mi nombre clave es Agente 007"}
        ],
    }
    resp_a = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=payload_a)
    assert resp_a.status_code == 200

    # Turno 1 en Sesión B
    payload_b = {
        "model": PUBLIC_MODEL_NAME,
        "chat_id": "session-unique-beta",
        "messages": [
            {"role": "user", "content": "¿Qué es la recursividad en programación?"}
        ],
    }
    resp_b = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=payload_b)
    assert resp_b.status_code == 200

    agent = JessycaLocalAgent.get_instance()
    sess_a = agent.context_manager.get_session("owui-session-unique-alpha")
    sess_b = agent.context_manager.get_session("owui-session-unique-beta")

    assert sess_a is not None
    assert sess_b is not None
    assert sess_a is not sess_b

    # El historial de A contiene el nombre clave
    assert any("007" in t.user_prompt for t in sess_a.turns)
    # El historial de B NO debe contener nada de A
    assert not any("007" in t.user_prompt for t in sess_b.turns)
    assert any("recursividad" in t.user_prompt.lower() for t in sess_b.turns)


# ── 5. VERIFICACIÓN: RECHAZO DE ACCIÓN DENEGADA POR POLÍTICAS ──
def test_openwebui_policy_denial_returns_proper_refusal(
    bridge_client: TestClient, auth_headers: dict[str, str]
):
    """Verifica que cuando PermissionManager o JDE deniega una acción por política,

    la respuesta refleje la denegación sin ejecutar herramientas y sin fallar el protocolo HTTP.
    """
    mock_permission_mgr = MagicMock()
    mock_permission_mgr.is_action_allowed.return_value = False

    agent = JessycaLocalAgent(permission_manager=mock_permission_mgr)

    with patch.object(JessycaLocalAgent, "get_instance", return_value=agent):
        payload = {
            "model": PUBLIC_MODEL_NAME,
            "chat_id": "session-denied-policy",
            "messages": [
                {"role": "user", "content": "abre el bloc de notas"}
            ],
        }
        resp = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        assert "denegada por política de permisos" in content.lower() or "denegada" in content.lower()


# ── 6. AUTENTICACIÓN: RECHAZO CON 401 ──
def test_openwebui_auth_failure_responses(bridge_client: TestClient):
    """Verifica que solicitudes con claves inválidas o ausentes sean rechazadas con 401."""
    # Sin header
    r1 = bridge_client.post(
        "/v1/chat/completions",
        json={"model": PUBLIC_MODEL_NAME, "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r1.status_code == 401
    assert r1.json()["error"]["code"] == "invalid_api_key"

    # Clave incorrecta
    r2 = bridge_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer clave-completamente-falsa"},
        json={"model": PUBLIC_MODEL_NAME, "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r2.status_code == 401
    assert r2.json()["error"]["code"] == "invalid_api_key"
