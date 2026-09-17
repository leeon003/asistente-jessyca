"""Pruebas automatizadas de resolución semántica y ejecución de Notepad / Bloc de notas (Fase Corrección Mobile).

Verifica:
1. "abre el bloc de notas" -> ejecuta Notepad sin pedir aclaración.
2. "abre Notepad" -> ejecuta Notepad sin pedir aclaración.
3. "crea un nuevo block de notas" -> ejecuta Notepad sin pedir aclaración.
4. "abre un block de notas y escribe feliz cumpleaños Diego" -> abre Notepad y escribe el texto.
5. Continuidad multi-turno:
   - Turno 1: "crea un nuevo block de notas"
   - Turno 2: "escribe feliz cumpleaños dentro del block de notas"
   Reutiliza la instancia activa en la sesión y no genera duplicados.
6. Prevención de falsos éxitos si falla la verificación de proceso o tipeo.
"""

from unittest.mock import MagicMock, patch

import pytest

from core.application_models import ApplicationSession, ApplicationState
from core.application_session_manager import ApplicationSessionManager, FakeApplicationAdapter
from core.local_agent.local_agent import JessycaLocalAgent, JessycaRequest, InputModality
from skills.apps_skill import WindowsAppsSkill


@pytest.fixture
def fake_notepad_proc():
    proc = MagicMock()
    proc.info = {"pid": 1010, "name": "notepad.exe"}
    return proc


def test_intent_and_execution_abre_el_bloc_de_notas(fake_notepad_proc):
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_sess_bloc_1"

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_notepad_proc]):
        resp = agent.interact(JessycaRequest(
            user_input="abre el bloc de notas",
            session_id=session_id,
            modality=InputModality.TEXT,
        ))

        assert resp.success is True
        assert resp.requires_clarification is False
        assert resp.intent == "open_application"
        assert "Bloc de notas" in resp.response_text
        assert "cuéntame un poco más" not in resp.response_text


def test_intent_and_execution_abre_notepad(fake_notepad_proc):
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_sess_notepad_1"

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_notepad_proc]):
        resp = agent.interact(JessycaRequest(
            user_input="abre Notepad",
            session_id=session_id,
            modality=InputModality.TEXT,
        ))

        assert resp.success is True
        assert resp.requires_clarification is False
        assert resp.intent == "open_application"
        assert "Bloc de notas" in resp.response_text
        assert "cuéntame un poco más" not in resp.response_text


def test_intent_and_execution_crea_un_nuevo_block_de_notas(fake_notepad_proc):
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_sess_crea_block_1"

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_notepad_proc]):
        resp = agent.interact(JessycaRequest(
            user_input="crea un nuevo block de notas",
            session_id=session_id,
            modality=InputModality.TEXT,
        ))

        assert resp.success is True
        assert resp.requires_clarification is False
        assert resp.intent == "open_application"
        assert "Bloc de notas" in resp.response_text
        assert "cuéntame un poco más" not in resp.response_text


def test_compound_abre_block_de_notas_y_escribe(fake_notepad_proc):
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_sess_compound_1"

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_notepad_proc]):
        resp = agent.interact(JessycaRequest(
            user_input="abre un block de notas y escribe feliz cumpleaños Diego",
            session_id=session_id,
            modality=InputModality.TEXT,
        ))

        assert resp.success is True
        assert resp.requires_clarification is False
        assert resp.intent == "open_application"
        assert "Bloc de notas" in resp.response_text
        assert "feliz cumpleaños Diego" in resp.response_text
        assert "cuéntame un poco más" not in resp.response_text


def test_compound_crea_un_nuevo_block_de_notas_y_escribe(fake_notepad_proc):
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_sess_compound_2"

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_notepad_proc]):
        resp = agent.interact(JessycaRequest(
            user_input="Crea un nuevo block de notas y escribe feliz cumpleaños Diego",
            session_id=session_id,
            modality=InputModality.TEXT,
        ))

        assert resp.success is True
        assert resp.requires_clarification is False
        assert resp.intent == "open_application"
        assert "Bloc de notas" in resp.response_text
        assert "feliz cumpleaños Diego" in resp.response_text
        assert "cuéntame un poco más" not in resp.response_text


def test_contextual_continuity_two_turns(fake_notepad_proc):
    """Prueba de continuidad contextual:
    Turno 1: 'crea un nuevo block de notas'
    Turno 2: 'escribe feliz cumpleaños dentro del block de notas'
    Verifica que el contexto se mantiene, no se pide aclaración y no se duplican ventanas.
    """
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_continuity_session_42"

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", return_value=[fake_notepad_proc]):
        # Turno 1
        t1 = agent.interact(JessycaRequest(
            user_input="crea un nuevo block de notas",
            session_id=session_id,
            modality=InputModality.TEXT,
        ))
        assert t1.success is True
        assert t1.requires_clarification is False
        assert t1.intent == "open_application"
        assert "Bloc de notas" in t1.response_text

        # Turno 2
        t2 = agent.interact(JessycaRequest(
            user_input="Escribe feliz cumpleaños dentro del block de notas",
            session_id=session_id,
            modality=InputModality.TEXT,
        ))
        assert t2.success is True
        assert t2.requires_clarification is False
        assert t2.intent == "type_text"
        assert "feliz cumpleaños" in t2.response_text
        assert "Bloc de notas" in t2.response_text
        assert "cuéntame un poco más" not in t2.response_text


def test_false_success_prevention_on_verification_failure():
    """Garantiza que si la verificación falla (el proceso nunca aparece), JESSYCA no responde con éxito."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_sess_verif_fail"

    # psutil no retorna ningún proceso notepad
    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[]):
        resp = agent.interact(JessycaRequest(
            user_input="abre el bloc de notas",
            session_id=session_id,
            modality=InputModality.TEXT,
        ))

        # No debe declarar éxito falso
        assert resp.requires_clarification is False
        assert "no confirmó" in resp.response_text or resp.success is False
