"""Pruebas de Integración y Seguridad para Conversational Intent Continuity (Fase 64.3.2).

Valida exhaustivamente la interpretación de órdenes de seguimiento dependientes
del contexto conversacional inmediato:
A. "Abre notepad" -> "ciérralo" -> Debe resolver notepad.
B. "Abre Chrome" -> "ciérralo" -> Debe resolver Chrome.
C. Dos aplicaciones -> pronombre ambiguo -> Debe pedir aclaración (CLARIFY).
D. Contexto expirado -> Debe pedir aclaración (CLARIFY).
E. Nueva acción reemplaza contexto anterior (notepad -> chrome -> ciérralo resuelve chrome).
F. Acción pendiente de confirmación tiene prioridad sobre contexto anterior.
G. "Sí" confirma acción pendiente (no reinterpreta como nueva acción).
H. "No" cancela acción pendiente.
I. Última acción fallida no debe convertirse en falso contexto exitoso.
J. action_id correcto.
K. target correcto.
L. skill correcto.
M. operation correcta.
N. No ejecutar durante resolución de contexto.
O. Resolver referencia no debe llamar directamente al Dispatcher.
P. Regresión completa y compatibilidad de confirmaciones y diálogo.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from core.confirmation import ConfirmationManager
from core.dialogue.action_planner import ActionPlanner
from core.dialogue.conversational_action_controller import (
    ConversationalActionController,
    ConversationalActionStatus,
)
from core.dialogue.conversational_intent_continuity import (
    ActionContext,
    ConversationalIntentContinuityResolver,
)
from core.dialogue.feedback_builder import FeedbackBuilder
from core.execution.action_pipeline import ActionPipeline
from core.execution.execution_dispatcher import ExecutionDispatcher
from core.execution.execution_gate_bridge import ExecutionGateBridge
from core.execution.idempotency_guard import ExecutionIdempotencyGuard
from core.execution.post_execution_verifier import (
    PostExecutionVerifier,
)
from skills.base_skill import BaseSkill
from skills.skill_models import SkillDefinition, SkillManifest, SkillResult, SkillStatus
from skills.skill_registry import SkillRegistry

# ── SKILLS Y VERIFICADORES DE PRUEBA ──────────────────────────────────────────


class SpySkill(BaseSkill):
    """Skill espía para registrar invocaciones y parámetros sin tocar el sistema operativo."""

    def __init__(self, skill_id: str = "windows.apps") -> None:
        self.call_count = 0
        self.last_params: dict[str, Any] | None = None
        self.invocations: list[dict[str, Any]] = []
        manifest = SkillManifest(
            id=skill_id,
            name="Spy Skill",
            version="1.0.0",
            description="Spy skill for conversational continuity testing",
            author="Jessyca Core",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "windows.launch_app", "windows.close_app"),
        )
        definition = SkillDefinition(
            skill_id=skill_id,
            name="Spy Skill",
            version="1.0.0",
            description="Spy skill definition",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "windows.launch_app", "windows.close_app"),
            manifest=manifest,
        )
        super().__init__(nombre=skill_id, nivel_riesgo=1, definition=definition)

    def execute(self, context: Any) -> SkillResult:
        self.call_count += 1
        self.last_params = dict(context.parameters)
        tool_name = getattr(context, "tool_name", "unknown")
        self.invocations.append({"tool": tool_name, "params": self.last_params})
        return SkillResult(
            skill_id=self.nombre,
            success=True,
            status=SkillStatus.COMPLETED,
            output={"exito": True, "mensaje": "Proceso ejecutado", "evidence": {"is_verified": True}},
        )

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        self.last_params = dict(parametros)
        self.invocations.append({"tool": "ejecutar", "params": self.last_params})
        return {"exito": True, "mensaje": "Proceso ejecutado", "evidence": {"is_verified": True}}


class MockBooleanVerifier:
    """Verificador simulado de bajo nivel para confirmar presencia o ausencia de procesos."""

    def __init__(self, process_exists: bool = True) -> None:
        self.process_exists = process_exists


# ── FIXTURES DE PRUEBA ────────────────────────────────────────────────────────


@pytest.fixture
def clean_continuity_env():
    """Configura un entorno aislado completo para pruebas de continuidad conversacional."""
    spy_apps = SpySkill("windows.apps")
    spy_media = SpySkill("windows.media")

    registry = SkillRegistry()
    registry.register_skill(spy_apps)
    registry.register_skill(spy_media)

    dispatcher = ExecutionDispatcher(registry=registry)
    guard = ExecutionIdempotencyGuard()
    guard.reset()
    verifier = PostExecutionVerifier()
    feedback = FeedbackBuilder()
    conf_mgr = ConfirmationManager()
    gate_bridge = ExecutionGateBridge(confirmation_manager=conf_mgr)
    planner = ActionPlanner()

    pipeline = ActionPipeline(
        planner=planner,
        gate_bridge=gate_bridge,
        dispatcher=dispatcher,
        verifier=verifier,
        feedback_builder=feedback,
        idempotency_guard=guard,
    )

    resolver = ConversationalIntentContinuityResolver()
    controller = ConversationalActionController(
        pipeline=pipeline,
        feedback_builder=feedback,
        continuity_resolver=resolver,
        default_ttl_seconds=120.0,
    )
    controller.clear_all()

    return {
        "controller": controller,
        "pipeline": pipeline,
        "spy_apps": spy_apps,
        "spy_media": spy_media,
        "resolver": resolver,
    }


# ── TESTS PRINCIPALES (A a S) ─────────────────────────────────────────────────


def test_case_a_open_notepad_then_close_it(clean_continuity_env):
    """A. 'Abre notepad' -> 'ciérralo' -> Debe resolver notepad y ejecutar confirmación."""
    controller = clean_continuity_env["controller"]
    spy_apps = clean_continuity_env["spy_apps"]
    session_id = "sess_a"

    # Turno 1: Abrir bloc de notas (SAFE -> se ejecuta directamente)
    r1 = controller.process_turn(
        "Abre Bloc de notas",
        session_id=session_id,
        custom_verifier=MockBooleanVerifier(process_exists=True),
    )
    assert r1.status == ConversationalActionStatus.COMPLETED
    assert spy_apps.call_count == 1
    assert spy_apps.last_params.get("nombre_app") == "notepad"

    # Contexto actualizado con notepad
    ctx = controller.get_action_context(session_id)
    assert ctx is not None
    assert ctx.target == "notepad"
    assert ctx.action == "open_application"

    # Turno 2: "Ciérralo" -> Debe resolver target=notepad, acción=close_application (HIGH risk -> pide confirmación)
    r2 = controller.process_turn(
        "Ciérralo",
        session_id=session_id,
    )
    assert r2.status == ConversationalActionStatus.WAITING_CONFIRMATION
    pending_a = controller.get_pending(session_id)
    assert pending_a is not None
    assert pending_a.action_intent.target == "notepad"

    # Turno 3: "Sí" -> Confirma el cierre de notepad
    r3 = controller.process_turn(
        "Sí",
        session_id=session_id,
        custom_verifier=MockBooleanVerifier(process_exists=False),
    )
    assert r3.status == ConversationalActionStatus.COMPLETED
    assert spy_apps.call_count == 2
    assert spy_apps.last_params.get("nombre_app") == "notepad"
    assert "cerré Bloc de notas" in r3.spoken_response


def test_case_b_open_chrome_then_close_it(clean_continuity_env):
    """B. 'Abre Chrome' -> 'ciérralo' -> Debe resolver Chrome."""
    controller = clean_continuity_env["controller"]
    spy_apps = clean_continuity_env["spy_apps"]
    session_id = "sess_b"

    # Turno 1: Abrir Chrome
    r1 = controller.process_turn(
        "Abre Chrome",
        session_id=session_id,
        custom_verifier=MockBooleanVerifier(process_exists=True),
    )
    assert r1.status == ConversationalActionStatus.COMPLETED
    assert spy_apps.last_params.get("nombre_app") == "chrome"

    # Turno 2: "Ciérralo" -> Debe resolver Chrome
    r2 = controller.process_turn(
        "Ciérralo",
        session_id=session_id,
    )
    assert r2.status == ConversationalActionStatus.WAITING_CONFIRMATION
    pending_b = controller.get_pending(session_id)
    assert pending_b is not None
    assert pending_b.action_intent.target == "chrome"

    # Confirmar
    r3 = controller.process_turn("Sí", session_id=session_id, custom_verifier=MockBooleanVerifier(process_exists=False))
    assert r3.status == ConversationalActionStatus.COMPLETED
    assert spy_apps.last_params.get("nombre_app") == "chrome"
    assert "cerré Chrome" in r3.spoken_response


def test_case_c_two_applications_ambiguity(clean_continuity_env):
    """C. Dos aplicaciones en contexto -> pronombre ambiguo -> Debe pedir aclaración (CLARIFY)."""
    controller = clean_continuity_env["controller"]
    spy_apps = clean_continuity_env["spy_apps"]
    session_id = "sess_c"

    # Establecer contexto con 2 aplicaciones candidatas
    controller.set_action_context(
        session_id,
        ActionContext(
            action_id="act_prev_composite",
            action="open_application",
            skill="windows.apps",
            operation="launch_app",
            target="chrome",
            entities=("chrome", "notepad"),
            status="COMPLETED",
        ),
    )

    # Turno del usuario: "Ciérralo."
    r = controller.process_turn("Ciérralo", session_id=session_id)

    # Debe exigir aclaración desambiguadora y NO despachar ninguna acción
    assert r.status == ConversationalActionStatus.CLARIFICATION_REQUIRED
    assert spy_apps.call_count == 0
    assert "¿Cuál quieres que cierre" in r.response_text
    assert "Chrome" in r.response_text
    assert "Bloc de notas" in r.response_text


def test_case_d_expired_context(clean_continuity_env):
    """D. Contexto expirado -> Debe pedir aclaración y NO llamar al Dispatcher."""
    controller = clean_continuity_env["controller"]
    spy_apps = clean_continuity_env["spy_apps"]
    session_id = "sess_d"

    # Crear contexto expirado hace 500 segundos (con TTL de 120s)
    old_time = time.time() - 500.0
    controller.set_action_context(
        session_id,
        ActionContext(
            action_id="act_old",
            action="open_application",
            skill="windows.apps",
            operation="launch_app",
            target="notepad",
            timestamp=old_time,
            ttl_seconds=120.0,
            status="COMPLETED",
        ),
    )

    # Turno del usuario: "Ciérralo."
    r = controller.process_turn("Ciérralo", session_id=session_id)

    # Debe solicitar aclaración porque la información expiró
    assert r.status == ConversationalActionStatus.CLARIFICATION_REQUIRED
    assert spy_apps.call_count == 0
    assert "¿Qué aplicación deseas que cierre?" in r.response_text


def test_case_e_new_action_replaces_previous_context(clean_continuity_env):
    """E. Nueva acción reemplaza el contexto anterior de forma ordenada y predecible."""
    controller = clean_continuity_env["controller"]
    session_id = "sess_e"

    # 1. Abrir Bloc de notas -> context target = notepad
    controller.process_turn("Abre Bloc de notas", session_id=session_id, custom_verifier=MockBooleanVerifier(process_exists=True))
    assert controller.get_action_context(session_id).target == "notepad"

    # 2. Abrir Chrome -> context target = chrome
    controller.process_turn("Abre Chrome", session_id=session_id, custom_verifier=MockBooleanVerifier(process_exists=True))
    assert controller.get_action_context(session_id).target == "chrome"

    # 3. "Ciérralo" -> Debe resolver chrome, no notepad
    r = controller.process_turn("Ciérralo", session_id=session_id)
    assert r.status == ConversationalActionStatus.WAITING_CONFIRMATION
    pending_e = controller.get_pending(session_id)
    assert pending_e is not None
    assert pending_e.action_intent.target == "chrome"
    assert pending_e.action_intent.target != "notepad"


def test_case_f_g_h_pending_confirmation_priority(clean_continuity_env):
    """F, G, H. Acción pendiente de confirmación tiene prioridad sobre contexto completado anterior."""
    controller = clean_continuity_env["controller"]
    spy_apps = clean_continuity_env["spy_apps"]
    session_id = "sess_fgh"

    # Última acción completada: Bloc de notas
    controller.set_action_context(
        session_id,
        ActionContext(
            action_id="act_completed_notepad",
            action="open_application",
            skill="windows.apps",
            operation="launch_app",
            target="notepad",
            status="COMPLETED",
        ),
    )

    # Petición que requiere confirmación: "Cierra Chrome"
    r_conf = controller.process_turn(
        "Cierra Chrome",
        session_id=session_id,
    )
    assert r_conf.status == ConversationalActionStatus.WAITING_CONFIRMATION
    assert controller.get_pending(session_id) is not None

    # Usuario responde: "Sí."
    # Debe confirmar EXACTAMENTE "Cierra Chrome", NO notepad
    r_yes = controller.process_turn("Sí", session_id=session_id, custom_verifier=MockBooleanVerifier(process_exists=False))
    assert r_yes.status == ConversationalActionStatus.COMPLETED
    assert spy_apps.last_params.get("nombre_app") == "chrome"

    # Caso Negativo (H): Cancelación
    controller.process_turn("Cierra Paint", session_id=session_id)
    assert controller.get_pending(session_id) is not None
    r_no = controller.process_turn("No", session_id=session_id)
    assert r_no.status == ConversationalActionStatus.CANCELLED
    assert controller.get_pending(session_id) is None


def test_case_i_failed_action_not_registered_as_successful_context(clean_continuity_env):
    """I. Última acción fallida no debe convertirse en falso contexto exitoso."""
    controller = clean_continuity_env["controller"]
    session_id = "sess_i"

    # Contexto previo válido: notepad
    controller.set_action_context(
        session_id,
        ActionContext(
            action_id="act_valid_notepad",
            action="open_application",
            skill="windows.apps",
            operation="launch_app",
            target="notepad",
            status="COMPLETED",
        ),
    )

    # Intento de abrir aplicación que falla en verificación (MockBooleanVerifier(False))
    r_fail = controller.process_turn(
        "Abre Paint",
        session_id=session_id,
        custom_verifier=MockBooleanVerifier(False),
    )
    assert r_fail.status == ConversationalActionStatus.FAILED

    # El contexto NO debe tener "paint" como última acción exitosa
    ctx = controller.get_action_context(session_id)
    assert ctx.target == "notepad"
    assert ctx.target != "paint"


def test_case_j_k_l_m_metadata_integrity(clean_continuity_env):
    """J, K, L, M. Integridad de metadatos: action_id, target, skill y operation se resuelven correctamente."""
    controller = clean_continuity_env["controller"]
    resolver = clean_continuity_env["resolver"]
    session_id = "sess_meta"

    act_ctx = ActionContext(
        action_id="act_origin_123",
        action="open_application",
        skill="windows.apps",
        operation="launch_app",
        target="calc",
        status="COMPLETED",
    )
    controller.set_action_context(session_id, act_ctx)

    # Resolución pura
    res = resolver.resolve("Ciérralo", act_ctx)
    assert res.is_reference is True
    assert res.resolved_intent == "close_application"
    assert res.resolved_target == "calc"
    assert res.resolved_skill == "windows.apps"
    assert res.resolved_operation == "close_application"
    assert res.resolved_parameters == {"app_name": "calc", "nombre_app": "calc"}


def test_case_n_o_no_execution_during_resolution(clean_continuity_env):
    """N, O. La resolución de contexto es estrictamente analítica y no llama al Dispatcher ni ejecuta skills."""
    controller = clean_continuity_env["controller"]
    spy_apps = clean_continuity_env["spy_apps"]
    resolver = clean_continuity_env["resolver"]
    session_id = "sess_no_exec"

    act_ctx = ActionContext(
        action_id="act_init",
        action="open_application",
        skill="windows.apps",
        operation="launch_app",
        target="notepad",
        status="COMPLETED",
    )
    controller.set_action_context(session_id, act_ctx)

    # 1. Llamar a resolver.resolve directamente
    r_res = resolver.resolve("Ciérralo", act_ctx)
    assert r_res.is_reference is True
    assert spy_apps.call_count == 0

    # 2. Llamar a controller.resolve_turn_continuity
    r_cont = controller.resolve_turn_continuity("Ciérralo", session_id=session_id)
    assert r_cont.is_reference is True
    assert spy_apps.call_count == 0


# ── TESTS ESPECIALES DE SEGURIDAD Y CASOS DE USO ──────────────────────────────


def test_special_safety_not_modifying_context_prematurely(clean_continuity_env):
    """TEST ESPECIAL DE SEGURIDAD:
    Contexto: target = notepad
    Nueva entrada: 'Abre Chrome.'
    NO modificar accidentalmente el contexto anterior antes de que corresponda.
    Luego: 'Ciérralo.' -> Debe resolver Chrome.
    """
    controller = clean_continuity_env["controller"]
    session_id = "sess_safety"

    # Contexto inicial: target = notepad
    controller.set_action_context(
        session_id,
        ActionContext(
            action_id="act_pad",
            action="open_application",
            skill="windows.apps",
            operation="launch_app",
            target="notepad",
            status="COMPLETED",
        ),
    )

    # Comprobar resolución previa a la ejecución de "Abre Chrome"
    # "Abre Chrome" no es una referencia; tiene su propio target explícito
    res_chrome = controller.resolve_turn_continuity("Abre Chrome", session_id=session_id)
    assert res_chrome.is_reference is False
    # El contexto previo sigue intacto como notepad antes de la ejecución
    assert controller.get_action_context(session_id).target == "notepad"

    # Ejecutar "Abre Chrome" exitosamente
    r_exec = controller.process_turn("Abre Chrome", session_id=session_id, custom_verifier=MockBooleanVerifier(True))
    assert r_exec.status == ConversationalActionStatus.COMPLETED

    # Ahora sí el contexto se ha actualizado a Chrome
    assert controller.get_action_context(session_id).target == "chrome"

    # Luego: "Ciérralo" -> Debe resolver Chrome
    res_followup = controller.resolve_turn_continuity("Ciérralo", session_id=session_id)
    assert res_followup.is_reference is True
    assert res_followup.resolved_target == "chrome"


def test_special_ambiguity_composite_turn(clean_continuity_env):
    """TEST DE AMBIGÜEDAD:
    Contexto: Chrome, Bloc de notas.
    Entrada: 'Ciérralo.'
    Esperado: CLARIFY, NO Dispatcher.
    """
    controller = clean_continuity_env["controller"]
    spy_apps = clean_continuity_env["spy_apps"]
    session_id = "sess_ambig"

    controller.set_action_context(
        session_id,
        ActionContext(
            action_id="act_composite",
            action="open_application",
            skill="windows.apps",
            operation="launch_app",
            target="chrome",
            entities=("chrome", "notepad"),
            status="COMPLETED",
        ),
    )

    res = controller.process_turn("Ciérralo", session_id=session_id)
    assert res.status == ConversationalActionStatus.CLARIFICATION_REQUIRED
    assert spy_apps.call_count == 0
    assert "Chrome o Bloc de notas" in res.response_text


def test_special_confirmation_preservation(clean_continuity_env):
    """TEST DE CONFIRMACIÓN:
    Pendiente: close_application(notepad).
    Entrada: 'Sí.'
    Esperado: confirmar EXACTAMENTE close_application(notepad). No reinterpretar 'sí' como nueva acción.
    """
    controller = clean_continuity_env["controller"]
    spy_apps = clean_continuity_env["spy_apps"]
    session_id = "sess_conf_preserv"

    # Iniciar cierre de notepad (HIGH risk -> WAITING_CONFIRMATION)
    r1 = controller.process_turn("Cierra Bloc de notas", session_id=session_id)
    assert r1.status == ConversationalActionStatus.WAITING_CONFIRMATION
    assert spy_apps.call_count == 0

    # Usuario dice "Sí."
    r2 = controller.process_turn("Sí", session_id=session_id, custom_verifier=MockBooleanVerifier(process_exists=False))
    assert r2.status == ConversationalActionStatus.COMPLETED
    assert spy_apps.call_count == 1
    assert spy_apps.last_params.get("nombre_app") == "notepad"


def test_media_pause_continuity(clean_continuity_env):
    """Prueba continuidad multimedia: 'Reproduce música' -> 'Páusala.'"""
    controller = clean_continuity_env["controller"]
    session_id = "sess_media"

    controller.set_action_context(
        session_id,
        ActionContext(
            action_id="act_media_1",
            action="play_media",
            skill="windows.media",
            operation="play",
            target="música",
            status="COMPLETED",
        ),
    )

    res = controller.resolve_turn_continuity("Páusala", session_id=session_id)
    assert res.is_reference is True
    assert res.resolved_intent == "pause_media"
    assert res.resolved_skill == "windows.media"
    assert res.resolved_target == "música"


def test_repeat_action_continuity(clean_continuity_env):
    """Prueba repetición / elipsis: 'Abre Bloc de notas' -> 'De nuevo' / 'Otra vez'."""
    controller = clean_continuity_env["controller"]
    session_id = "sess_repeat"

    controller.set_action_context(
        session_id,
        ActionContext(
            action_id="act_rep_1",
            action="open_application",
            skill="windows.apps",
            operation="launch_app",
            target="notepad",
            status="COMPLETED",
        ),
    )

    res1 = controller.resolve_turn_continuity("De nuevo", session_id=session_id)
    assert res1.is_reference is True
    assert res1.resolved_intent == "open_application"
    assert res1.resolved_target == "notepad"

    res2 = controller.resolve_turn_continuity("Otra vez", session_id=session_id)
    assert res2.is_reference is True
    assert res2.resolved_target == "notepad"


def test_demonstrative_phrase_continuity(clean_continuity_env):
    """Prueba frases demostrativas: 'Cierra esa aplicación' / 'Cierra eso'."""
    controller = clean_continuity_env["controller"]
    session_id = "sess_dem"

    controller.set_action_context(
        session_id,
        ActionContext(
            action_id="act_dem_1",
            action="open_application",
            skill="windows.apps",
            operation="launch_app",
            target="edge",
            status="COMPLETED",
        ),
    )

    res1 = controller.resolve_turn_continuity("Cierra esa aplicación", session_id=session_id)
    assert res1.is_reference is True
    assert res1.resolved_target == "edge"

    res2 = controller.resolve_turn_continuity("Cierra eso", session_id=session_id)
    assert res2.is_reference is True
    assert res2.resolved_target == "edge"


def test_no_prior_context_returns_clarification(clean_continuity_env):
    """Prueba que sin contexto previo 'Ciérralo' pide aclaración sin inventar contexto."""
    controller = clean_continuity_env["controller"]
    spy_apps = clean_continuity_env["spy_apps"]
    session_id = "sess_empty"

    r = controller.process_turn("Ciérralo", session_id=session_id)
    assert r.status == ConversationalActionStatus.CLARIFICATION_REQUIRED
    assert spy_apps.call_count == 0
    assert "¿Qué aplicación deseas que cierre?" in r.response_text
