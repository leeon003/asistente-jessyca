"""Pruebas de Contrato y Regresión para Fase 10 - Consolidación Gradual sin Romper Compatibilidad.

Verifica:
1. Aislamiento estricto de intenciones pendientes por session_id en core/orquestador.py:
   - Dos sesiones concurrentes con intenciones de aclaración distintas.
   - La cancelación en Sesión A no afecta a Sesión B.
   - La confirmación/resolución en Sesión B no autoriza la acción de Sesión A.
   - Expiración TTL independiente por sesión.
   - Ausencia de doble ejecución.
2. Resolución canónica de Tool Registry:
   - tools.tool_registry, tools.registry y tools reexportan la misma clase e instancia singleton.
   - tools/registry/ (paquete de Windows Registry) conserva sus exports de backend y servicios.
   - Autodescubrimiento dinámico no genera duplicados ni reconoce archivos de infraestructura como herramientas.
3. Sintetizador de Respuestas (ResponseSynthesizer):
   - Formateo verídico sin falsos éxitos.
   - Normalización de spoken_text para TTS.
   - Delegación transparente desde JessycaLocalAgent.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.intent_models import IntentStatus, ParsedIntent, PendingIntent
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    JessycaRequest,
    LocalAgentMetrics,
)
from core.local_agent.response_synthesizer import (
    ResponseSynthesizer,
    get_response_synthesizer,
)
from core.orquestador import (
    DEFAULT_SESSION_ID,
    clear_all_pending_intents,
    clear_pending_intent,
    ejecutar_orden_texto,
    get_pending_intent,
    set_pending_intent,
)
from core.system.system_coordinator import SystemResponse
from skills.base_skill import BaseSkill


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES Y CLASES DE PRUEBA
# ─────────────────────────────────────────────────────────────────────────────


class SpySkill(BaseSkill):
    """Skill espía que registra ejecuciones para verificar ausencia de doble ejecución."""

    def __init__(self, nombre: str, nivel_riesgo: int = 1) -> None:
        super().__init__(nombre=nombre, nivel_riesgo=nivel_riesgo)
        self.invocaciones: list[dict[str, Any]] = []

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        self.invocaciones.append(parametros)
        return {
            "exito": True,
            "mensaje": f"{self.nombre} ejecutado con éxito.",
            "parametros": parametros,
        }


@pytest.fixture(autouse=True)
def cleanup_orchestrator_sessions() -> None:
    """Limpia las sesiones del orquestador antes y después de cada test."""
    clear_all_pending_intents()
    yield
    clear_all_pending_intents()


# ─────────────────────────────────────────────────────────────────────────────
# 1. PRUEBAS DE SESIÓN Y AISLAMIENTO EN CORE/ORQUESTADOR.PY
# ─────────────────────────────────────────────────────────────────────────────


def test_orquestador_multi_session_isolation() -> None:
    """Verifica que dos sesiones mantengan estados de aclaración independientes."""
    session_a = "sesion_usuario_1"
    session_b = "sesion_usuario_2"

    intent_a = PendingIntent(
        skill_nombre="abrir_aplicacion",
        parametros_parciales={},
        parametro_esperado="nombre_app",
        candidatos_posibles=[],
        pregunta_formulada="¿Qué aplicación abro?",
        timestamp=time.time(),
        intentos=0,
        estado_origen=IntentStatus.INCOMPLETE,
    )
    intent_b = PendingIntent(
        skill_nombre="cerrar_aplicacion",
        parametros_parciales={},
        parametro_esperado="nombre_app",
        candidatos_posibles=[],
        pregunta_formulada="¿Qué aplicación cierro?",
        timestamp=time.time(),
        intentos=0,
        estado_origen=IntentStatus.INCOMPLETE,
    )

    set_pending_intent(intent_a, session_id=session_a)
    set_pending_intent(intent_b, session_id=session_b)

    # Cada sesión debe recuperar su propio PendingIntent
    rec_a = get_pending_intent(session_id=session_a)
    rec_b = get_pending_intent(session_id=session_b)

    assert rec_a is not None
    assert rec_a.skill_nombre == "abrir_aplicacion"
    assert rec_b is not None
    assert rec_b.skill_nombre == "cerrar_aplicacion"

    # Cancelar sesión A no afecta a sesión B
    clear_pending_intent(session_id=session_a)
    assert get_pending_intent(session_id=session_a) is None
    assert get_pending_intent(session_id=session_b) is not None
    assert get_pending_intent(session_id=session_b).skill_nombre == "cerrar_aplicacion"


@patch("core.orquestador.procesar_orden")
def test_two_sessions_distinct_confirmations_and_no_cross_authorization(
    mock_brain: MagicMock,
) -> None:
    """Verifica que resolver una aclaración en Sesión B no active ni autorice la acción de Sesión A."""
    skill_open = SpySkill("abrir_aplicacion")
    skill_close = SpySkill("cerrar_aplicacion")
    skills = {"abrir_aplicacion": skill_open, "cerrar_aplicacion": skill_close}

    session_a = "session_user_alice"
    session_b = "session_user_bob"

    # Turno 1 para Alice: Incompleto para abrir_aplicacion
    mock_brain.return_value = ParsedIntent(
        estado=IntentStatus.INCOMPLETE,
        respuesta_hablada="¿Qué app abro?",
        skill="abrir_aplicacion",
        parametros={},
        pregunta_aclaratoria="¿Qué aplicación abro?",
        parametro_faltante="nombre_app",
    )
    resp_a1 = ejecutar_orden_texto("abre", skills, session_id=session_a)
    assert resp_a1 == "¿Qué aplicación abro?"
    assert get_pending_intent(session_id=session_a) is not None
    assert get_pending_intent(session_id=session_b) is None

    # Turno 1 para Bob: Incompleto para cerrar_aplicacion
    mock_brain.return_value = ParsedIntent(
        estado=IntentStatus.INCOMPLETE,
        respuesta_hablada="¿Qué app cierro?",
        skill="cerrar_aplicacion",
        parametros={},
        pregunta_aclaratoria="¿Qué aplicación deseas cerrar?",
        parametro_faltante="nombre_app",
    )
    resp_b1 = ejecutar_orden_texto("cierra", skills, session_id=session_b)
    assert resp_b1 == "¿Qué aplicación deseas cerrar?"
    assert get_pending_intent(session_id=session_b) is not None

    # Bob cancela explícitamente: solo se cancela Bob
    resp_b_cancel = ejecutar_orden_texto("cancelar", skills, session_id=session_b)
    assert resp_b_cancel == "De acuerdo, cancelé la acción."
    assert get_pending_intent(session_id=session_b) is None
    # Alice sigue teniendo su intención pendiente intacta
    assert get_pending_intent(session_id=session_a) is not None
    assert get_pending_intent(session_id=session_a).skill_nombre == "abrir_aplicacion"

    # Alice aclara su intención y se ejecuta únicamente la de Alice
    mock_brain.return_value = ParsedIntent(
        estado=IntentStatus.CLEAR,
        respuesta_hablada="Abriendo el bloc de notas.",
        skill="abrir_aplicacion",
        parametros={"nombre_app": "notepad"},
    )
    resp_a2 = ejecutar_orden_texto("notepad", skills, session_id=session_a)
    assert "Abriendo" in resp_a2
    assert len(skill_open.invocaciones) == 1
    assert len(skill_close.invocaciones) == 0
    assert get_pending_intent(session_id=session_a) is None


@patch("core.orquestador.procesar_orden")
def test_absence_of_double_execution_on_clarification(mock_brain: MagicMock) -> None:
    """Verifica que una orden aclarada se ejecute estrictamente una sola vez."""
    skill = SpySkill("abrir_aplicacion")
    skills = {"abrir_aplicacion": skill}

    session_id = "test_idempotency_session"

    # Turno 1: Incompleto
    mock_brain.return_value = ParsedIntent(
        estado=IntentStatus.INCOMPLETE,
        respuesta_hablada="¿Qué aplicación?",
        skill="abrir_aplicacion",
        parametros={},
        pregunta_aclaratoria="¿Qué aplicación?",
        parametro_faltante="nombre_app",
    )
    ejecutar_orden_texto("abre", skills, session_id=session_id)
    assert len(skill.invocaciones) == 0

    # Turno 2: Resuelto
    mock_brain.return_value = ParsedIntent(
        estado=IntentStatus.CLEAR,
        respuesta_hablada="Abriendo calculadora.",
        skill="abrir_aplicacion",
        parametros={"nombre_app": "calc"},
    )
    ejecutar_orden_texto("calculadora", skills, session_id=session_id)
    assert len(skill.invocaciones) == 1

    # Turno 3: Envío posterior sin intención no debe re-ejecutar la anterior
    mock_brain.return_value = ParsedIntent(
        estado=IntentStatus.CLEAR,
        respuesta_hablada="Hola, ¿en qué te ayudo?",
        skill="",
        parametros={},
    )
    ejecutar_orden_texto("hola", skills, session_id=session_id)
    assert len(skill.invocaciones) == 1  # No hubo doble ejecución


def test_orquestador_ttl_expiration_independent_per_session() -> None:
    """Verifica que el TTL expire de forma independiente por sesión."""
    session_old = "sesion_expirada"
    session_fresh = "sesion_activa"

    # Intent con timestamp en el pasado (> 60 segundos)
    expired_intent = PendingIntent(
        skill_nombre="abrir_aplicacion",
        parametros_parciales={},
        parametro_esperado="nombre_app",
        candidatos_posibles=[],
        pregunta_formulada="¿Qué app?",
        timestamp=time.time() - 120.0,
        intentos=0,
        estado_origen=IntentStatus.INCOMPLETE,
    )
    # Intent recién creado
    fresh_intent = PendingIntent(
        skill_nombre="abrir_aplicacion",
        parametros_parciales={},
        parametro_esperado="nombre_app",
        candidatos_posibles=[],
        pregunta_formulada="¿Qué app?",
        timestamp=time.time(),
        intentos=0,
        estado_origen=IntentStatus.INCOMPLETE,
    )

    set_pending_intent(expired_intent, session_id=session_old)
    set_pending_intent(fresh_intent, session_id=session_fresh)

    # get_pending_intent descarta la expirada pero mantiene la activa
    assert get_pending_intent(session_id=session_old) is None
    assert get_pending_intent(session_id=session_fresh) is not None


# ─────────────────────────────────────────────────────────────────────────────
# 2. PRUEBAS DE RESOLUCIÓN DE AMBIGÜEDAD EN REGISTROS DE HERRAMIENTAS
# ─────────────────────────────────────────────────────────────────────────────


def test_tool_registry_canonical_resolution() -> None:
    """Verifica que las distintas rutas de importación resuelvan a la misma entidad canónica."""
    import tools
    import tools.registry as shim_registry
    import tools.tool_registry as canonical_registry

    # 1. Las clases son idénticas
    assert tools.ToolRegistry is canonical_registry.ToolRegistry
    assert shim_registry.ToolRegistry is canonical_registry.ToolRegistry

    # 2. La función de acceso singleton es idéntica
    assert tools.get_tool_registry is canonical_registry.get_tool_registry
    assert shim_registry.get_tool_registry is canonical_registry.get_tool_registry

    # 3. La instancia singleton obtenida por las tres vías es exactamente la misma
    instance_canonical = canonical_registry.get_tool_registry()
    instance_shim = shim_registry.get_tool_registry()
    instance_pkg = tools.get_tool_registry()

    assert instance_canonical is instance_shim
    assert instance_canonical is instance_pkg


def test_windows_registry_package_coexistence() -> None:
    """Verifica que el paquete tools/registry/ (Registro de Windows) coexista pacíficamente."""
    from tools.registry.backend import WindowsWinregBackend
    from tools.registry.registry_service import RegistryService

    service = RegistryService(backend=WindowsWinregBackend())
    assert service is not None
    assert hasattr(service, "get_key_info")
    assert hasattr(service, "list_values")


def test_dynamic_discovery_excludes_infrastructure_files() -> None:
    """Verifica que el descubrimiento dinámico excluya archivos shim e infraestructura."""
    from tools.tool_registry import ToolRegistry

    reg = ToolRegistry()
    discovered_count = reg.discover()
    # No debe dar error ni registrar registry.py o tool_registry.py como herramientas
    tool_names = [t.name for t in reg.list_tools()]
    assert "registry" not in tool_names
    assert "tool_registry" not in tool_names
    assert "discovery" not in tool_names


# ─────────────────────────────────────────────────────────────────────────────
# 3. PRUEBAS DE CONTRATO DEL SINTETIZADOR DE RESPUESTAS (ResponseSynthesizer)
# ─────────────────────────────────────────────────────────────────────────────


def test_response_synthesizer_speech_normalization() -> None:
    """Verifica que synthesize_spoken_text limpie markdown y artefactos para TTS."""
    synth = get_response_synthesizer()

    # Markdown con enlaces, negritas, código
    raw_markdown = "Aquí tienes el archivo [documento.txt](file:///d:/doc.txt) con **éxito** y `codigo`."
    spoken = synth.synthesize_spoken_text(raw_markdown)

    assert "documento.txt" in spoken
    assert "file:///" not in spoken
    assert "**" not in spoken
    assert "`" not in spoken
    assert "con éxito y codigo." in spoken


def test_response_synthesizer_unverified_prevention() -> None:
    """Verifica que una acción con verificación fallida no produzca una respuesta falsamente afirmativa."""
    from unittest.mock import Mock
    from core.execution.execution_verifier import ExecutionResult, ExecutionStatus

    synth = ResponseSynthesizer()

    unverified_result = ExecutionResult(
        status=ExecutionStatus.VERIFICATION_FAILED,
        action="open",
        target="notepad",
        message="Ventana no encontrada.",
    )

    sys_resp = Mock(spec=SystemResponse, success=False, output={}, error="Verification failed")

    text = synth.format_response_text(
        intent="open_application",
        sys_resp=sys_resp,
        params={"app_name": "notepad"},
        execution_result=unverified_result,
    )

    assert "Listo" not in text
    assert "no confirmó" in text or "no pude confirmar" in text or "no pudo ser verificada" in text


def test_response_synthesizer_success_formatting() -> None:
    """Verifica el formateo correcto ante éxito verificado."""
    from unittest.mock import Mock
    from core.execution.execution_verifier import ExecutionResult, ExecutionStatus

    synth = ResponseSynthesizer()

    success_result = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        action="open",
        target="notepad",
        message="Ventana confirmada.",
    )

    sys_resp = Mock(spec=SystemResponse, success=True, output={}, error=None)

    text = synth.format_response_text(
        intent="open_application",
        sys_resp=sys_resp,
        params={"app_name": "notepad"},
        execution_result=success_result,
    )

    assert "Listo, abrí el Bloc de notas." == text


def test_response_synthesizer_build_response_factory() -> None:
    """Verifica el contrato de fábrica canónica build_response."""
    synth = ResponseSynthesizer()
    req = JessycaRequest(user_input="hola", session_id="session_test")
    metrics = LocalAgentMetrics(task_id=req.request_id)
    t0 = time.perf_counter()

    resp = synth.build_response(
        request_id=req.request_id,
        session_id=req.session_id,
        success=True,
        status=AgentExecutionState.COMPLETED,
        response_text="Hola, ¿en qué puedo ayudarte hoy?",
        metrics=metrics,
        start_time=t0,
    )

    assert resp.request_id == req.request_id
    assert resp.session_id == req.session_id
    assert resp.success is True
    assert resp.status == AgentExecutionState.COMPLETED
    assert resp.spoken_text == "Hola, ¿en qué puedo ayudarte hoy?"
    assert resp.metrics.total_latency_ms >= 0.0
