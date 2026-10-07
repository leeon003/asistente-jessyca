"""Tests para la Fase 17.1.4: Respuestas técnicas precisas y eliminación del pitch automático.

Verifica rigurosamente:
1. Respuestas directas a preguntas técnicas sin autopresentaciones ni pitch promocional no solicitado.
2. Saludos naturales en español sin autopromoción repetitiva obligatoria.
3. Preservación íntegra de la explicación de capacidades cuando el usuario las consulta expresamente.
4. Distinción epistémica: reconocimiento honesto de datos desconocidos sin alucinación de archivos, saldos o métricas.
5. Reconocimiento claro y sobrio de limitaciones operativas sin publicidad sustitutiva.
6. Principio Anti-False Success: no afirmar éxito ni finalización de acciones antes de disponer de verificación observable.
7. Comportamiento del filtro de salida contra autopromociones y coletillas comerciales generadas por LLMs.
"""

from __future__ import annotations

import pytest

from core.execution.execution_verifier import ExecutionResult, ExecutionStatus
from core.local_agent.conversational_handler import (
    DEFAULT_SYSTEM_PROMPT,
    ConversationalDialogueHandler,
)
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    JessycaRequest,
)
from core.local_agent.response_synthesizer import ResponseSynthesizer
from core.system.system_coordinator import SystemResponse


@pytest.fixture
def agent() -> JessycaLocalAgent:
    return JessycaLocalAgent.get_instance()


@pytest.fixture
def handler() -> ConversationalDialogueHandler:
    return ConversationalDialogueHandler()


@pytest.fixture
def synthesizer() -> ResponseSynthesizer:
    return ResponseSynthesizer()


# ── 1. PREGUNTAS TÉCNICAS CONCRETAS: RESPONDER DIRECTO SIN PITCH ───────────────


def test_technical_question_primary_key_answers_directly_without_pitch(agent: JessycaLocalAgent) -> None:
    """Verifica que una pregunta técnica sobre clave primaria responde al concepto directamente."""
    req = JessycaRequest(user_input="¿Qué es una clave primaria en bases de datos?", session_id="test_tech_pk")
    res = agent.interact(req)

    assert res.success is True
    assert res.status == AgentExecutionState.COMPLETED
    text = res.response_text

    # Propiedad 1: Responde al concepto técnico concreto
    lower = text.lower()
    assert any(term in lower for term in ("columna", "identifica", "registro", "fila", "unívoca", "tabla"))

    # Propiedad 2: Cero autopresentación y cero pitch publicitario
    assert "soy jessyca" not in lower
    assert "tu asistente" not in lower
    assert "puedo abrir" not in lower
    assert "videos de baile" not in lower


def test_technical_question_pointer_answers_directly_without_pitch(agent: JessycaLocalAgent) -> None:
    """Verifica que una pregunta sobre punteros explica memoria sin autopresentaciones."""
    req = JessycaRequest(user_input="¿Qué es un puntero en programación?", session_id="test_tech_ptr")
    res = agent.interact(req)

    assert res.success is True
    text = res.response_text
    lower = text.lower()

    # Debe contener la explicación conceptual
    assert "memoria" in lower
    assert any(k in lower for k in ("variable", "dirección", "direccion", "almacena"))

    # No debe añadir autopresentación
    assert "soy jessyca" not in lower
    assert "puedo ayudarte a abrir" not in lower


def test_technical_question_process_vs_thread(agent: JessycaLocalAgent) -> None:
    """Verifica que la diferencia entre proceso e hilo se aborda de forma técnica y directa."""
    req = JessycaRequest(user_input="¿Cuál es la diferencia entre un proceso y un hilo?", session_id="test_tech_thread")
    res = agent.interact(req)

    assert res.success is True
    text = res.response_text
    lower = text.lower()

    assert "proceso" in lower
    assert "hilo" in lower
    assert "memoria" in lower
    assert "soy jessyca" not in lower
    assert "como tu asistente" not in lower


def test_technical_question_git_rebase(agent: JessycaLocalAgent) -> None:
    """Verifica explicación técnica de git rebase sin relleno publicitario."""
    req = JessycaRequest(user_input="¿Qué hace git rebase?", session_id="test_tech_rebase")
    res = agent.interact(req)

    assert res.success is True
    text = res.response_text
    lower = text.lower()

    assert "commits" in lower or "historial" in lower or "rama" in lower
    assert "soy jessyca" not in lower


# ── 2. SALUDOS NATURALES: SIN AUTOPROMOCIÓN REPETITIVA ────────────────────────


def test_greeting_hola_is_natural_without_promotional_pitch(agent: JessycaLocalAgent) -> None:
    """Verifica que un saludo simple 'Hola' no incluya el pitch repetitivo de capacidades."""
    req = JessycaRequest(user_input="Hola", session_id="test_greet_hola")
    res = agent.interact(req)

    assert res.success is True
    text = res.response_text
    lower = text.lower()

    # Saludo cordial y disponible
    assert "hola" in lower or "ayudar" in lower or "colabor" in lower
    # No debe inyectar la lista promocional de tareas
    assert "puedo abrir y cerrar aplicaciones" not in lower
    assert "reproducir vídeos" not in lower


def test_greeting_buenos_dias_is_natural(agent: JessycaLocalAgent) -> None:
    """Verifica que 'Buenos días' devuelva un saludo matutino natural sin pitch."""
    req = JessycaRequest(user_input="Buenos días", session_id="test_greet_dias")
    res = agent.interact(req)

    assert res.success is True
    lower = res.response_text.lower()

    assert "buenos días" in lower or "buenos dias" in lower or "hola" in lower
    assert "puedo abrir" not in lower
    assert "vídeos de baile" not in lower


# ── 3. EXPLICACIÓN DE CAPACIDADES CUANDO SE SOLICITAN EXPLÍCITAMENTE ───────────


def test_capability_query_explains_truthful_capabilities_when_asked(agent: JessycaLocalAgent) -> None:
    """Verifica que cuando el usuario pregunta explícitamente '¿Qué puedes hacer?', sí se describan."""
    req = JessycaRequest(user_input="¿Qué puedes hacer?", session_id="test_cap_explicit")
    res = agent.interact(req)

    assert res.success is True
    text = res.response_text
    lower = text.lower()

    # Al ser solicitada explícitamente, debe explicar sus capacidades
    assert "jessyca" in lower
    assert any(w in lower for w in ("aplicaciones", "archivos", "abrir", "tareas", "sistema"))


def test_identity_query_answers_identity_when_asked(agent: JessycaLocalAgent) -> None:
    """Verifica que cuando el usuario pregunta '¿Quién eres?', responda su identidad con sobriedad."""
    req = JessycaRequest(user_input="¿Quién eres?", session_id="test_identity")
    res = agent.interact(req)

    assert res.success is True
    lower = res.response_text.lower()

    assert "jessyca" in lower
    assert "asistente" in lower


# ── 4. DISTINCIÓN EPISTÉMICA: DATOS DESCONOCIDOS SIN ALUCINACIÓN ──────────────


def test_unknown_private_data_acknowledged_honestly(agent: JessycaLocalAgent) -> None:
    """Verifica que consultas sobre datos inexistentes/desconocidos no inventen datos ni archivos."""
    req = JessycaRequest(user_input="¿Cuál es el saldo de mi cuenta bancaria?", session_id="test_unknown_bank")
    res = agent.interact(req)

    assert res.success is True
    lower = res.response_text.lower()

    # Debe admitir honestamente que no dispone de ese dato
    assert any(term in lower for term in ("no dispongo", "desconozco", "no tengo acceso", "no existen registros", "no cuento"))
    # No debe alucinar cantidades monetarias ni entidades bancarias
    assert "$" not in res.response_text
    assert "dólares" not in lower
    assert "euros" not in lower


def test_unknown_emails_acknowledged_without_invention(agent: JessycaLocalAgent) -> None:
    """Verifica que no invente recuentos de correos sin conexión comprobada."""
    req = JessycaRequest(user_input="¿Cuántos correos tengo hoy en mi bandeja?", session_id="test_unknown_emails")
    res = agent.interact(req)

    assert res.success is True
    lower = res.response_text.lower()

    assert any(term in lower for term in ("no dispongo", "no tengo acceso", "registros", "información", "informacion"))


# ── 5. RECONOCIMIENTO DE LIMITACIONES SIN PUBLICIDAD SUSTITUTIVA ───────────────


def test_unsupported_action_stated_clearly_without_ad_replacement(agent: JessycaLocalAgent) -> None:
    """Verifica que acciones no soportadas se rechacen con claridad sin sustituirlas por publicidad."""
    req = JessycaRequest(user_input="Edita este video para TikTok y hazlo viral", session_id="test_unsupported_video")
    res = agent.interact(req)

    assert res.success is True
    lower = res.response_text.lower()

    # Declara la limitación con franqueza
    assert any(w in lower for w in ("no puedo", "no está soportada", "no esta soportada", "no dispongo"))
    # No intenta vender otras capacidades ni promocionar videos de baile
    assert "reproducir vídeos de baile" not in lower
    assert "¡pero mira todo lo que sí puedo hacer!" not in lower


# ── 6. PRINCIPIO ANTI-FALSE SUCCESS: NO AFIRMAR ÉXITO SIN VERIFICACIÓN ─────────


def test_unverified_execution_does_not_claim_success(synthesizer: ResponseSynthesizer) -> None:
    """Verifica que un resultado no verificado (UNKNOWN) declare la incertidumbre con honestidad."""
    fake_result = ExecutionResult(
        action="launch_app",
        target="notepad",
        status=ExecutionStatus.UNKNOWN,
        message="Process spawned but window not verified",
    )
    resp_text = synthesizer.format_response_text(
        intent="open_application",
        sys_resp=SystemResponse(task_id="test_t1", correlation_id="test_c1", success=True, status="COMPLETED", output={}),
        params={"app_name": "notepad"},
        execution_result=fake_result,
    )

    lower = resp_text.lower()
    # No debe cantar victoria prematuramente
    assert "listo, abrí" not in lower
    assert "éxito" not in lower
    # Debe reflejar que no se pudo confirmar
    assert any(term in lower for term in ("no pude confirmar", "no confirmó", "incertidumbre"))


def test_verified_execution_confirms_cleanly(synthesizer: ResponseSynthesizer) -> None:
    """Verifica que un resultado formalmente verificado confirme concisamente sin publicidad."""
    fake_result = ExecutionResult(
        action="launch_app",
        target="notepad",
        status=ExecutionStatus.SUCCEEDED,
        message="Window confirmed open",
    )
    resp_text = synthesizer.format_response_text(
        intent="open_application",
        sys_resp=SystemResponse(task_id="test_t1", correlation_id="test_c1", success=True, status="COMPLETED", output={}),
        params={"app_name": "notepad"},
        execution_result=fake_result,
    )

    assert "Listo, abrí el Bloc de notas." in resp_text
    # No agrega pitch adicional
    assert "recuerda que soy jessyca" not in resp_text.lower()


# ── 7. FILTRADO DE SALIDA CONTRA PITCH GENERADO POR LLM ───────────────────────


def test_output_filter_strips_leading_pitch_from_technical_answer(handler: ConversationalDialogueHandler) -> None:
    """Verifica que _filter_unsolicited_pitch remueva autopresentaciones iniciales de LLMs."""
    llm_output = (
        "¡Hola! Soy Jessyca, tu asistente local e inteligente para Windows. "
        "Un deadlock o interbloqueo es una condición donde dos o más hilos quedan "
        "bloqueados permanentemente esperando recursos mutuos."
    )
    user_query = "¿Qué es un deadlock en programación concurrente?"

    filtered = handler._filter_unsolicited_pitch(llm_output, user_query)

    assert not filtered.startswith("¡Hola! Soy Jessyca")
    assert not filtered.startswith("Soy Jessyca")
    assert filtered.startswith("Un deadlock o interbloqueo es una condición")


def test_output_filter_strips_trailing_promotional_tagline(handler: ConversationalDialogueHandler) -> None:
    """Verifica que _filter_unsolicited_pitch elimine coletillas promocionales al final."""
    llm_output = (
        "Git rebase traslada una serie de commits sobre una nueva base. "
        "Recuerda que puedo ayudarte a abrir aplicaciones o reproducir videos."
    )
    user_query = "¿Para qué sirve git rebase?"

    filtered = handler._filter_unsolicited_pitch(llm_output, user_query)

    assert "Git rebase traslada una serie de commits" in filtered
    assert "Recuerda que puedo ayudarte a abrir aplicaciones" not in filtered


def test_output_filter_preserves_presentation_when_user_asks_identity(handler: ConversationalDialogueHandler) -> None:
    """Verifica que la autopresentación NO se elimine cuando el usuario preguntó quién es."""
    full_resp = "Soy Jessyca, tu asistente local e inteligente para Windows."
    filtered = handler._filter_unsolicited_pitch(full_resp, "¿Quién eres?")

    assert filtered == full_resp


def test_default_system_prompt_contains_precision_and_no_pitch_rules() -> None:
    """Verifica que DEFAULT_SYSTEM_PROMPT contenga las directrices de precisión y cero pitch."""
    prompt = DEFAULT_SYSTEM_PROMPT.lower()

    assert "cero pitch automático" in prompt or "prohibido el pitch" in prompt
    assert "distinción epistémica" in prompt or "hechos comprobados" in prompt
    assert "veracidad técnica" in prompt or "no inventes" in prompt
    assert "no anticipar verificación" in prompt
    assert "limitaciones honestas" in prompt or "limitación" in prompt
