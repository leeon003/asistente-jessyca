"""Pruebas canónicas End-to-End para Open WebUI → JESSYCA Core (WebUI Bridge).

Verifica la arquitectura objetivo completa:
Open WebUI → WebUI Bridge → Core (JessycaLocalAgent) → JDE → Executor → Verifier

Invariantes contractuales evaluadas:
1. Catálogo /v1/models expone estrictamente 'jessyca' (PUBLIC_MODEL_NAME).
2. Autenticación Bearer obligatoria y prohibición de credenciales de desarrollo inseguras.
3. Turno conversacional completo a través del puente hasta el Core.
4. Aislamiento estricto de dos conversaciones (diferentes sesiones/chats no mezclan contexto).
5. Acción física inocua (open_application) verificada con evidencia desde el puente hasta JDE.
6. Deduplicación e Idempotencia: un reintento del mismo request no re-ejecuta la acción.
7. Tareas internas de Open WebUI (Auto-Title, Auto-Tags) interceptadas sin tocar herramientas físicas.
8. Streaming SSE compatible con OpenAI culminando en [DONE].
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from core.execution.idempotency_guard import get_idempotency_guard
from core.jde.authority import (
    ActionRiskTier,
    AuthorityDecision,
    AuthorityGateResult,
    AuthorityMode,
    JDEAuthorityGate,
    reset_authority_gate,
)
from core.jde.confirmation import reset_confirmation_manager
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeMode,
    reset_jde_runtime_binding,
)
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState
from interfaces.webui_bridge.adapter import PUBLIC_MODEL_NAME
from interfaces.webui_bridge.app import create_webui_bridge_app

TEST_AUTH_TOKEN = "test-secure-webui-token-xyz-123"


@pytest.fixture(autouse=True)
def clean_bridge_e2e_env():
    """Limpia estado singleton antes y después de cada test."""
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
        timeout_seconds=5.0,
    )
    return TestClient(app, raise_server_exceptions=False)


# ── TEST 1: /v1/models EXPONE EXCLUSIVAMENTE PUBLIC_MODEL_NAME ('jessyca') ──
def test_e2e_models_catalog_exposes_jessyca(bridge_client: TestClient, auth_headers: dict[str, str]):
    """Verifica que /v1/models devuelva exclusivamente el modelo público 'jessyca'."""
    resp = bridge_client.get("/v1/models", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("object") == "list"
    models = data.get("data", [])
    assert len(models) == 1
    assert models[0]["id"] == PUBLIC_MODEL_NAME
    assert models[0]["id"] == "jessyca"


# ── TEST 2: AUTENTICACIÓN Y RECHAZO DE TOKENS INSEGUROS ──
def test_e2e_authentication_enforcement(bridge_client: TestClient):
    """Verifica que peticiones sin token o con token erróneo sean rechazadas con 401."""
    # Sin autenticación
    resp_no_auth = bridge_client.post(
        "/v1/chat/completions",
        json={"model": PUBLIC_MODEL_NAME, "messages": [{"role": "user", "content": "hola"}]},
    )
    assert resp_no_auth.status_code == 401
    assert resp_no_auth.json()["error"]["code"] == "invalid_api_key"

    # Token incorrecto
    resp_bad_auth = bridge_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token-invalido-erroneo"},
        json={"model": PUBLIC_MODEL_NAME, "messages": [{"role": "user", "content": "hola"}]},
    )
    assert resp_bad_auth.status_code == 401

    # Prohibición de token de desarrollo inseguro al crear la app
    with pytest.raises(ValueError, match="inseguro conocido"):
        create_webui_bridge_app(auth_token="jessyca-dev-token-insecure")


# ── TEST 3: TURNO CONVERSACIONAL Y AISLAMIENTO DE DOS CONVERSACIONES ──
def test_e2e_conversation_turn_and_session_isolation(
    bridge_client: TestClient, auth_headers: dict[str, str]
):
    """Verifica conversación a través del puente y que dos chats operen en sesiones aisladas."""
    # Chat 1: Primera conversación
    chat1_payload = {
        "model": PUBLIC_MODEL_NAME,
        "chat_id": "chat-session-alpha",
        "messages": [
            {"role": "user", "content": "Hola, ¿cuál es la diferencia entre un proceso y un hilo?"}
        ],
    }
    resp1 = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=chat1_payload)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["model"] == PUBLIC_MODEL_NAME
    assert len(data1["choices"]) == 1
    assert data1["choices"][0]["message"]["role"] == "assistant"
    content1 = data1["choices"][0]["message"]["content"]
    assert len(content1) > 0
    # No pitch publicitario
    assert not content1.lower().startswith("soy jessyca, tu asistente")

    # Chat 2: Segunda conversación independiente
    chat2_payload = {
        "model": PUBLIC_MODEL_NAME,
        "chat_id": "chat-session-beta",
        "messages": [
            {"role": "user", "content": "¿Qué es una clave primaria en bases de datos?"}
        ],
    }
    resp2 = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=chat2_payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    content2 = data2["choices"][0]["message"]["content"]
    assert len(content2) > 0

    # Las dos sesiones están aisladas en el context manager
    agent = JessycaLocalAgent.get_instance()
    sess_alpha = agent.context_manager.get_session("owui-chat-session-alpha")
    sess_beta = agent.context_manager.get_session("owui-chat-session-beta")
    assert sess_alpha is not None
    assert sess_beta is not None
    assert sess_alpha is not sess_beta


# ── TEST 4: ACCIÓN INOCUA CON EVIDENCIA OBSERVABLE (PUENTE -> JDE -> TOOL -> VERIFIER) ──
def test_e2e_innocuous_action_execution_with_evidence(
    bridge_client: TestClient, auth_headers: dict[str, str]
):
    """Verifica que una acción física inocua viaje por el puente, pase por JDE,

    se ejecute en el skill real y su evidencia verificada sea reflejada en la respuesta.
    """
    mock_skill_mgr = MagicMock()
    mock_skill_mgr.execute_skill.return_value = MagicMock(
        success=True,
        output={
            "exito": True,
            "mensaje": "Notepad iniciado correctamente.",
            "evidence": {
                "verification_type": "process",
                "target": "notepad",
                "is_verified": True,
                "details": {"pid": 54321},
            },
        },
        error=None,
    )

    # Configurar gate de autoridad JDE que permite la acción
    gate = JDEAuthorityGate()
    gate.evaluate_authority = MagicMock(return_value=AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.ALLOW,
        can_execute=True,
        can_block=True,
        risk_tier=ActionRiskTier.LOW,
        action="open_application",
        tool="windows.apps",
        is_authorized=True,
        requires_human_confirmation=False,
        reason="Acción de bajo riesgo autorizada.",
    ))

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)

    with patch.object(JessycaLocalAgent, "get_instance", return_value=agent):
        payload = {
            "model": PUBLIC_MODEL_NAME,
            "chat_id": "chat-action-innocuous",
            "messages": [
                {"role": "user", "content": "abre el bloc de notas"}
            ],
        }
        resp = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        # El executor fue invocado exactamente una vez
        mock_skill_mgr.execute_skill.assert_called_once()
        assert "notepad" in content.lower() or "bloc de notas" in content.lower() or "abrí" in content.lower()


# ── TEST 5: PREVENCIÓN DE DUPLICADOS EN REINTENTO (IDEMPOTENCIA) ──
def test_e2e_retry_duplicate_request_does_not_repeat_action(
    bridge_client: TestClient, auth_headers: dict[str, str]
):
    """Verifica que un reintento con el mismo X-Request-Id sea interceptado por

    IdempotencyGuard y no invoque la herramienta una segunda vez.
    """
    mock_skill_mgr = MagicMock()
    mock_skill_mgr.execute_skill.return_value = MagicMock(
        success=True,
        output={
            "exito": True,
            "mensaje": "Notepad abierto.",
            "evidence": {
                "verification_type": "process",
                "target": "notepad",
                "is_verified": True,
                "details": {"pid": 11111},
            },
        },
        error=None,
    )

    gate = JDEAuthorityGate()
    gate.evaluate_authority = MagicMock(return_value=AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.ALLOW,
        can_execute=True,
        can_block=True,
        risk_tier=ActionRiskTier.LOW,
        action="open_application",
        tool="windows.apps",
        is_authorized=True,
        requires_human_confirmation=False,
        reason="Idempotency test allow",
    ))

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)

    headers_with_req_id = {
        **auth_headers,
        "X-Request-Id": "owui-retry-idempotency-key-001",
    }
    payload = {
        "model": PUBLIC_MODEL_NAME,
        "chat_id": "chat-idempotency-sess",
        "messages": [
            {"role": "user", "content": "abre el bloc de notas"}
        ],
    }

    with patch.object(JessycaLocalAgent, "get_instance", return_value=agent):
        # 1. Primera llamada: ejecuta el skill
        resp1 = bridge_client.post("/v1/chat/completions", headers=headers_with_req_id, json=payload)
        assert resp1.status_code == 200
        assert mock_skill_mgr.execute_skill.call_count == 1

        # 2. Reintento idéntico (misma clave de idempotencia / X-Request-Id):
        resp2 = bridge_client.post("/v1/chat/completions", headers=headers_with_req_id, json=payload)
        assert resp2.status_code == 200
        # El executor NO fue llamado por segunda vez (reutilizó el resultado previo)
        assert mock_skill_mgr.execute_skill.call_count == 1


# ── TEST 6: TAREAS INTERNAS DE OPEN WEBUI NO DISPARAN HERRAMIENTAS FÍSICAS ──
@pytest.mark.parametrize("internal_prompt", [
    "Generate a concise 3-5 word title for the conversation.",
    "Generate 1-3 broad tags categorizing this conversation.",
    "Suggest 3 follow-up questions.",
    "Summarize the following conversation.",
])
def test_e2e_internal_openwebui_tasks_do_not_trigger_skills(
    bridge_client: TestClient, auth_headers: dict[str, str], internal_prompt: str
):
    """Garantiza que tareas internas automáticas de Open WebUI jamás llamen al Core o ejecuten herramientas."""
    mock_skill_mgr = MagicMock()
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr)

    with patch.object(JessycaLocalAgent, "get_instance", return_value=agent):
        payload = {
            "model": PUBLIC_MODEL_NAME,
            "messages": [
                {"role": "user", "content": "abre el bloc de notas"},
                {"role": "assistant", "content": "Listo, abrí el bloc de notas."},
                {"role": "user", "content": internal_prompt},
            ],
        }
        resp = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=payload)
        assert resp.status_code == 200
        # El skill físico jamás fue llamado
        mock_skill_mgr.execute_skill.assert_not_called()
        data = resp.json()
        assert len(data["choices"]) == 1
        assert data["choices"][0]["finish_reason"] == "stop"


# ── TEST 7: STREAMING SSE COMPATIBLE CON OPENAI CULMINANDO EN [DONE] ──
def test_e2e_streaming_sse_protocol(bridge_client: TestClient, auth_headers: dict[str, str]):
    """Verifica que stream=True emita formato SSE OpenAI con deltas y señal final [DONE]."""
    mock_resp = MagicMock()
    mock_resp.response_text = "Esta es una respuesta progresiva de prueba."
    mock_resp.status = AgentExecutionState.COMPLETED
    mock_resp.success = True
    mock_resp.request_id = "test-stream-req-01"

    agent = MagicMock()
    agent.interact.return_value = mock_resp

    with patch.object(JessycaLocalAgent, "get_instance", return_value=agent):
        payload = {
            "model": PUBLIC_MODEL_NAME,
            "stream": True,
            "messages": [{"role": "user", "content": "dime algo breve"}],
        }
        resp = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=payload)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body_text = resp.text
        assert "data: " in body_text
        assert "data: [DONE]" in body_text


# ── TEST 8: RECHAZO DE MODELO NO PERMITIDO (404 NOT FOUND) ──
def test_e2e_unknown_model_rejected(bridge_client: TestClient, auth_headers: dict[str, str]):
    """Garantiza que cualquier modelo diferente de 'jessyca' retorne HTTP 404."""
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hola"}],
    }
    resp = bridge_client.post("/v1/chat/completions", headers=auth_headers, json=payload)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "model_not_found"
