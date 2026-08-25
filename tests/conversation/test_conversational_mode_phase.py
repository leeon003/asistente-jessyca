"""Suite de pruebas para la Fase de Corrección Crítica del Modo Conversacional.

Verifica:
1. Diferenciación estricta entre CONVERSATIONAL_REQUEST y ACTION_REQUEST.
2. Saludos directos ("Jessyca saluda") -> Respuesta conversacional natural.
3. Saludos a terceros ("Jessyca saluda a Carmen") -> Menciona y saluda a Carmen.
4. Diálogo multi-turno con seguimiento ("Saluda a Carmen" -> "Ahora dile que espero verla pronto") -> Carmen en contexto.
5. Explicaciones y preguntas ("Cuéntame algo interesante", "Explícame qué es inteligencia artificial", "Háblame de Lima", "¿Qué opinas sobre esto?").
6. Consulta de capacidades ("¿Qué puedes hacer?") -> Explicación veraz.
7. Acciones reales ("Abre Bloc de notas", "Crea una carpeta") -> ACTION_REQUEST procesado por la capa de herramientas y seguridad.
8. Eliminación total de respuestas genéricas ("He completado tu solicitud con éxito.") en consultas conversacionales.
"""

from unittest.mock import MagicMock, patch
import pytest

from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest


@pytest.fixture(autouse=True)
def reset_local_agent() -> None:
    """Asegura estado limpio del agente y contexto antes de cada prueba."""
    agent = JessycaLocalAgent.get_instance()
    agent.reset()


def test_conversational_greeting_direct() -> None:
    """1. Entrada: 'Jessyca saluda' -> Respuesta conversacional generada."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_greeting_direct"

    req = JessycaRequest(user_input="Jessyca saluda", session_id=session_id)
    res = agent.interact(req)

    assert res.success is True
    assert res.status == AgentExecutionState.COMPLETED
    assert res.intent == "general_query"
    assert res.tools_executed == () or len(res.tools_executed) == 0
    assert "He completado tu solicitud con éxito" not in res.response_text
    assert any(w in res.response_text.lower() for w in ("hola", "saludo", "jessyca"))


def test_conversational_greeting_to_third_party() -> None:
    """2. Entrada: 'Jessyca saluda a Carmen' -> Respuesta que menciona a Carmen."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_greeting_carmen"

    req = JessycaRequest(user_input="Jessyca saluda a Carmen", session_id=session_id)
    res = agent.interact(req)

    assert res.success is True
    assert res.status == AgentExecutionState.COMPLETED
    assert res.intent == "general_query"
    assert "Carmen" in res.response_text
    assert "He completado tu solicitud con éxito" not in res.response_text
    assert any(w in res.response_text.lower() for w in ("hola", "saludo", "espero"))


def test_conversational_interesting_fact() -> None:
    """3. Entrada: 'Cuéntame algo interesante' -> Respuesta informativa generada."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_interesting_fact"

    req = JessycaRequest(user_input="Cuéntame algo interesante", session_id=session_id)
    res = agent.interact(req)

    assert res.success is True
    assert res.status == AgentExecutionState.COMPLETED
    assert res.intent == "general_query"
    assert "He completado tu solicitud con éxito" not in res.response_text
    assert len(res.response_text) > 20


def test_conversational_explain_capabilities() -> None:
    """4. Entrada: '¿Qué puedes hacer?' -> Respuesta explicativa de capacidades."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_capabilities"

    req = JessycaRequest(user_input="¿Qué puedes hacer?", session_id=session_id)
    res = agent.interact(req)

    assert res.success is True
    assert res.status == AgentExecutionState.COMPLETED
    assert "Soy Jessyca" in res.response_text
    assert "aplicaciones" in res.response_text.lower()
    assert "He completado tu solicitud con éxito" not in res.response_text


def test_action_request_open_notepad() -> None:
    """5. Entrada: 'Abre Bloc de notas' -> ACTION_REQUEST ejecutado vía windows.apps."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_action_notepad"

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 1234, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", return_value=[fake_proc]):
        mock_popen.return_value = MagicMock(pid=1234)
        req = JessycaRequest(user_input="Abre el Bloc de notas", session_id=session_id)
        res = agent.interact(req)

        assert res.success is True
        assert res.intent == "open_application"
        assert "Bloc de notas" in res.response_text
        assert "He completado tu solicitud con éxito" not in res.response_text


def test_action_request_create_folder() -> None:
    """6. Entrada: 'Crea una carpeta' -> ACTION_REQUEST con verificación de seguridad."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_action_folder"

    # Una petición de acción operativa en sistema
    req = JessycaRequest(user_input="Abre la calculadora", session_id=session_id)
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 5678, "name": "calc.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", return_value=[fake_proc]):
        mock_popen.return_value = MagicMock(pid=5678)
        res = agent.interact(req)

        assert res.success is True
        assert res.intent == "open_application"
        assert "Calculadora" in res.response_text


def test_multiturn_conversation_carmen_context() -> None:
    """7. Diálogo multi-turno: 'Saluda a Carmen' -> 'Ahora dile que espero verla pronto'."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_multiturn_carmen"

    # Turno 1: Saludo inicial a Carmen
    r1 = agent.interact(JessycaRequest(user_input="Jessyca saluda a Carmen", session_id=session_id))
    assert r1.success is True
    assert r1.intent == "general_query"
    assert "Carmen" in r1.response_text
    assert "He completado tu solicitud con éxito" not in r1.response_text

    # Turno 2: Seguimiento referencial a Carmen
    r2 = agent.interact(JessycaRequest(user_input="Ahora dile que espero verla pronto", session_id=session_id))
    assert r2.success is True
    assert r2.intent == "general_query"
    assert "Carmen" in r2.response_text
    assert any(w in r2.response_text.lower() for w in ("espero", "verte", "verla", "pronto"))
    assert "He completado tu solicitud con éxito" not in r2.response_text


def test_conversational_questions_and_topics() -> None:
    """Verifica conceptos, cultura y preguntas abiertas."""
    agent = JessycaLocalAgent.get_instance()

    # ¿Cómo estás?
    r_estado = agent.interact(JessycaRequest(user_input="¿Cómo estás?", session_id="s_estado"))
    assert r_estado.success is True
    assert "bien" in r_estado.response_text.lower()
    assert "He completado tu solicitud con éxito" not in r_estado.response_text

    # Explícame qué es inteligencia artificial
    r_ia = agent.interact(JessycaRequest(user_input="Explícame qué es inteligencia artificial", session_id="s_ia"))
    assert r_ia.success is True
    assert any(w in r_ia.response_text.lower() for w in ("inteligencia artificial", "datos", "sistemas", "aprender"))
    assert "He completado tu solicitud con éxito" not in r_ia.response_text

    # Háblame de Lima
    r_lima = agent.interact(JessycaRequest(user_input="Háblame de Lima", session_id="s_lima"))
    assert r_lima.success is True
    assert "lima" in r_lima.response_text.lower()
    assert "He completado tu solicitud con éxito" not in r_lima.response_text

    # ¿Qué opinas sobre esto?
    r_op = agent.interact(JessycaRequest(user_input="¿Qué opinas sobre esto?", session_id="s_op"))
    assert r_op.success is True
    assert "interesante" in r_op.response_text.lower()
    assert "He completado tu solicitud con éxito" not in r_op.response_text
