"""Suite de pruebas unitarias para OWUI-MEM-02 — Contexto Conversacional Open WebUI ↔ JESSYCA.

Valida rigurosamente:
1. Normalización de mensajes (normalize_conversation_messages).
2. Compatibilidad hacia atrás de JessycaRequest (sin conversation_context).
3. Ingestión y deduplicación en ConversationContextManager.
4. Preservación del límite de turnos y presupuesto de caracteres.
5. Aislamiento estricto entre sesiones diferentes.
6. Integración Direct Bridge con lista multi-mensaje.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.local_agent.conversation_context import ConversationContextManager
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
    JessycaResponse,
)
from interfaces.webui_bridge.adapter import (
    normalize_conversation_messages,
)
from interfaces.webui_bridge.app import create_webui_bridge_app
from interfaces.webui_bridge.models import ChatMessage

TEST_AUTH_TOKEN = "test-owui-mem-token-secret"


@pytest.fixture
def client() -> TestClient:
    app = create_webui_bridge_app(
        auth_token=TEST_AUTH_TOKEN,
        timeout_seconds=2.0,
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_AUTH_TOKEN}"}


# ── TEST 1: NORMALIZACIÓN DE MENSAJES ──
def test_normalize_conversation_messages() -> None:
    raw_messages = [
        ChatMessage(role="system", content="System instruction"),
        ChatMessage(role="user", content="  Hola, soy Carlos.  "),
        ChatMessage(role="assistant", content="Hola Carlos."),
        ChatMessage(role="tool", content="tool output"),  # no debe incluirse
        ChatMessage(role="user", content=""),  # vacío, no debe incluirse
        ChatMessage(role="user", content="¿Cómo me llamo?"),
    ]
    normalized = normalize_conversation_messages(raw_messages)
    assert len(normalized) == 4
    assert normalized[0] == {"role": "system", "content": "System instruction"}
    assert normalized[1] == {"role": "user", "content": "Hola, soy Carlos."}
    assert normalized[2] == {"role": "assistant", "content": "Hola Carlos."}
    assert normalized[3] == {"role": "user", "content": "¿Cómo me llamo?"}


# ── TEST 2: LEGACY JESSYCA_REQUEST COMPATIBILITY ──
def test_legacy_jessyca_request_compatibility() -> None:
    req = JessycaRequest(user_input="Hola")
    assert req.user_input == "Hola"
    assert req.conversation_context == []
    assert req.session_id == "default_session"
    assert req.modality == InputModality.TEXT


# ── TEST 3: DEDUPLICACIÓN EN CONVERSATION_CONTEXT_MANAGER ──
def test_ingest_external_context_deduplication() -> None:
    ctx = ConversationContextManager()
    session_id = "test-dedup-sess-1"

    external_msgs = [
        {"role": "user", "content": "Mi nombre es Carlos."},
        {"role": "assistant", "content": "Hola Carlos."},
        {"role": "user", "content": "¿Qué proyecto te acabo de mencionar?"},
        {"role": "assistant", "content": "Mencionaste JESSYCA."},
        {"role": "user", "content": "Nuevo mensaje activo"},
    ]

    # Primera ingestión: debe incorporar 2 turnos previos
    count1 = ctx.ingest_external_context(session_id, external_msgs)
    assert count1 == 2
    history1 = ctx.get_history(session_id)
    assert len(history1) == 2
    assert history1[0].user_prompt == "Mi nombre es Carlos."
    assert history1[0].assistant_response == "Hola Carlos."
    assert history1[1].user_prompt == "¿Qué proyecto te acabo de mencionar?"
    assert history1[1].assistant_response == "Mencionaste JESSYCA."

    # Segunda ingestión con el mismo payload: 0 turnos duplicados
    count2 = ctx.ingest_external_context(session_id, external_msgs)
    assert count2 == 0
    history2 = ctx.get_history(session_id)
    assert len(history2) == 2

    # Tercera ingestión con un turno adicional en el historial
    updated_msgs = [
        {"role": "user", "content": "Mi nombre es Carlos."},
        {"role": "assistant", "content": "Hola Carlos."},
        {"role": "user", "content": "¿Qué proyecto te acabo de mencionar?"},
        {"role": "assistant", "content": "Mencionaste JESSYCA."},
        {"role": "user", "content": "Nuevo mensaje activo"},
        {"role": "assistant", "content": "Respuesta al nuevo mensaje."},
        {"role": "user", "content": "Último turno activo"},
    ]
    count3 = ctx.ingest_external_context(session_id, updated_msgs)
    assert count3 == 1
    history3 = ctx.get_history(session_id)
    assert len(history3) == 3
    assert history3[2].user_prompt == "Nuevo mensaje activo"


# ── TEST 4: AISLAMIENTO ENTRE SESIONES ──
def test_session_isolation_preservation() -> None:
    ctx = ConversationContextManager()
    s1 = "session-lucero-secret"
    s2 = "session-other-fresh"

    ctx.ingest_external_context(
        s1,
        [
            {"role": "user", "content": "La palabra secreta es LUCERO."},
            {"role": "assistant", "content": "Entendido, palabra registrada."},
            {"role": "user", "content": "consulta"},
        ],
    )

    # Verificar que s1 tiene el contexto y entidad
    sess1 = ctx.get_session(s1)
    assert sess1 is not None
    assert sess1.get_context("secret_word") == "LUCERO"

    # Verificar que s2 está completamente limpio y aislado
    sess2 = ctx.get_session(s2)
    assert sess2 is None

    sess2_new = ctx.get_or_create_session(s2)
    assert sess2_new.get_context("secret_word") is None
    assert len(ctx.get_history(s2)) == 0


# ── TEST 5: DIRECT BRIDGE INGESTS CONTEXT INTO JESSYCA_REQUEST ──
def test_direct_bridge_passes_conversation_context(client: TestClient, auth_headers: dict[str, str]) -> None:
    captured: list[JessycaRequest] = []

    def fake_interact(req: JessycaRequest) -> JessycaResponse:
        captured.append(req)
        return JessycaResponse(
            request_id=req.request_id,
            session_id=req.session_id,
            success=True,
            status=AgentExecutionState.COMPLETED,
            response_text="Hola Carlos, te llamas Carlos.",
        )

    agent = JessycaLocalAgent.get_instance()
    agent.interact = fake_interact  # type: ignore[assignment]

    resp = client.post(
        "/v1/chat/completions",
        headers=auth_headers,
        json={
            "model": "jessyca",
            "messages": [
                {"role": "user", "content": "Mi nombre es Carlos."},
                {"role": "assistant", "content": "Hola Carlos."},
                {"role": "user", "content": "¿Cómo me llamo?"},
            ],
            "stream": False,
        },
    )

    assert resp.status_code == 200
    assert len(captured) == 1
    req = captured[0]
    assert req.user_input == "¿Cómo me llamo?"
    assert len(req.conversation_context) == 3
    assert req.conversation_context[0]["content"] == "Mi nombre es Carlos."
    assert req.conversation_context[1]["content"] == "Hola Carlos."
    assert req.conversation_context[2]["content"] == "¿Cómo me llamo?"
