"""Pruebas de Integración para ConversationalActionController (Fase 64.3.1).

Valida exhaustivamente la integración del ActionPipeline con el diálogo continuo:
A. Nueva acción sin confirmación -> Pipeline normal (COMPLETED).
B. Acción que requiere confirmación -> WAITING_CONFIRMATION.
C. "Sí" -> Continúa acción pendiente (COMPLETED).
D. "No" -> Cancela acción pendiente (CANCELLED).
E. "Claro" -> Continúa acción afirmativamente.
F. "Adelante" -> Continúa acción afirmativamente.
G. "Hazlo" -> Continúa acción afirmativamente.
H. "Cancela" -> Cancela acción pendiente.
I. Confirmación expirada -> NO Dispatcher, estado EXPIRED con mensaje específico.
J. Confirmación inexistente ("Sí") -> NO acción ejecutada, estado IDLE.
K. Confirmación de acción A seguida de nueva orden B -> NO ejecutar A accidentalmente.
L. Acción ya ejecutada + nuevo "Sí" -> NO ejecutar nuevamente.
M. Doble "Sí" -> Una sola ejecución (idempotencia).
N. action_id permanece correcto a lo largo del flujo.
O. Confirmation A no puede autorizar ActionIntent B.
P. Dispatcher solamente recibe acciones autorizadas.
Q. Verification continúa funcionando.
R. Feedback continúa reflejando el resultado real.
S. Tests especiales: Seguridad ante desvío, Verificación de Contexto, Expiración estricta y Doble Ejecución.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.action_intent_contract import (
    ActionIntent,
    ActionIntentContract,
    ExecutionGate,
    ExecutionSpec,
    PreActionFeedback,
)
from core.confirmation import ConfirmationManager
from core.dialogue.action_planner import ActionPlanner
from core.dialogue.conversational_action_controller import (
    ConversationalActionController,
    ConversationalActionStatus,
    classify_confirmation_intent,
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


class SpySkill(BaseSkill):
    """Skill espía para registrar invocaciones y parámetros sin tocar aplicaciones reales."""

    def __init__(self, skill_id: str = "windows.apps") -> None:
        self.call_count = 0
        self.last_params: dict[str, Any] | None = None
        self.invocations: list[dict[str, Any]] = []
        manifest = SkillManifest(
            id=skill_id,
            name="Spy Skill",
            version="1.0.0",
            description="Spy skill for conversational action testing",
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
        self.invocations.append({"tool": getattr(context, "tool_name", "unknown"), "params": self.last_params})
        return SkillResult(
            skill_id="windows.apps",
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


@pytest.fixture
def isolated_controller() -> tuple[ConversationalActionController, SpySkill]:
    """Crea una instancia aislada del ConversationalActionController con SkillRegistry y Dispatcher frescos."""
    spy_skill = SpySkill(skill_id="windows.apps")
    registry = SkillRegistry()
    registry.register_skill(spy_skill)

    guard = ExecutionIdempotencyGuard()
    guard.reset()

    dispatcher = ExecutionDispatcher(registry=registry)
    gate_bridge = ExecutionGateBridge(confirmation_manager=ConfirmationManager())
    post_verifier = PostExecutionVerifier()
    feedback_b = FeedbackBuilder()
    planner = ActionPlanner()

    pipeline = ActionPipeline(
        planner=planner,
        gate_bridge=gate_bridge,
        dispatcher=dispatcher,
        verifier=post_verifier,
        feedback_builder=feedback_b,
        idempotency_guard=guard,
    )
    pipeline.reset()

    controller = ConversationalActionController(
        pipeline=pipeline,
        feedback_builder=feedback_b,
        default_ttl_seconds=60.0,
    )
    controller.clear_all()

    return controller, spy_skill


# ── TEST CLASSIFIER ──────────────────────────────────────────────────────────


def test_classifier_affirmative_and_negative() -> None:
    """Valida el clasificador determinista para frases afirmativas, negativas y comandos libres."""
    # Afirmativas
    for text in ("sí", "si", "claro", "adelante", "hazlo", "correcto", "dale", "confirma", "sí, hazlo", "si hazlo", "sí por favor", "si, si"):
        assert classify_confirmation_intent(text) is True, f"Fallo al clasificar '{text}' como afirmativo"

    # Negativas
    for text in ("no", "cancela", "cancelar", "mejor no", "déjalo", "dejalo", "no lo hagas", "no gracias", "detente", "alto"):
        assert classify_confirmation_intent(text) is False, f"Fallo al clasificar '{text}' como negativo"

    # Comandos libres / Otros
    for text in ("abre bloc de notas", "cierra calculadora", "busca en internet", "hola", "qué hora es"):
        assert classify_confirmation_intent(text) is None, f"Fallo: '{text}' no debió ser respuesta a confirmación"


# ── TEST A: NUEVA ACCIÓN SIN CONFIRMACIÓN ───────────────────────────────────


def test_turn_a_new_action_without_confirmation(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST A — Nueva acción sin confirmación: Abre Bloc de notas -> Pipeline ejecuta y retorna COMPLETED."""
    controller, spy = isolated_controller
    mock_v = MockBooleanVerifier(process_exists=True)

    result = controller.process_turn(
        user_input="Abre Bloc de notas",
        session_id="session_test_a",
        custom_verifier=mock_v,
    )

    assert result.status == ConversationalActionStatus.COMPLETED
    assert result.is_terminal is True
    assert spy.call_count == 1
    assert "abrí Bloc de notas" in result.spoken_response


# ── TEST B: ACCIÓN QUE REQUIERE CONFIRMACIÓN ────────────────────────────────


def test_turn_b_action_requiring_confirmation(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST B — Acción sensible: Cierra Bloc de notas -> WAITING_CONFIRMATION (Dispatcher NO llamado)."""
    controller, spy = isolated_controller

    result = controller.process_turn(
        user_input="Cierra Bloc de notas",
        session_id="session_test_b",
    )

    assert result.status == ConversationalActionStatus.WAITING_CONFIRMATION
    assert result.is_terminal is False
    assert spy.call_count == 0  # No invocado todavía
    assert controller.get_pending("session_test_b") is not None


# ── TEST C: CONFIRMACIÓN AFIRMATIVA "SÍ" ─────────────────────────────────────


def test_turn_c_confirm_yes(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST C — Turno 1: Cierra -> WAITING_CONFIRMATION. Turno 2: 'Sí' -> Ejecución COMPLETED."""
    controller, spy = isolated_controller
    mock_v = MockBooleanVerifier(process_exists=False)  # False = aplicación cerrada con éxito

    # Turno 1
    r1 = controller.process_turn("Cierra Bloc de notas", session_id="session_test_c")
    assert r1.status == ConversationalActionStatus.WAITING_CONFIRMATION
    assert spy.call_count == 0

    # Turno 2
    r2 = controller.process_turn("Sí", session_id="session_test_c", custom_verifier=mock_v)
    assert r2.status == ConversationalActionStatus.COMPLETED
    assert r2.is_terminal is True
    assert spy.call_count == 1
    assert "cerré Bloc de notas" in r2.spoken_response
    # Acción pendiente debe quedar limpia
    assert controller.get_pending("session_test_c") is None


# ── TEST D: CANCELACIÓN "NO" ─────────────────────────────────────────────────


def test_turn_d_confirm_no(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST D — Turno 1: Cierra -> WAITING_CONFIRMATION. Turno 2: 'No' -> CANCELLED (Dispatcher no invocado)."""
    controller, spy = isolated_controller

    r1 = controller.process_turn("Cierra Bloc de notas", session_id="session_test_d")
    assert r1.status == ConversationalActionStatus.WAITING_CONFIRMATION

    r2 = controller.process_turn("No", session_id="session_test_d")
    assert r2.status == ConversationalActionStatus.CANCELLED
    assert r2.is_terminal is True
    assert spy.call_count == 0  # NUNCA ejecutado
    assert "cancelada" in r2.spoken_response.lower()
    assert controller.get_pending("session_test_d") is None


# ── TESTS E, F, G: VARIACIONES AFIRMATIVAS ("Claro", "Adelante", "Hazlo") ───


@pytest.mark.parametrize("affirmative_phrase", ["Claro", "Adelante", "Hazlo", "Sí, hazlo"])
def test_turns_e_f_g_affirmative_variants(
    affirmative_phrase: str,
    isolated_controller: tuple[ConversationalActionController, SpySkill],
) -> None:
    """TESTS E, F, G — Variaciones afirmativas reanudan y completan la acción sensible pendiente."""
    controller, spy = isolated_controller
    mock_v = MockBooleanVerifier(process_exists=False)

    sess = f"session_test_aff_{affirmative_phrase}"
    controller.process_turn("Cierra Bloc de notas", session_id=sess)
    assert spy.call_count == 0

    r = controller.process_turn(affirmative_phrase, session_id=sess, custom_verifier=mock_v)
    assert r.status == ConversationalActionStatus.COMPLETED
    assert spy.call_count == 1
    assert "cerré Bloc de notas" in r.spoken_response


# ── TEST H: VARIACIÓN NEGATIVA ("Cancela") ───────────────────────────────────


def test_turn_h_negative_cancela(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST H — Usuario dice 'Cancela' -> Cancela acción pendiente y limpia el contexto."""
    controller, spy = isolated_controller

    controller.process_turn("Cierra Bloc de notas", session_id="session_test_h")
    r = controller.process_turn("Cancela", session_id="session_test_h")

    assert r.status == ConversationalActionStatus.CANCELLED
    assert spy.call_count == 0
    assert "cancelada" in r.spoken_response.lower()


# ── TEST I: CONFIRMACIÓN EXPIRADA ────────────────────────────────────────────


def test_turn_i_expired_confirmation(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST I — Confirmación con TTL vencido -> Rechaza con 'Ya no tengo esa acción pendiente'."""
    controller, spy = isolated_controller

    # Turno 1: Registrar con TTL negativo (expirada de inmediato)
    r1 = controller.process_turn(
        "Cierra Bloc de notas",
        session_id="session_test_i",
        ttl_seconds=-5.0,  # Ya expirada
    )
    assert r1.status == ConversationalActionStatus.WAITING_CONFIRMATION

    # Turno 2: Usuario intenta confirmar
    r2 = controller.process_turn("Sí", session_id="session_test_i")
    assert r2.status == ConversationalActionStatus.EXPIRED
    assert spy.call_count == 0  # NO Dispatcher
    assert "Ya no tengo esa acción pendiente" in r2.spoken_response
    assert controller.get_pending("session_test_i") is None


# ── TEST J: CONFIRMACIÓN INEXISTENTE ("SÍ" EN FRÍO) ──────────────────────────


def test_turn_j_orphan_confirmation(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST J — 'Sí' sin confirmación previa no ejecuta ninguna acción histórica (IDLE)."""
    controller, spy = isolated_controller

    r = controller.process_turn("Sí", session_id="session_test_j")
    assert r.status == ConversationalActionStatus.IDLE
    assert spy.call_count == 0
    assert "No tengo ninguna acción pendiente" in r.spoken_response


# ── TEST K: NUEVA ORDEN DURANTE ESPERA DE CONFIRMACIÓN ───────────────────────


def test_turn_k_new_order_during_confirmation(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST K (Seguridad) — Acción A en espera. Llega Orden B ('Abre Calculadora') -> Descartar A y ejecutar B."""
    controller, spy = isolated_controller
    mock_v = MockBooleanVerifier(process_exists=True)

    # 1. Acción A sensible
    r1 = controller.process_turn("Cierra Bloc de notas", session_id="session_test_k")
    assert r1.status == ConversationalActionStatus.WAITING_CONFIRMATION
    act_a_id = r1.action_id

    # 2. En lugar de responder Sí/No, el usuario pide otra orden
    r2 = controller.process_turn("Abre Calculadora", session_id="session_test_k", custom_verifier=mock_v)

    # Debe ejecutar la calculadora directamente y haber descartado la orden de cerrar
    assert r2.status == ConversationalActionStatus.COMPLETED
    assert r2.action_id != act_a_id
    assert "calculadora" in r2.spoken_response.lower()
    assert "abrí" in r2.spoken_response.lower()

    # La acción anterior A no debe quedar pendiente
    assert controller.get_pending("session_test_k") is None


# ── TEST L: ACCIÓN YA EJECUTADA + NUEVO "SÍ" ─────────────────────────────────


def test_turn_l_already_executed_then_yes(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST L — Tras ejecutar una acción, un nuevo 'Sí' no la repite."""
    controller, spy = isolated_controller
    mock_v = MockBooleanVerifier(process_exists=False)

    controller.process_turn("Cierra Bloc de notas", session_id="session_test_l")
    r_first_yes = controller.process_turn("Sí", session_id="session_test_l", custom_verifier=mock_v)
    assert r_first_yes.status == ConversationalActionStatus.COMPLETED
    assert spy.call_count == 1

    # Usuario repite "Sí"
    r_second_yes = controller.process_turn("Sí", session_id="session_test_l")
    assert r_second_yes.status == ConversationalActionStatus.IDLE
    assert spy.call_count == 1  # No se incrementó
    assert "No tengo ninguna acción pendiente" in r_second_yes.spoken_response


# ── TEST M: DOBLE "SÍ" / "SÍ, SÍ" (IDEMPOTENCIA) ─────────────────────────────


def test_turn_m_double_yes_idempotency(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST M — 'Sí, sí' en un solo turno ejecuta la acción pendiente exactamente una sola vez."""
    controller, spy = isolated_controller
    mock_v = MockBooleanVerifier(process_exists=False)

    controller.process_turn("Cierra Bloc de notas", session_id="session_test_m")
    r = controller.process_turn("Sí, sí", session_id="session_test_m", custom_verifier=mock_v)

    assert r.status == ConversationalActionStatus.COMPLETED
    assert spy.call_count == 1


# ── TEST N: TRAZABILIDAD DE ACTION_ID ─────────────────────────────────────────


def test_turn_n_action_id_preserved(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST N — El action_id creado en el turno 1 se conserva exactamente en la reanudación del turno 2."""
    controller, spy = isolated_controller
    mock_v = MockBooleanVerifier(process_exists=False)

    r1 = controller.process_turn("Cierra Bloc de notas", session_id="session_test_n")
    original_action_id = r1.action_id
    assert original_action_id is not None

    r2 = controller.process_turn("Sí", session_id="session_test_n", custom_verifier=mock_v)
    assert r2.action_id == original_action_id
    assert r2.contract is not None
    assert r2.contract.request_id == original_action_id


# ── TEST O: SCOPE BINDING (CONFIRMACIÓN A NO PUEDE AUTORIZAR B) ──────────────


def test_turn_o_confirmation_scope_binding(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST O — La confirmación de sesión A no autoriza la acción de otra sesión B."""
    controller, spy = isolated_controller
    mock_v = MockBooleanVerifier(process_exists=False)

    # Sesión 1: Pide cerrar Bloc de notas
    r_s1 = controller.process_turn("Cierra Bloc de notas", session_id="sess_user_1")
    assert r_s1.status == ConversationalActionStatus.WAITING_CONFIRMATION

    # Sesión 2: Dice "Sí" sin tener acción pendiente
    r_s2 = controller.process_turn("Sí", session_id="sess_user_2")
    assert r_s2.status == ConversationalActionStatus.IDLE
    assert spy.call_count == 0  # Sesión 1 NO fue ejecutada por la confirmación de Sesión 2

    # Sesión 1 sigue pendiente intacta
    assert controller.get_pending("sess_user_1") is not None

    # Sesión 1 confirma legítimamente
    r_s1_conf = controller.process_turn("Sí", session_id="sess_user_1", custom_verifier=mock_v)
    assert r_s1_conf.status == ConversationalActionStatus.COMPLETED
    assert spy.call_count == 1


# ── TEST P: DISPATCHER RECIBE SÓLO ACCIONES AUTORIZADAS ──────────────────────


def test_turn_p_dispatcher_only_receives_authorized(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST P — El Dispatcher nunca es alcanzado si la acción fue rechazada o cancelada."""
    controller, spy = isolated_controller

    controller.process_turn("Cierra Bloc de notas", session_id="session_test_p")
    controller.process_turn("No lo hagas", session_id="session_test_p")

    assert spy.call_count == 0


# ── TEST Q: VERIFICACIÓN POST-EJECUCIÓN CONTINÚA FUNCIONANDO ─────────────────


def test_turn_q_verification_integrity(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST Q — La verificación post-ejecución sigue siendo obligatoria; no se declara éxito falso si falla."""
    controller, spy = isolated_controller
    # Si simulamos que el proceso sigue existiendo tras close, el verifier reportará fallo
    mock_failing_verifier = MockBooleanVerifier(process_exists=True)

    controller.process_turn("Cierra Bloc de notas", session_id="session_test_q")
    r = controller.process_turn("Sí", session_id="session_test_q", custom_verifier=mock_failing_verifier)

    assert r.status == ConversationalActionStatus.FAILED
    assert "no pude confirmar" in r.spoken_response.lower()


# ── TEST R: FEEDBACK GENERADO DESDE RESULTADO REAL ───────────────────────────


def test_turn_r_feedback_real_reflection(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST R — El feedback generado refleja estrictamente el resultado verificado y la entidad objetivo."""
    controller, spy = isolated_controller
    mock_v = MockBooleanVerifier(process_exists=False)

    controller.process_turn("Cierra Bloc de notas", session_id="session_test_r")
    r = controller.process_turn("Adelante", session_id="session_test_r", custom_verifier=mock_v)

    assert r.status == ConversationalActionStatus.COMPLETED
    assert "Listo, cerré Bloc de notas." in r.spoken_response


# ── TEST ESPECIAL: CONTEXTO COMPLETO PRESERVADO AL DESPACHAR ─────────────────


def test_special_context_parameters_integrity(isolated_controller: tuple[ConversationalActionController, SpySkill]) -> None:
    """TEST ESPECIAL DE CONTEXTO:
    ActionIntent: action_id='req-ctx-001', skill='windows.apps', operation='apps.close', target='notepad'.
    Usuario: 'Sí'.
    Verificar que SpySkill recibe exactamente esos parámetros.
    """
    controller, spy = isolated_controller
    mock_v = MockBooleanVerifier(process_exists=False)

    intent = ActionIntent(
        intent_name="close_application",
        confidence=0.95,
        parameters={"nombre_app": "notepad"},
    )
    gate = ExecutionGate(
        can_execute=False,
        needs_confirmation=True,
        risk_level="HIGH",
        confirmation_prompt="Voy a cerrar Bloc de notas. ¿Confirmas?",
    )
    contract = ActionIntentContract(
        request_id="req-ctx-001",
        session_id="session_ctx",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(acknowledgement_speech="Cerrando."),
        execution_spec=ExecutionSpec(
            skill_id="windows.apps",
            tool_name="apps.close",
            idempotency_key="idem-ctx-001",
        ),
    )

    # Iniciar turno con el contrato explícito
    r1 = controller.process_turn(
        user_input="Cierra Bloc de notas",
        session_id="session_ctx",
        contract=contract,
    )
    assert r1.status == ConversationalActionStatus.WAITING_CONFIRMATION
    assert r1.action_id == "req-ctx-001"

    # Confirmar
    r2 = controller.process_turn("Sí", session_id="session_ctx", custom_verifier=mock_v)
    assert r2.status == ConversationalActionStatus.COMPLETED
    assert spy.call_count == 1
    assert spy.last_params is not None
    assert spy.last_params.get("nombre_app") == "notepad"
