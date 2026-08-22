"""Suite de Pruebas de Certificación para Diálogo Natural y Comprensión Contextual (Fase 50).

Valida:
1. test_pronoun_reference: Resolución anafórica de pronombres ("Abre Chrome" -> "Busca YouTube" -> "Ábrelo").
2. test_contextual_followup: Seguimiento deíctico ("Abre el bloc de notas" -> "Cierra esa ventana").
3. test_ellipsis: Elipsis operacional ("Abre calculadora" -> "Ahora otra suma" -> "Hazla con 50 y 25").
4. test_user_correction: Corrección de objetivo ("Abre Chrome" -> "No, quería Edge").
5. test_cancel_task: Cancelación conversacional ("Haz una suma" -> "Olvídalo").
6. test_topic_switch: Cambio de tema sin arrastre ("Abre calculadora" -> "Oye, ¿qué puedes hacer?").
7. test_ambiguous_reference: Referencias ambiguas con clarificación explícita.
8. test_no_context_does_not_invent: Prohibición estricta de inventar objetivos sin contexto ("Ábrelo" en frío).
9. test_context_relevance_scoring: Ponderación, marca temporal y procedencia de ContextItem.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.local_agent import (
    AgentExecutionState,
    ConversationSession,
    JessycaLocalAgent,
    JessycaRequest,
)


@pytest.fixture(autouse=True)
def reset_local_agent():
    agent = JessycaLocalAgent.get_instance()
    agent.reset()
    yield
    agent.reset()


# ── 1. RESOLUCIÓN DE PRONOMBRES Y REFERENCIAS ──


def test_pronoun_reference():
    """Valida: 'Abre Chrome' -> 'Ahora busca YouTube' -> 'Ábrelo'."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "session_pronoun_test"

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 1111, "name": "msedge.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_proc]):
        # Turno 1: Abrir navegador
        r1 = agent.interact(JessycaRequest(user_input="Abre el navegador", session_id=session_id))
        assert r1.success is True
        assert r1.intent == "open_application"

        # Turno 2: Buscar YouTube
        r2 = agent.interact(JessycaRequest(user_input="Ahora busca YouTube", session_id=session_id))
        assert r2.success is True
        assert r2.intent == "browser_search"
        assert "youtube" in r2.response_text.lower()

        # Turno 3: "Ábrelo" (debe resolver hacia la entidad YouTube / búsqueda)
        r3 = agent.interact(JessycaRequest(user_input="Ábrelo", session_id=session_id))
        assert r3.success is True
        assert r3.intent in ("browser_search", "open_application")
        assert "youtube" in r3.response_text.lower()


# ── 2. SEGUIMIENTO CONTEXTUAL Y DEÍCTICOS ──


def test_contextual_followup():
    """Valida: 'Abre el bloc de notas' -> 'Cierra esa ventana'."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "session_followup_test"

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 2222, "name": "notepad.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_proc]):
        # Turno 1: Abrir bloc de notas
        r1 = agent.interact(JessycaRequest(user_input="Abre el bloc de notas", session_id=session_id))
        assert r1.success is True
        assert "Bloc de notas" in r1.response_text

    with patch("subprocess.Popen"), patch("psutil.process_iter", side_effect=[[fake_proc], []]):
        # Turno 2: "Cierra esa ventana" (debe resolver sobre notepad)
        r2 = agent.interact(JessycaRequest(user_input="Cierra esa ventana", session_id=session_id))
        assert r2.success is True
        assert r2.intent == "close_application"
        assert "Bloc de notas" in r2.response_text


# ── 3. ELIPSIS OPERACIONAL ──


def test_ellipsis():
    """Valida: 'Abre la calculadora' -> 'Ahora otra suma' -> 'Hazla con 50 y 25'."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "session_ellipsis_test"

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 3333, "name": "calc.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_proc]):
        # Turno 1: Abrir calculadora
        r1 = agent.interact(JessycaRequest(user_input="Abre la calculadora", session_id=session_id))
        assert r1.success is True

        # Turno 2: "Ahora otra suma"
        r2 = agent.interact(JessycaRequest(user_input="Ahora otra suma", session_id=session_id))
        assert r2.status == AgentExecutionState.AWAITING_CLARIFICATION
        assert "¿Qué números quieres sumar?" in r2.response_text

        # Turno 3: "Hazla con 50 y 25" (hereda contexto de suma)
        r3 = agent.interact(JessycaRequest(user_input="Hazla con 50 y 25", session_id=session_id))
        assert r3.success is True
        assert r3.intent == "math_calculation"
        assert "75" in r3.response_text


# ── 4. CORRECCIÓN DIRECTA DEL USUARIO ──


def test_user_correction():
    """Valida: 'Abre Chrome' -> 'No, quería Edge'."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "session_correction_test"

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 4444, "name": "msedge.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_proc]):
        # Turno 1: Abrir Chrome
        r1 = agent.interact(JessycaRequest(user_input="Abre Chrome", session_id=session_id))
        assert r1.success is True

        # Turno 2: Corrección del usuario
        r2 = agent.interact(JessycaRequest(user_input="No, quería Edge", session_id=session_id))
        assert r2.success is True
        assert r2.intent == "open_application"
        assert "Edge" in r2.response_text


# ── 5. CANCELACIÓN CONVERSACIONAL ──


def test_cancel_task():
    """Valida: 'Haz una suma' -> 'Olvídalo'."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "session_cancel_test"

    # Turno 1: Iniciar tarea
    r1 = agent.interact(JessycaRequest(user_input="Haz una suma", session_id=session_id))
    assert r1.requires_clarification is True

    # Turno 2: Cancelar
    r2 = agent.interact(JessycaRequest(user_input="Olvídalo", session_id=session_id))
    assert r2.success is True
    assert r2.intent == "cancel_task"
    assert "cancelada" in r2.response_text.lower()

    # Verificar que no quedan pendientes
    session = agent.context_manager.get_session(session_id)
    assert session is not None
    assert session.pending_intent is None


# ── 6. CAMBIO DE TEMA SIN ARRASTRE ESPURIO ──


def test_topic_switch():
    """Valida: 'Abre la calculadora' -> 'Oye, ¿qué puedes hacer?'."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "session_topic_switch_test"

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 5555, "name": "calc.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_proc]):
        # Turno 1: Calculadora
        r1 = agent.interact(JessycaRequest(user_input="Abre la calculadora", session_id=session_id))
        assert r1.success is True

        # Turno 2: Cambio de tema (consulta de capacidades)
        r2 = agent.interact(JessycaRequest(user_input="Oye, ¿qué puedes hacer?", session_id=session_id))
        assert r2.success is True
        assert r2.intent == "general_query"
        assert "Soy Jessyca" in r2.response_text


# ── 7. REFERENCIAS AMBIGUAS ──


def test_ambiguous_reference():
    """Valida que entradas ambiguas sin parámetros soliciten aclaración sin ejecutar."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "session_ambiguous_test"

    r = agent.interact(JessycaRequest(user_input="Abre", session_id=session_id))
    assert r.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert r.requires_clarification is True


# ── 8. NO INVENTAR CONTEXTO SIN ANTECEDENTES ──


def test_no_context_does_not_invent():
    """Valida que referencias anafóricas en frío ('Ábrelo', 'Ciérralo') pregunten al usuario en lugar de inventar."""
    agent = JessycaLocalAgent.get_instance()

    # Caso 1: "Ábrelo" en sesión limpia sin contexto previo
    r1 = agent.interact(JessycaRequest(user_input="Ábrelo", session_id="fresh_session_open"))
    assert r1.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert r1.requires_clarification is True
    assert "¿Qué quieres que abra?" in r1.response_text

    # Caso 2: "Ciérralo" en sesión limpia sin contexto previo
    r2 = agent.interact(JessycaRequest(user_input="Ciérralo", session_id="fresh_session_close"))
    assert r2.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert r2.requires_clarification is True
    assert "¿Qué ventana o aplicación deseas que cierre?" in r2.response_text


# ── 9. PONDERACIÓN DE RELEVANCIA CONTEXTUAL (CONTEXTITEM) ──


def test_context_relevance_scoring():
    """Valida la creación, filtrado por relevancia y vigencia temporal de ContextItem."""
    session = ConversationSession(conversation_id="relevance_test")

    # Registrar contexto con distintas relevancias
    session.set_context_item("current_application", "chrome", relevance=0.95, source="user_intent")
    session.set_context_item("secondary_tip", "usar atajos", relevance=0.3, source="system_hint")

    item = session.get_context_item("current_application")
    assert item is not None
    assert item.relevance == 0.95
    assert item.source == "user_intent"
    assert item.is_fresh(max_age_seconds=60.0)

    # Filtrar solo relevantes (min_relevance >= 0.5)
    relevant = session.get_relevant_context(min_relevance=0.5)
    assert "current_application" in relevant
    assert "secondary_tip" not in relevant
