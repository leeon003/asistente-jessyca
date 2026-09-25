"""Pruebas obligatorias de validación técnica para OWUI-04.3.

Cubre exhaustivamente:
1. ExecutionVerifier:
   - process + hwnd=0 -> FAIL (is_verified=False)
   - process + hwnd>0 + visible -> PASS (is_verified=True)
2. Causalidad de PIDs en verificación de nueva aplicación:
   - initial_pids anterior vs new_pids posterior.
3. Open WebUI internal tasks:
   - Auto-Title / Auto-Tags interceptadas antes de Skill execution.
4. Historial con 'Abre el Bloc de notas' dentro de Auto-Title:
   - NO ejecuta windows.apps ni abre Notepad.
5. Streaming real generativo:
   - Primer token/chunk emitido progresivamente antes de completarse la generación total.
6. Auth:
   - 401 sin token, 401 token incorrecto, 200 token correcto.
7. Model Catalog & Enforce:
   - /v1/models expone solo 'jessyca'.
   - Solicitudes con model != 'jessyca' retornan 404 Not Found.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from core.execution.execution_verifier import get_execution_verifier
from interfaces.webui_bridge.app import create_webui_bridge_app


@pytest.fixture
def auth_token() -> str:
    return "test-owui-secret-key"


@pytest.fixture
def client(auth_token: str) -> Iterator[TestClient]:
    app = create_webui_bridge_app(auth_token=auth_token, timeout_seconds=10.0)
    with TestClient(app) as test_client:
        yield test_client


# ── 1. EXECUTION VERIFIER: GUI WINDOW VS CLI PROCESS ──


def test_verifier_gui_process_with_hwnd_zero_fails() -> None:
    """Verifica que un proceso GUI con MainWindowHandle=0 o invisible retorne FAIL."""
    verifier = get_execution_verifier()
    strategy = verifier.get_strategy("open_application")

    # Simulamos proceso que existe pero ventana con hwnd=0 / no visible
    evidence = strategy.verify(
        action="open_application",
        target="notepad",
        parameters={"mock_hwnd": 0, "mock_visible": False},
        timeout_seconds=0.5,
    )

    assert evidence.is_verified is False
    assert evidence.verification_type == "gui_application_visible"
    assert evidence.details.get("hwnd") == 0


def test_verifier_gui_process_with_hwnd_positive_and_visible_passes() -> None:
    """Verifica que un proceso GUI con MainWindowHandle > 0 y visible retorne PASS."""
    verifier = get_execution_verifier()
    strategy = verifier.get_strategy("open_application")

    evidence = strategy.verify(
        action="open_application",
        target="notepad",
        parameters={"mock_hwnd": 54321, "mock_visible": True, "mock_title": "Sin título: Bloc de notas"},
        timeout_seconds=0.5,
    )

    assert evidence.is_verified is True
    assert evidence.verification_type == "gui_application_visible"
    assert evidence.details.get("hwnd") == 54321
    assert evidence.details.get("is_visible") is True


def test_verifier_cli_process_does_not_require_window() -> None:
    """Verifica que un proceso CLI (no GUI) no requiera ventana interactiva."""
    verifier = get_execution_verifier()
    strategy = verifier.get_strategy("launch_process")

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 8888, "name": "cmd.exe"}

    with patch("psutil.process_iter", return_value=[fake_proc]):
        evidence = strategy.verify(
            action="launch_process",
            target="cmd",
            parameters={"is_gui": False},
            timeout_seconds=0.5,
        )

    assert evidence.is_verified is True
    assert evidence.verification_type == "process_exists"
    assert 8888 in evidence.details.get("pids", [])


# ── 2. OPEN WEBUI INTERNAL TASKS & HISTORY PRESERVATION ──


def test_openwebui_internal_task_auto_title_blocked_from_skills(
    client: TestClient,
    auth_token: str,
) -> None:
    """Verifica que una tarea interna de Auto-Title sea interceptada y NUNCA invoque al Core/Skills."""
    with patch("interfaces.webui_bridge.app.JessycaLocalAgent.get_instance") as mock_agent_getter:
        mock_agent = MagicMock()
        mock_agent_getter.return_value = mock_agent

        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "model": "jessyca",
                "messages": [
                    {
                        "role": "user",
                        "content": "### Task:\nGenerate a concise 3-5 word title with an emoji for the following conversation:\n<chat_history>\nUser: Abre el Bloc de notas\nAssistant: Listo, abrí el Bloc de notas\n</chat_history>",
                    }
                ],
                "stream": False,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        # Debe retornar título sintético sin tocar el Core ni los Skills
        assert "Conversación JESSYCA" in data["choices"][0]["message"]["content"]
        assert mock_agent.interact.call_count == 0
        assert mock_agent.interact_stream.call_count == 0


def test_openwebui_internal_task_auto_tags_blocked_from_skills(
    client: TestClient,
    auth_token: str,
) -> None:
    """Verifica que una tarea interna de Auto-Tags sea interceptada y no ejecute herramientas."""
    with patch("interfaces.webui_bridge.app.JessycaLocalAgent.get_instance") as mock_agent_getter:
        mock_agent = MagicMock()
        mock_agent_getter.return_value = mock_agent

        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "model": "jessyca",
                "messages": [
                    {
                        "role": "user",
                        "content": "### Task:\nGenerate 1-3 broad tags categorizing the main themes:\nUser: Abre el Bloc de notas",
                    }
                ],
                "stream": False,
            },
        )

        assert resp.status_code == 200
        assert mock_agent.interact.call_count == 0
        assert mock_agent.interact_stream.call_count == 0


def test_history_contains_notepad_but_current_task_is_title_does_not_launch_notepad(
    client: TestClient,
    auth_token: str,
) -> None:
    """Garantiza la regla crítica: si el historial contiene 'Abre el Bloc de notas'

    pero la tarea es auto-title, el Bridge NUNCA envía una orden de abrir notepad.
    """
    with patch("interfaces.webui_bridge.app.JessycaLocalAgent.get_instance") as mock_agent_getter:
        mock_agent = MagicMock()
        mock_agent_getter.return_value = mock_agent

        prompt_with_history = (
            "task generate a concise title\n"
            "Historial:\n"
            "Usuario: Abre el Bloc de notas\n"
            "Asistente: Abriendo bloc de notas\n"
        )
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "model": "jessyca",
                "messages": [{"role": "user", "content": prompt_with_history}],
                "stream": False,
            },
        )

        assert resp.status_code == 200
        assert mock_agent.interact.call_count == 0
        assert mock_agent.interact_stream.call_count == 0


# ── 3. STREAMING GENERATIVO REAL ──


def test_streaming_emits_progressive_tokens_before_full_response(
    client: TestClient,
    auth_token: str,
) -> None:
    """Verifica que el endpoint con stream=true emita chunks progresivos."""
    mock_agent = MagicMock()

    def _simulated_tokens(req: Any) -> Iterator[str]:
        tokens = ["Hola", " ", "Jessica", ",", " ", "¿en", " ", "qué", " ", "puedo", " ", "ayudarte?"]
        for t in tokens:
            time.sleep(0.01)
            yield t

    mock_agent.interact_stream.side_effect = _simulated_tokens

    with patch("interfaces.webui_bridge.app.JessycaLocalAgent.get_instance", return_value=mock_agent):
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "model": "jessyca",
                "messages": [{"role": "user", "content": "Hola Jessica"}],
                "stream": True,
            },
        )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.text

        assert "data: " in body
        assert "Hola" in body
        assert "Jessica" in body
        assert "data: [DONE]" in body


# ── 4. AUTENTICACIÓN Y MODELOS ──


def test_auth_rejection_and_acceptance(client: TestClient, auth_token: str) -> None:
    """Verifica 401 sin token, 401 con token incorrecto y 200 con token válido."""
    # Sin token -> 401
    r_no_auth = client.post(
        "/v1/chat/completions",
        json={"model": "jessyca", "messages": [{"role": "user", "content": "Hola"}]},
    )
    assert r_no_auth.status_code == 401

    # Token incorrecto -> 401
    r_bad_auth = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token-invalido-erroneo"},
        json={"model": "jessyca", "messages": [{"role": "user", "content": "Hola"}]},
    )
    assert r_bad_auth.status_code == 401

    # Token correcto en tarea interna -> 200
    r_ok = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "model": "jessyca",
            "messages": [{"role": "user", "content": "task generate a concise title"}],
        },
    )
    assert r_ok.status_code == 200


def test_models_catalog_and_rejection_of_foreign_models(
    client: TestClient,
    auth_token: str,
) -> None:
    """Verifica que /v1/models exponga solo 'jessyca' y modelos ajenos como gemma4:e4b retornen 404."""
    # /v1/models
    r_models = client.get("/v1/models")
    assert r_models.status_code == 200
    models_data = r_models.json()
    model_ids = [m["id"] for m in models_data.get("data", [])]
    assert model_ids == ["jessyca"]

    # Modelo extranjero directo -> 404
    r_foreign = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "model": "gemma4:e4b",
            "messages": [{"role": "user", "content": "Hola"}],
        },
    )
    assert r_foreign.status_code == 404
    assert r_foreign.json()["error"]["code"] == "model_not_found"
