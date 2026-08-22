"""Suite de Pruebas de Certificación para el Núcleo Conversacional (Fase 49 - Conversational Core Foundation).

Valida:
1. test_conversation_session_creation: Creación y ciclo de vida de ConversationSession.
2. test_conversation_turn: Inmutabilidad, roles y campos de ConversationTurn.
3. test_multi_turn_context: Resolución anafórica de contexto corto (Abre navegador -> Busca hoteles).
4. test_pending_question: Preguntas pendientes y slot-filling (Abre app -> Cuál -> Calculadora).
5. test_pending_parameter: Parámetros multi-turno (Haz una suma -> Qué números -> 125 y 378 -> 503).
6. test_context_expiration: Expiración determinista por inactividad temporal.
7. test_conversation_close: Cierre formal de sesión (adiós / salir / cerrar conversación).
8. test_context_cannot_authorize_action: Invariante CONTEXT != AUTHORIZATION.
9. test_multi_turn_calculator_sum_flow: Diálogo multi-turno completo.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from core.local_agent import (
    AgentExecutionState,
    ConversationContextManager,
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
    DialogueState,
    JessycaLocalAgent,
    JessycaRequest,
    TurnRole,
)


@pytest.fixture(autouse=True)
def reset_local_agent():
    agent = JessycaLocalAgent.get_instance()
    agent.reset()
    yield
    agent.reset()


# ── 1. CREACIÓN DE SESIÓN CONVERSACIONAL ──


def test_conversation_session_creation():
    """Valida la inicialización correcta de ConversationSession con sus campos obligatorios."""
    session = ConversationSession(conversation_id="session_test_01")

    assert session.conversation_id == "session_test_01"
    assert session.status == ConversationStatus.ACTIVE
    assert session.dialogue_state == DialogueState.NO_ACTIVE_TASK
    assert len(session.turns) == 0
    assert isinstance(session.active_context, dict)
    assert session.pending_intent is None
    assert session.pending_question is None
    assert not session.is_expired(timeout_seconds=300.0)


# ── 2. MODELO DE TURNO CONVERSACIONAL ──


def test_conversation_turn():
    """Valida los roles, campos inmutables y serialización de ConversationTurn."""
    turn = ConversationTurn(
        role=TurnRole.USER,
        raw_input="  Abre la calculadora  ",
        normalized_input="Abre la calculadora",
        user_prompt="Abre la calculadora",
        assistant_response="Listo, abrí la Calculadora.",
        intent="open_application",
        intent_confidence=0.98,
        tools_executed=("windows.launch_app",),
        security_verdict="ALLOW",
    )

    assert turn.role == TurnRole.USER
    assert turn.raw_input == "  Abre la calculadora  "
    assert turn.normalized_input == "Abre la calculadora"
    assert turn.intent == "open_application"
    assert turn.intent_confidence == 0.98
    assert "windows.launch_app" in turn.tools_executed
    assert turn.security_verdict == "ALLOW"

    d = turn.to_dict()
    assert d["role"] == "USER"
    assert d["intent"] == "open_application"


# ── 3. CONTEXTO CORTO Y RESOLUCIÓN ANAFÓRICA ──


def test_multi_turn_context():
    """Valida que una acción previa enriquezca el contexto del siguiente turno (Navegador -> Busca hoteles)."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "session_browser_context"

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 5555, "name": "msedge.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_proc]):
        # Turno 1: Abrir navegador
        req1 = JessycaRequest(user_input="Abre el navegador", session_id=session_id)
        res1 = agent.interact(req1)
        assert res1.success is True
        assert res1.intent == "open_application"

        # Verificar que el contexto corto registró la aplicación activa
        active_app = agent.context_manager.get_recent_entity(session_id, "current_application")
        assert active_app == "browser"

        # Turno 2: "Busca hoteles" en el contexto del navegador abierto
        req2 = JessycaRequest(user_input="Busca hoteles", session_id=session_id)
        res2 = agent.interact(req2)

        assert res2.success is True
        assert res2.intent == "browser_search"
        assert "hoteles" in res2.response_text.lower()


# ── 4. PREGUNTAS PENDIENTES Y SLOT FILLING ──


def test_pending_question():
    """Valida que una pregunta de aclaración pendiente sea completada en el siguiente turno."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "session_pending_app"

    # Turno 1: Orden incompleta / ambigua ("Abre una aplicación")
    req1 = JessycaRequest(user_input="Abre", session_id=session_id)
    res1 = agent.interact(req1)

    assert res1.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert res1.requires_clarification is True

    # Turno 2: Respuesta con el parámetro faltante ("Calculadora")
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 6666, "name": "calc.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_proc]):
        req2 = JessycaRequest(user_input="Calculadora", session_id=session_id)
        res2 = agent.interact(req2)

        assert res2.success is True
        assert res2.status == AgentExecutionState.COMPLETED
        assert res2.intent == "open_application"
        assert "Calculadora" in res2.response_text


# ── 5. PARÁMETROS MULTI-TURNO Y OPERACIONES MATEMÁTICAS ──


def test_pending_parameter():
    """Valida el flujo multi-turno de solicitud y suministro de parámetros (Haz una suma -> 125 y 378)."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "session_math"

    # Turno 1: Solicitar operación matemática sin números
    req1 = JessycaRequest(user_input="Haz una suma", session_id=session_id)
    res1 = agent.interact(req1)

    assert res1.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert res1.requires_clarification is True
    assert "¿Qué números quieres sumar?" in res1.response_text

    # Turno 2: Suministrar los números
    req2 = JessycaRequest(user_input="125 y 378", session_id=session_id)
    res2 = agent.interact(req2)

    assert res2.success is True
    assert res2.status == AgentExecutionState.COMPLETED
    assert res2.intent == "math_calculation"
    assert "503" in res2.response_text


# ── 6. EXPIRACIÓN TEMPORAL DE CONTEXTO ──


def test_context_expiration():
    """Valida que una sesión inactiva por más tiempo que el timeout sea declarada expirada."""
    manager = ConversationContextManager(conversation_timeout=0.05)
    session = manager.get_or_create_session("session_expiring")

    assert not session.is_expired(timeout_seconds=0.05)

    # Simular paso del tiempo
    time.sleep(0.08)
    assert session.is_expired(timeout_seconds=0.05)

    # get_session debe retornar None al expirar
    assert manager.get_session("session_expiring") is None


# ── 7. CIERRE FORMAL DE CONVERSACIÓN ──


def test_conversation_close():
    """Valida que comandos de despedida o cierre finalicen la sesión y limpien el contexto."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "session_closing"

    # Turno 1: Interacción
    req1 = JessycaRequest(user_input="Hola", session_id=session_id)
    res1 = agent.interact(req1)
    assert res1.success is True

    # Turno 2: Despedida ("Adiós")
    req2 = JessycaRequest(user_input="Adiós", session_id=session_id)
    res2 = agent.interact(req2)

    assert res2.success is True
    assert res2.intent == "close_conversation"
    assert "Hasta luego" in res2.response_text

    # Verificar que el contexto activo fue limpiado
    session = agent.context_manager.get_session(session_id)
    # Sesión cerrada no debe mantener contexto activo
    assert session is None or session.status == ConversationStatus.CLOSED


# ── 8. INVARIANTE: CONTEXT != AUTHORIZATION ──


def test_context_cannot_authorize_action():
    """Valida que el contexto conversacional no pueda almacenar flags de autorización ni eludir seguridad."""
    session = ConversationSession(conversation_id="session_security_test")

    # Intentar inyectar permisos en el contexto
    session.update_context("authorization", True)
    session.update_context("allow_all", True)
    session.update_context("security_override", "ADMIN")
    session.update_context("is_authorized", True)

    assert "authorization" not in session.active_context
    assert "allow_all" not in session.active_context
    assert "security_override" not in session.active_context
    assert "is_authorized" not in session.active_context

    # Claves legítimas sí se guardan
    session.update_context("last_app", "notepad")
    assert session.get_context("last_app") == "notepad"


# ── 9. DIÁLOGO MULTI-TURNO COMPLETO ──


def test_multi_turn_calculator_sum_flow():
    """Valida la secuencia completa del ejemplo canónico de la Fase 49:
    1. Usuario: Abre la calculadora. -> JESSYCA: Listo...
    2. Usuario: Haz una suma. -> JESSYCA: Claro. ¿Qué números quieres sumar?
    3. Usuario: 125 y 378. -> JESSYCA: El resultado es 503.
    4. Usuario: Adiós. -> JESSYCA: ¡Hasta luego!
    """
    agent = JessycaLocalAgent.get_instance()
    session_id = "canonical_multi_turn_session"

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 7777, "name": "calc.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_proc]):
        # Paso 1: Abre la calculadora
        r1 = agent.interact(JessycaRequest(user_input="Abre la calculadora", session_id=session_id))
        assert r1.success is True
        assert "Calculadora" in r1.response_text

        # Paso 2: Haz una suma
        r2 = agent.interact(JessycaRequest(user_input="Haz una suma", session_id=session_id))
        assert "¿Qué números quieres sumar?" in r2.response_text

        # Paso 3: 125 y 378
        r3 = agent.interact(JessycaRequest(user_input="125 y 378", session_id=session_id))
        assert r3.success is True
        assert "503" in r3.response_text

        # Paso 4: Adiós
        r4 = agent.interact(JessycaRequest(user_input="Adiós", session_id=session_id))
        assert r4.success is True
        assert "Hasta luego" in r4.response_text
