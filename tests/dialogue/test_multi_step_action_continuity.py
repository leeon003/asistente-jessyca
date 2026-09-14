"""Suite de Pruebas de Continuidad de Acciones Multi-Paso (test_multi_step_action_continuity.py - Fase 64.3.3).

Verifica exhaustivamente los requerimientos de la Fase 64.3.3:
- A: Dos acciones secuenciales exitosas.
- B: Paso 1 exitoso -> Paso 2 exitoso.
- C: Paso 1 falla -> Paso 2 NO se ejecuta (STOP_ON_FAILURE).
- D: Paso requiere confirmación -> Secuencia PAUSED en WAITING_CONFIRMATION.
- E: Confirmación positiva ("Sí") -> reanuda y completa la secuencia.
- F: Confirmación negativa ("No" / "Cancelar") -> cancela secuencia y pasos pendientes.
- G / I: Pronombre singular ambiguo con 2 candidatos -> CLARIFICATION_REQUIRED.
- H: Referencia múltiple plural ("ciérralos") resuelta inequívocamente a todos los candidatos.
- J: Cada paso posee step_id y action_id únicos.
- K: Reprocesamiento no duplica acciones (Idempotencia).
- L: Verificación independiente por paso (PostExecutionVerifier).
- M: Contexto conversacional actualizado tras cada paso completado.
- N: Nueva orden durante pausa descarta limpiamente la secuencia previa.
- O: Cancelación evita pasos pendientes (SKIPPED).
- P: Excepción en un paso no derriba el controlador.
- Q: Dispatcher recibe únicamente acciones autorizadas y confirmadas.
- R: Feedback final refleja el resultado real.
- S: TEST ESPECIAL (abrir notepad y luego cerrarlo con confirmación).
- T: TEST FAILURE (paso 1 falla -> paso 2 no ejecuta).
- U: TEST DUPLICADO (doble ejecución no repite acciones).
"""

from __future__ import annotations

from typing import Any

import pytest

from core.confirmation import ConfirmationManager
from core.dialogue.action_planner import ActionPlanner
from core.dialogue.action_sequence import (
    ActionSequenceStatus,
    ActionStepStatus,
    StepPlanner,
)
from core.dialogue.conversational_action_controller import (
    ConversationalActionController,
    ConversationalActionStatus,
)
from core.dialogue.conversational_intent_continuity import (
    ConversationalIntentContinuityResolver,
)
from core.dialogue.feedback_builder import FeedbackBuilder
from core.execution.action_pipeline import ActionPipeline
from core.execution.execution_dispatcher import ExecutionDispatcher
from core.execution.execution_gate_bridge import ExecutionGateBridge
from core.execution.idempotency_guard import ExecutionIdempotencyGuard
from core.execution.post_execution_verifier import PostExecutionVerifier
from skills.base_skill import BaseSkill
from skills.skill_models import SkillDefinition, SkillManifest, SkillResult, SkillStatus
from skills.skill_registry import SkillRegistry

# ── SPIES Y MOCKS DE APOYO ───────────────────────────────────────────────────


class SpyAppsSkill(BaseSkill):
    """Skill espía configurable para simular éxito o fallo en aplicaciones Windows."""

    def __init__(self, skill_id: str = "windows.apps") -> None:
        self.call_count = 0
        self.last_params: dict[str, Any] | None = None
        self.invocations: list[dict[str, Any]] = []
        self.should_fail_on_app: str | None = None
        self.raise_exception: bool = False

        manifest = SkillManifest(
            id=skill_id,
            name="Spy Apps Skill",
            version="1.0.0",
            description="Spy apps skill for multi-step continuity testing",
            author="Jessyca Core",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "windows.launch_app", "windows.close_app"),
        )
        definition = SkillDefinition(
            skill_id=skill_id,
            name="Spy Apps Skill",
            version="1.0.0",
            description="Spy apps skill definition",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "windows.launch_app", "windows.close_app"),
            manifest=manifest,
        )
        super().__init__(nombre=skill_id, nivel_riesgo=1, definition=definition)

    def execute(self, context: Any) -> SkillResult:
        if self.raise_exception:
            raise RuntimeError("Fallo catastrófico simulado en la skill")

        self.call_count += 1
        self.last_params = dict(context.parameters)
        tool_name = getattr(context, "intent", getattr(context, "tool_name", "unknown"))
        app_name = self.last_params.get("nombre_app") or self.last_params.get("app_name") or ""
        self.invocations.append({"tool": tool_name, "app": app_name, "params": self.last_params})

        if self.should_fail_on_app and self.should_fail_on_app.lower() in app_name.lower():
            return SkillResult(
                skill_id=self.nombre,
                success=False,
                status=SkillStatus.FAILED,
                error=f"Fallo simulado al procesar {app_name}",
            )

        return SkillResult(
            skill_id=self.nombre,
            success=True,
            status=SkillStatus.COMPLETED,
            output={"exito": True, "mensaje": f"Proceso {app_name} ejecutado", "evidence": {"is_verified": True}},
        )

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        self.last_params = dict(parametros)
        app_name = self.last_params.get("nombre_app") or self.last_params.get("app_name") or ""
        self.invocations.append({"tool": "ejecutar", "params": self.last_params, "app": app_name})
        return {"exito": True, "mensaje": f"Proceso {app_name} ejecutado", "evidence": {"is_verified": True}}


class SmartVerifier:
    """Verificador inteligente para secuencias que verifica tanto apertura como cierre."""

    def __init__(self, fail_on_app: str | None = None) -> None:
        self.fail_on_app = fail_on_app

    def verify_action(self, operation: str, target: str, parameters: dict[str, Any]) -> tuple[str, bool]:
        if self.fail_on_app and self.fail_on_app.lower() in target.lower():
            return f"Verificación fallida en {target}", False
        return f"Verificación exitosa: efecto real comprobado en {target}", True


# ── FIXTURE DE ENTORNO AISLADO ────────────────────────────────────────────────


@pytest.fixture
def clean_sequence_env():
    """Configura un entorno completo y aislado para pruebas de secuencias multi-paso."""
    spy_apps = SpyAppsSkill("windows.apps")
    spy_media = SpyAppsSkill("windows.media")

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
    step_planner = StepPlanner()

    controller = ConversationalActionController(
        pipeline=pipeline,
        feedback_builder=feedback,
        continuity_resolver=resolver,
        step_planner=step_planner,
        default_ttl_seconds=120.0,
    )
    controller.clear_all()

    return {
        "controller": controller,
        "pipeline": pipeline,
        "spy_apps": spy_apps,
        "spy_media": spy_media,
        "step_planner": step_planner,
        "resolver": resolver,
        "guard": guard,
    }


# ── TESTS PRINCIPALES (A a U) ─────────────────────────────────────────────────


def test_case_a_b_two_sequential_successful_actions(clean_sequence_env) -> None:
    """A y B. Dos acciones secuenciales exitosas se ejecutan en orden con ActionPipeline."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    spy_apps: SpyAppsSkill = clean_sequence_env["spy_apps"]
    session_id = "sess_ab"

    # "Abre Chrome y luego abre Bloc de notas" (ambas SAFE -> ejecución secuencial directa)
    r = controller.process_turn(
        "Abre Chrome y luego abre Bloc de notas",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )

    assert r.status == ConversationalActionStatus.COMPLETED
    assert spy_apps.call_count == 2
    # El orden debe ser estricto: primero Chrome, luego Notepad
    assert spy_apps.invocations[0]["app"] == "chrome"
    assert spy_apps.invocations[1]["app"] == "notepad"

    # Contexto actualizado al último paso (Bloc de notas)
    ctx = controller.get_action_context(session_id)
    assert ctx is not None
    assert ctx.target == "notepad"
    assert "completé la secuencia" in r.response_text or "Listo" in r.response_text


def test_case_c_stop_on_failure(clean_sequence_env) -> None:
    """C. Si el paso 1 falla, el paso 2 NO se ejecuta (STOP_ON_FAILURE)."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    spy_apps: SpyAppsSkill = clean_sequence_env["spy_apps"]
    session_id = "sess_c"

    # Configurar para que Chrome falle en la skill
    spy_apps.should_fail_on_app = "chrome"

    r = controller.process_turn(
        "Abre Chrome y luego abre Bloc de notas",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )

    # La secuencia debe detenerse en fallo
    assert r.status == ConversationalActionStatus.FAILED
    assert "no pudo completarse" in r.response_text or "falló" in r.response_text

    # Chrome fue intentado (1 llamada), pero Bloc de notas NUNCA fue ejecutado
    assert spy_apps.call_count == 1
    assert spy_apps.invocations[0]["app"] == "chrome"

    # No hay secuencia pendiente
    assert controller.get_pending_sequence(session_id) is None


def test_case_d_e_special_open_then_close_with_confirmation(clean_sequence_env) -> None:
    """D, E y TEST ESPECIAL: 'Abre Bloc de notas y luego ciérralo'.

    Paso 1: open notepad -> SAFE -> ejecutado y verificado con éxito.
    Paso 2: close notepad -> HIGH -> PAUSA en WAITING_CONFIRMATION.
    Turno 'Sí' -> Paso 2 ejecutado una sola vez -> COMPLETED.
    """
    controller: ConversationalActionController = clean_sequence_env["controller"]
    spy_apps: SpyAppsSkill = clean_sequence_env["spy_apps"]
    session_id = "sess_special"

    # Turno 1: Solicitud compuesta
    r1 = controller.process_turn(
        "Abre Bloc de notas y luego ciérralo",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )

    # Paso 1 ejecutado con éxito
    assert spy_apps.call_count == 1
    assert spy_apps.invocations[0]["app"] == "notepad"
    assert spy_apps.invocations[0]["tool"] in ("windows.launch_app", "apps.open")

    # Paso 2 solicita confirmación -> secuencia PAUSADA
    assert r1.status == ConversationalActionStatus.WAITING_CONFIRMATION
    assert "cerrar" in r1.response_text.lower() or "confirmas" in r1.response_text.lower()

    # Comprobar que hay secuencia pendiente pausada
    pending_seq = controller.get_pending_sequence(session_id)
    assert pending_seq is not None
    assert pending_seq.overall_status == ActionSequenceStatus.WAITING_CONFIRMATION
    assert pending_seq.current_step == 2
    assert pending_seq.completed_steps[0].target == "notepad"

    # Turno 2: Usuario confirma con "Sí"
    r2 = controller.process_turn(
        "Sí",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )

    # Paso 2 ejecutado y verificado exactamente una vez
    assert r2.status == ConversationalActionStatus.COMPLETED
    assert spy_apps.call_count == 2
    assert spy_apps.invocations[1]["app"] == "notepad"
    assert spy_apps.invocations[1]["tool"] in ("windows.close_app", "apps.close")

    # Secuencia culminada y liberada
    assert controller.get_pending_sequence(session_id) is None
    # Contexto actualizado a close_application notepad
    ctx = controller.get_action_context(session_id)
    assert ctx is not None
    assert ctx.target == "notepad"
    assert ctx.action == "close_application"


def test_case_f_step_confirmation_rejection_cancels(clean_sequence_env) -> None:
    """F. Confirmación negativa ('No' / 'Cancelar') cancela la secuencia sin ejecutar pasos pendientes."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    spy_apps: SpyAppsSkill = clean_sequence_env["spy_apps"]
    session_id = "sess_f"

    # Paso 1 abre Chrome (SAFE), Paso 2 cierra Bloc de notas (HIGH)
    r1 = controller.process_turn(
        "Abre Chrome y luego cierra Bloc de notas",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )
    assert r1.status == ConversationalActionStatus.WAITING_CONFIRMATION
    assert spy_apps.call_count == 1
    assert spy_apps.invocations[0]["app"] == "chrome"

    # Turno 2: Usuario cancela
    r2 = controller.process_turn("Cancelar", session_id=session_id)
    assert r2.status == ConversationalActionStatus.CANCELLED
    assert "cancelada" in r2.response_text.lower()

    # Paso 2 NUNCA se ejecutó en la skill
    assert spy_apps.call_count == 1
    assert controller.get_pending_sequence(session_id) is None


def test_case_g_i_ambiguous_singular_asks_clarification(clean_sequence_env) -> None:
    """G e I. Dos aplicaciones en contexto -> pronombre singular 'ciérralo' -> CLARIFY."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    spy_apps: SpyAppsSkill = clean_sequence_env["spy_apps"]
    session_id = "sess_gi"

    # Abrir dos aplicaciones simultáneamente
    controller.process_turn(
        "Abre Chrome y Bloc de notas",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )
    assert spy_apps.call_count == 2

    # Pronombre singular: "Ciérralo" -> ¿Cuál de las dos?
    r = controller.process_turn("Ciérralo", session_id=session_id)
    assert r.status == ConversationalActionStatus.CLARIFICATION_REQUIRED
    assert "¿Cuál quieres que cierre" in r.response_text
    assert "Chrome" in r.response_text
    assert "Bloc de notas" in r.response_text

    # No se envió ninguna orden de cierre al Dispatcher
    assert spy_apps.call_count == 2


def test_case_h_plural_reference_closes_both_apps(clean_sequence_env) -> None:
    """H. 'Abre Chrome y Bloc de notas' -> 'Ciérralos' -> Secuencia de cierre para ambos."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    spy_apps: SpyAppsSkill = clean_sequence_env["spy_apps"]
    session_id = "sess_h"

    # Abrir ambas aplicaciones
    controller.process_turn(
        "Abre Chrome y Bloc de notas",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )
    assert spy_apps.call_count == 2

    # Turno plural inequívoco: "Ciérralos"
    r = controller.process_turn("Ciérralos", session_id=session_id)

    # Como el cierre es de riesgo HIGH, el paso 1 pausa para confirmación
    assert r.status == ConversationalActionStatus.WAITING_CONFIRMATION
    pending_seq = controller.get_pending_sequence(session_id)
    assert pending_seq is not None
    assert len(pending_seq.steps) == 2

    # Confirmar paso 1
    r2 = controller.process_turn("Sí", session_id=session_id, custom_verifier=SmartVerifier())
    # Si el paso 2 también requiere confirmación (close es HIGH)
    if r2.status == ConversationalActionStatus.WAITING_CONFIRMATION:
        r3 = controller.process_turn("Sí", session_id=session_id, custom_verifier=SmartVerifier())
        assert r3.status == ConversationalActionStatus.COMPLETED

    # Ambas aplicaciones fueron cerradas
    closed_apps = [inv["app"] for inv in spy_apps.invocations if "close" in inv["tool"]]
    assert "chrome" in closed_apps
    assert "notepad" in closed_apps


def test_case_h2_multi_turn_plural_continuity(clean_sequence_env) -> None:
    """H2. Turno 1: 'Abre Bloc de notas', Turno 2: 'Abre Chrome', Turno 3: 'Ciérralos'."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    spy_apps: SpyAppsSkill = clean_sequence_env["spy_apps"]
    session_id = "sess_h2"

    # Turno 1
    controller.process_turn("Abre Bloc de notas", session_id=session_id, custom_verifier=SmartVerifier())
    # Turno 2
    controller.process_turn("Abre Chrome", session_id=session_id, custom_verifier=SmartVerifier())
    assert spy_apps.call_count == 2

    # Turno 3: "Ciérralos" (detecta ambas aplicaciones abiertas en la sesión)
    r = controller.process_turn("Ciérralos", session_id=session_id)
    assert r.status == ConversationalActionStatus.WAITING_CONFIRMATION

    # Confirmar cierres
    r2 = controller.process_turn("Sí", session_id=session_id, custom_verifier=SmartVerifier())
    if r2.status == ConversationalActionStatus.WAITING_CONFIRMATION:
        controller.process_turn("Sí", session_id=session_id, custom_verifier=SmartVerifier())

    closed_apps = [inv["app"] for inv in spy_apps.invocations if "close" in inv["tool"]]
    assert "notepad" in closed_apps
    assert "chrome" in closed_apps


def test_case_j_unique_action_id_and_step_id(clean_sequence_env) -> None:
    """J. Cada paso de la secuencia tiene step_id y action_id únicos."""
    step_planner: StepPlanner = clean_sequence_env["step_planner"]
    seq = step_planner.plan_sequence("Abre Chrome y luego abre Bloc de notas", session_id="sess_j")
    assert seq is not None
    assert len(seq.steps) == 2
    assert seq.steps[0].step_id != seq.steps[1].step_id
    assert seq.steps[0].action_id != seq.steps[1].action_id
    assert seq.steps[0].step_number == 1
    assert seq.steps[1].step_number == 2


def test_case_k_reprocessing_does_not_duplicate_actions(clean_sequence_env) -> None:
    """K y TEST DUPLICADO: Reprocesar la misma secuencia no duplica pasos ya completados."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    spy_apps: SpyAppsSkill = clean_sequence_env["spy_apps"]
    session_id = "sess_k"

    step_planner: StepPlanner = clean_sequence_env["step_planner"]
    seq = step_planner.plan_sequence("Abre Chrome y luego abre Bloc de notas", session_id=session_id)
    assert seq is not None

    # Primera ejecución
    r1 = controller._execute_sequence(seq, session_id=session_id, custom_verifier=SmartVerifier())
    assert r1.status == ConversationalActionStatus.COMPLETED
    assert spy_apps.call_count == 2

    # Segunda ejecución con el mismo objeto de secuencia (pasos ya marcados COMPLETED)
    r2 = controller._execute_sequence(seq, session_id=session_id, custom_verifier=SmartVerifier())
    assert r2.status == ConversationalActionStatus.COMPLETED

    # No se incrementaron las llamadas a la skill
    assert spy_apps.call_count == 2


def test_case_l_independent_verification_per_step(clean_sequence_env) -> None:
    """L. Cada paso se somete a verificación independiente y separada."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    session_id = "sess_l"

    # Verificador que rechaza la verificación de notepad en el paso 2
    failing_verifier = SmartVerifier(fail_on_app="notepad")

    r = controller.process_turn(
        "Abre Chrome y luego abre Bloc de notas",
        session_id=session_id,
        custom_verifier=failing_verifier,
    )

    # El paso 1 (Chrome) se verificó con éxito, pero el paso 2 (Notepad) falló la verificación
    assert r.status == ConversationalActionStatus.FAILED
    assert "falló el paso 2" in r.response_text or "error" in r.response_text.lower()


def test_case_m_context_updated_after_each_step(clean_sequence_env) -> None:
    """M. El contexto conversacional se actualiza paso a paso con el resultado del último paso."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    session_id = "sess_m"

    controller.process_turn(
        "Abre Chrome y luego abre Bloc de notas",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )

    ctx = controller.get_action_context(session_id)
    assert ctx is not None
    # El contexto final refleja el último paso ejecutado (Notepad)
    assert ctx.target == "notepad"
    assert ctx.action == "open_application"


def test_case_n_new_order_safely_redirects_from_sequence(clean_sequence_env) -> None:
    """N. Nueva orden ('No, mejor abre Spotify') descarta la secuencia previa sin ejecutar pasos pendientes."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    spy_apps: SpyAppsSkill = clean_sequence_env["spy_apps"]
    session_id = "sess_n"

    # Iniciar secuencia con confirmación en paso 2
    r1 = controller.process_turn(
        "Abre Chrome y luego cierra Bloc de notas",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )
    assert r1.status == ConversationalActionStatus.WAITING_CONFIRMATION
    assert spy_apps.call_count == 1

    # Usuario formula una nueva orden explícita
    r2 = controller.process_turn(
        "No, mejor abre Spotify",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )
    assert r2.status == ConversationalActionStatus.COMPLETED
    assert spy_apps.call_count == 2
    assert spy_apps.invocations[1]["app"] == "spotify"

    # Bloc de notas NUNCA fue cerrado
    closed_apps = [inv["app"] for inv in spy_apps.invocations if "close" in inv["tool"]]
    assert "notepad" not in closed_apps
    assert controller.get_pending_sequence(session_id) is None


def test_case_o_cancellation_skips_pending_steps(clean_sequence_env) -> None:
    """O. Cancelar una secuencia en pausa marca los pasos posteriores como SKIPPED."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    session_id = "sess_o"

    # Secuencia de 2 pasos
    controller.process_turn(
        "Abre Chrome y luego cierra Bloc de notas",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )
    pending_seq = controller.get_pending_sequence(session_id)
    assert pending_seq is not None

    # Rechazar
    controller.process_turn("No", session_id=session_id)

    # Paso 2 rechazado y secuencia cancelada
    assert pending_seq.steps[1].status == ActionStepStatus.REJECTED
    assert pending_seq.overall_status == ActionSequenceStatus.CANCELLED


def test_case_p_exception_does_not_crash_controller(clean_sequence_env) -> None:
    """P. Excepción imprevista dentro de un paso no derriba el controlador y retorna FAILED."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    spy_apps: SpyAppsSkill = clean_sequence_env["spy_apps"]
    session_id = "sess_p"

    spy_apps.raise_exception = True

    r = controller.process_turn(
        "Abre Chrome y luego abre Bloc de notas",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )

    assert r.status == ConversationalActionStatus.FAILED
    assert "error" in r.response_text.lower()
    assert controller.get_pending_sequence(session_id) is None


def test_case_q_dispatcher_receives_only_authorized_steps(clean_sequence_env) -> None:
    """Q. ExecutionDispatcher recibe únicamente pasos debidamente autorizados."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    spy_apps: SpyAppsSkill = clean_sequence_env["spy_apps"]
    session_id = "sess_q"

    # Acción simple de cierre: requiere confirmación
    controller.process_turn("Cierra Chrome", session_id=session_id)
    # No autorizado todavía -> call_count debe ser 0
    assert spy_apps.call_count == 0

    # Rechazar -> call_count debe seguir siendo 0
    controller.process_turn("No", session_id=session_id)
    assert spy_apps.call_count == 0


def test_case_r_final_feedback_reflects_reality(clean_sequence_env) -> None:
    """R. El feedback final refleja exactamente las acciones completadas en la secuencia."""
    controller: ConversationalActionController = clean_sequence_env["controller"]
    session_id = "sess_r"

    r = controller.process_turn(
        "Abre Chrome y luego abre Bloc de notas",
        session_id=session_id,
        custom_verifier=SmartVerifier(),
    )
    assert r.status == ConversationalActionStatus.COMPLETED
    assert "Listo" in r.spoken_response or "completé" in r.spoken_response.lower()
