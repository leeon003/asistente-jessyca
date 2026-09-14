"""Suite de Pruebas de Conversational Recovery & Error Resolution (test_conversational_recovery.py - Fase 64.3.4).

Verifica exhaustivamente los 17 requerimientos mandatorios de la Fase 64.3.4:
- Test 1: failure recovery -> RECOVERY_AVAILABLE
- Test 2: explicit retry -> "intenta de nuevo" re-ejecuta el pipeline normal
- Test 3: affirmative recovery -> "sí" tras fallo gatilla retry
- Test 4: negative recovery -> "no" cancela la recuperación sin ejecutar
- Test 5: cancellation -> "olvídalo" cancela limpiamente
- Test 6: modification -> "mejor abre Chrome" descarta la acción previa y despacha la nueva
- Test 7: unverified -> UNVERIFIED != SUCCESS, recovery disponible
- Test 8: verification failure -> VERIFIED_FAILURE != SUCCESS, recovery disponible
- Test 9: rejected action -> Acción rechazada no puede saltarse ExecutionGate en retry
- Test 10: sequence recovery -> Retry de secuencia ejecuta ÚNICAMENTE el paso fallido
- Test 11: no duplicate successful steps -> Pasos previamente exitosos no se duplican
- Test 12: context continuity -> "hazlo otra vez" refiere correctamente a la acción fallida
- Test 13: unrelated intent -> "¿qué hora es?" descarta recovery y procesa nueva orden
- Test 14: idempotency -> Retry genera nuevo action_id trazable sin duplicar
- Test 15: retry safety -> Acción sensible vuelve a requerir ExecutionGate / Confirmación
- Test 16: retry limit -> Exceso de reintentos detiene loop (LIMIT_EXCEEDED)
- Test 17: anti-false-success -> FAILURE / VERIFIED_FAILURE / UNVERIFIED nunca son SUCCESS
"""

from __future__ import annotations

from typing import Any

import pytest

from core.confirmation import ConfirmationManager
from core.dialogue.action_planner import ActionPlanner
from core.dialogue.action_recovery import (
    ActionFailureCategory,
    ActionRecoveryState,
)
from core.dialogue.action_sequence import (
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
from core.execution.post_execution_verifier import (
    PostExecutionVerifier,
    VerificationReport,
    VerificationReportStatus,
)
from skills.base_skill import BaseSkill
from skills.skill_models import SkillDefinition, SkillManifest, SkillResult, SkillStatus
from skills.skill_registry import SkillRegistry

# ── SPIES Y MOCKS DE APOYO ───────────────────────────────────────────────────


class MockAppSkill(BaseSkill):
    """Skill configurable para simular éxito o fallo determinista en aplicaciones."""

    def __init__(self, skill_id: str = "windows.apps") -> None:
        self.call_count = 0
        self.invocations: list[dict[str, Any]] = []
        self.should_fail_on: set[str] = set()

        manifest = SkillManifest(
            id=skill_id,
            name="Mock App Skill",
            version="1.0.0",
            description="Mock apps skill for recovery testing",
            author="Jessyca Core",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "windows.launch_app", "windows.close_app"),
        )
        definition = SkillDefinition(
            skill_id=skill_id,
            name="Mock App Skill",
            version="1.0.0",
            description="Mock apps skill definition",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "windows.launch_app", "windows.close_app"),
            manifest=manifest,
        )
        super().__init__(nombre=skill_id, nivel_riesgo=1, definition=definition)

    def execute(self, context: Any) -> SkillResult:
        self.call_count += 1
        params = dict(context.parameters)
        raw_app = str(params.get("nombre_app") or params.get("app_name") or params.get("target") or "").lower().strip()
        self.invocations.append({"app": raw_app, "params": params, "call_index": self.call_count})

        # Comprobar si coincide con should_fail_on considerando sinónimos
        fails = False
        for f in self.should_fail_on:
            f_clean = f.lower().strip()
            if f_clean in raw_app or raw_app in f_clean:
                fails = True
                break
            if f_clean in ("notepad", "bloc de notas", "bloc") and any(w in raw_app for w in ("notepad", "bloc")):
                fails = True
                break
            if f_clean in ("calc", "calculadora") and any(w in raw_app for w in ("calc", "calculadora")):
                fails = True
                break
            if f_clean in ("paint", "mspaint") and any(w in raw_app for w in ("paint", "mspaint")):
                fails = True
                break

        if fails:
            return SkillResult(
                skill_id=self.nombre,
                success=False,
                status=SkillStatus.FAILED,
                error=f"No se pudo iniciar la aplicación {raw_app}",
            )

        return SkillResult(
            skill_id=self.nombre,
            success=True,
            status=SkillStatus.COMPLETED,
            output={"exito": True, "mensaje": f"{raw_app} iniciado", "evidence": {"is_verified": True}},
        )

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        raw_app = str(parametros.get("nombre_app") or parametros.get("app_name") or parametros.get("target") or "").lower().strip()
        self.invocations.append({"app": raw_app, "params": parametros, "call_index": self.call_count})
        fails = any(f.lower() in raw_app or raw_app in f.lower() for f in self.should_fail_on)
        if fails:
            return {"exito": False, "error": f"Fallo al abrir {raw_app}"}
        return {"exito": True, "mensaje": f"{raw_app} iniciado", "evidence": {"is_verified": True}}


class MockVerifier:
    """Verificador configurable para simular verificación exitosa, fallida o no verificable."""

    def __init__(self, mode: str = "success") -> None:
        self.mode = mode  # "success", "failure", "unverified"

    def verify_action(self, operation: str, target: str, parameters: dict[str, Any]) -> tuple[str, bool]:
        if self.mode == "failure":
            return f"Efecto real no observado para {target}", False
        return f"Efecto confirmado para {target}", True

    def verify(self, intent: Any, execution: Any) -> VerificationReport:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        act_id = getattr(execution, "action_id", "mock_id")
        if self.mode == "unverified":
            return VerificationReport(
                action_id=act_id,
                skill="windows.apps",
                operation="launch_app",
                expected_effect="Efecto no verificable",
                observed_effect="Sensor no disponible",
                verification_status=VerificationReportStatus.UNVERIFIED,
                verification_method="none",
                is_verified=False,
                claims_success=False,
                timestamp=now,
                error="No verificable",
                feedback_suggestion="No se pudo comprobar si la acción tuvo efecto.",
            )
        elif self.mode == "failure":
            return VerificationReport(
                action_id=act_id,
                skill="windows.apps",
                operation="launch_app",
                expected_effect="Aplicación en ejecución",
                observed_effect="Ventana no detectada",
                verification_status=VerificationReportStatus.VERIFIED_FAILURE,
                verification_method="process_scan",
                is_verified=True,
                claims_success=False,
                timestamp=now,
                error="Ventana no detectada",
                feedback_suggestion="No se pudo verificar la apertura.",
            )
        else:
            return VerificationReport(
                action_id=act_id,
                skill="windows.apps",
                operation="launch_app",
                expected_effect="Aplicación en ejecución",
                observed_effect="Ventana activa comprobada",
                verification_status=VerificationReportStatus.VERIFIED_SUCCESS,
                verification_method="process_scan",
                is_verified=True,
                claims_success=True,
                timestamp=now,
                feedback_suggestion="Acción verificada.",
            )


# ── FIXTURE DEL CONTROLADOR Y ENTORNO ─────────────────────────────────────────


@pytest.fixture
def recovery_env() -> dict[str, Any]:
    """Entorno de prueba completamente aislado con controlador y mock skill."""
    mock_skill = MockAppSkill("windows.apps")
    registry = SkillRegistry()
    registry.register_skill(mock_skill)

    dispatcher = ExecutionDispatcher(registry=registry)
    guard = ExecutionIdempotencyGuard()
    guard.reset()
    smart_verifier = MockVerifier(mode="success")
    verifier = PostExecutionVerifier(verifier=smart_verifier)
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
        "mock_skill": mock_skill,
        "pipeline": pipeline,
        "gate_bridge": gate_bridge,
    }


# ── 17 PRUEBAS MANDATORIAS DE LA FASE 64.3.4 ─────────────────────────────────


def test_1_failure_recovery(recovery_env: dict[str, Any]) -> None:
    """Test 1: Fallo de acción genera RECOVERY_AVAILABLE con contexto de recuperación."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_1"

    skill.should_fail_on.add("bloc de notas")

    r = ctrl.process_turn("abre bloc de notas", session_id=session_id)

    assert r.status == ConversationalActionStatus.FAILED
    assert r.recovery_available is True
    assert r.recovery_state == ActionRecoveryState.RETRY_AVAILABLE
    assert "¿Quieres que lo intente de nuevo?" in r.response_text

    rec_ctx = ctrl.get_recovery_context(session_id)
    assert rec_ctx is not None
    assert rec_ctx.failure_category == ActionFailureCategory.EXECUTION_FAILURE
    assert "notepad" in str(rec_ctx.target).lower() or "bloc" in str(rec_ctx.target).lower()
    assert rec_ctx.retry_count == 0


def test_2_explicit_retry(recovery_env: dict[str, Any]) -> None:
    """Test 2: Usuario dice 'intenta de nuevo' -> re-ejecuta el pipeline normal."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_2"

    skill.should_fail_on.add("bloc de notas")
    ctrl.process_turn("abre bloc de notas", session_id=session_id)
    assert skill.call_count == 1

    # Desactivar la causa del fallo antes del reintento
    skill.should_fail_on.clear()

    # Usuario solicita reintento explícito
    r = ctrl.process_turn("intenta de nuevo", session_id=session_id)

    assert r.status == ConversationalActionStatus.COMPLETED
    assert r.recovery_state == ActionRecoveryState.RESOLVED
    assert skill.call_count == 2
    assert ctrl.get_recovery_context(session_id) is None


def test_3_affirmative_recovery(recovery_env: dict[str, Any]) -> None:
    """Test 3: Usuario responde 'sí' a la pregunta de recuperación -> reintento exitoso."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_3"

    skill.should_fail_on.add("calculadora")
    r1 = ctrl.process_turn("abre calculadora", session_id=session_id)
    assert "¿Quieres que lo intente de nuevo?" in r1.response_text

    skill.should_fail_on.clear()

    # 'sí' funciona como confirmación de reintento
    r2 = ctrl.process_turn("sí", session_id=session_id)

    assert r2.status == ConversationalActionStatus.COMPLETED
    assert skill.call_count == 2
    assert "Listo" in r2.response_text or "ahora sí" in r2.response_text.lower()
    assert ctrl.get_recovery_context(session_id) is None


def test_4_negative_recovery(recovery_env: dict[str, Any]) -> None:
    """Test 4: Usuario responde 'no' a la recuperación -> cancela el recovery sin ejecutar."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_4"

    skill.should_fail_on.add("chrome")
    ctrl.process_turn("abre chrome", session_id=session_id)
    initial_calls = skill.call_count

    # Usuario rechaza el reintento
    r = ctrl.process_turn("no", session_id=session_id)

    assert r.status == ConversationalActionStatus.CANCELLED
    assert r.recovery_state == ActionRecoveryState.CANCELLED
    assert skill.call_count == initial_calls
    assert ctrl.get_recovery_context(session_id) is None
    assert "cancelo" in r.response_text.lower()


def test_5_cancellation(recovery_env: dict[str, Any]) -> None:
    """Test 5: Usuario dice 'olvídalo' durante recovery -> cancela limpiamente."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_5"

    skill.should_fail_on.add("paint")
    ctrl.process_turn("abre paint", session_id=session_id)
    initial_calls = skill.call_count

    r = ctrl.process_turn("olvídalo", session_id=session_id)

    assert r.status == ConversationalActionStatus.CANCELLED
    assert skill.call_count == initial_calls
    assert ctrl.get_recovery_context(session_id) is None
    assert "cancelo" in r.response_text.lower()


def test_6_modification(recovery_env: dict[str, Any]) -> None:
    """Test 6: Acción A falla, usuario dice 'mejor abre Chrome' -> no reintenta A, despacha B."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_6"

    skill.should_fail_on.add("spotify")
    ctrl.process_turn("abre spotify", session_id=session_id)
    assert skill.call_count == 1
    assert skill.invocations[0]["app"] == "spotify"

    # Usuario modifica la acción
    r = ctrl.process_turn("mejor abre Chrome", session_id=session_id)

    assert r.status == ConversationalActionStatus.COMPLETED
    assert skill.call_count == 2
    # La segunda llamada fue Chrome, no Spotify
    assert skill.invocations[1]["app"] == "chrome"
    assert ctrl.get_recovery_context(session_id) is None


def test_7_unverified_result(recovery_env: dict[str, Any]) -> None:
    """Test 7: Verificación devuelve UNVERIFIED -> NO es SUCCESS y recovery disponible."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    session_id = "sess_rec_7"

    unverified_mock = MockVerifier(mode="unverified")
    r = ctrl.process_turn("abre bloc de notas", session_id=session_id, custom_verifier=unverified_mock)

    # ANTI-FALSE SUCCESS: NO debe ser COMPLETED
    assert r.status != ConversationalActionStatus.COMPLETED
    assert r.recovery_available is True
    assert r.recovery_context is not None
    assert r.recovery_context.failure_category == ActionFailureCategory.UNVERIFIED


def test_8_verification_failure(recovery_env: dict[str, Any]) -> None:
    """Test 8: Verificación devuelve VERIFIED_FAILURE -> recovery disponible."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    session_id = "sess_rec_8"

    failure_mock = MockVerifier(mode="failure")
    r = ctrl.process_turn("abre bloc de notas", session_id=session_id, custom_verifier=failure_mock)

    assert r.status == ConversationalActionStatus.FAILED
    assert r.recovery_available is True
    assert r.recovery_context is not None
    assert r.recovery_context.failure_category == ActionFailureCategory.VERIFICATION_FAILURE


def test_9_rejected_action_cannot_bypass_gate(recovery_env: dict[str, Any]) -> None:
    """Test 9: Una acción rechazada por ExecutionGate no puede saltarse el Gate en retry."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    session_id = "sess_rec_9"

    from core.action_intent_contract import (
        ActionIntent,
        ActionIntentContract,
        ExecutionGate,
        ExecutionSpec,
        PostActionFeedback,
        PreActionFeedback,
    )

    intent = ActionIntent(
        intent_name="system_format_drive",
        target="C:",
        confidence=0.95,
    )
    rejected_gate = ExecutionGate(can_execute=False, risk_level="5")
    contract = ActionIntentContract(
        request_id="act_reject_test",
        session_id=session_id,
        action_intent=intent,
        execution_gate=rejected_gate,
        pre_action_feedback=PreActionFeedback(acknowledgement_speech="Acción bloqueada"),
        execution_spec=ExecutionSpec(skill_id="windows.danger", tool_name="format", idempotency_key="key_reject_9"),
        post_action_feedback=PostActionFeedback(spoken_response="Bloqueada", response_text="Bloqueada"),
    )

    r = ctrl.process_turn("formatea disco", session_id=session_id, contract=contract)
    assert r.status == ConversationalActionStatus.REJECTED

    # Intentar retry: no puede saltarse el ExecutionGate
    r_retry = ctrl.process_turn("intenta de nuevo", session_id=session_id)
    # Debe ser rechazado o fallar, nunca tener éxito
    assert r_retry.status in (ConversationalActionStatus.REJECTED, ConversationalActionStatus.FAILED)


def test_10_sequence_recovery_only_failed_step(recovery_env: dict[str, Any]) -> None:
    """Test 10: Secuencia SUCCESS, SUCCESS, FAILURE -> retry ejecuta ÚNICAMENTE el paso 3."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_10"

    # Chrome -> OK, Bloc de notas -> OK, Spotify -> Falla
    skill.should_fail_on.add("spotify")

    r = ctrl.process_turn("abre Chrome, luego Bloc de notas y después Spotify", session_id=session_id)

    assert r.status == ConversationalActionStatus.FAILED
    assert r.recovery_available is True
    assert r.recovery_state == ActionRecoveryState.SEQUENCE_PAUSED
    assert skill.call_count == 3
    assert skill.invocations[0]["app"] == "chrome"
    assert skill.invocations[1]["app"] == "notepad"
    assert skill.invocations[2]["app"] == "spotify"

    # Ahora Spotify funcionará
    skill.should_fail_on.clear()

    # Reintentar mediante turno afirmativo
    r_retry = ctrl.process_turn("sí", session_id=session_id)

    assert r_retry.status == ConversationalActionStatus.COMPLETED
    # Se ejecutó Spotify una vez más (total llamadas = 4)
    assert skill.call_count == 4
    assert skill.invocations[3]["app"] == "spotify"


def test_11_no_duplicate_successful_steps(recovery_env: dict[str, Any]) -> None:
    """Test 11: Los pasos previamente exitosos en una secuencia NO vuelven a ejecutarse."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_11"

    skill.should_fail_on.add("spotify")
    ctrl.process_turn("abre Chrome, luego Bloc de notas y después Spotify", session_id=session_id)

    skill.should_fail_on.clear()
    ctrl.process_turn("reintenta", session_id=session_id)

    # Contar llamadas por aplicación
    chrome_calls = sum(1 for inv in skill.invocations if inv["app"] == "chrome")
    notepad_calls = sum(1 for inv in skill.invocations if inv["app"] == "notepad")
    spotify_calls = sum(1 for inv in skill.invocations if inv["app"] == "spotify")

    assert chrome_calls == 1, "Chrome no debió ejecutarse dos veces"
    assert notepad_calls == 1, "Bloc de notas no debió ejecutarse dos veces"
    assert spotify_calls == 2, "Spotify debió ejecutarse exactamente 2 veces (1 fallo + 1 retry)"


def test_12_context_continuity_after_failure(recovery_env: dict[str, Any]) -> None:
    """Test 12: Tras un fallo, 'hazlo otra vez' resuelve correctamente la acción fallida."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_12"

    skill.should_fail_on.add("spotify")
    ctrl.process_turn("abre Spotify", session_id=session_id)

    # Verificar que el contexto de fallo está correctamente registrado
    failed_ctx = ctrl.get_last_failed_context(session_id)
    assert failed_ctx is not None
    assert "spotify" in failed_ctx.target.lower()

    # Usuario usa referencia de reintento "hazlo otra vez"
    skill.should_fail_on.clear()
    r = ctrl.process_turn("hazlo otra vez", session_id=session_id)

    assert r.status == ConversationalActionStatus.COMPLETED
    assert skill.call_count == 2
    assert skill.invocations[1]["app"] == "spotify"


def test_13_unrelated_intent_abandons_recovery(recovery_env: dict[str, Any]) -> None:
    """Test 13: Tras un fallo, una orden no relacionada ('¿qué hora es?') descarta el recovery."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_13"

    skill.should_fail_on.add("spotify")
    ctrl.process_turn("abre Spotify", session_id=session_id)
    assert ctrl.get_recovery_context(session_id) is not None

    # Usuario cambia de tema
    ctrl.process_turn("¿qué hora es?", session_id=session_id)

    # El contexto de recuperación fue descartado
    assert ctrl.get_recovery_context(session_id) is None
    # No se volvió a llamar a la skill de spotify
    assert skill.call_count == 1


def test_14_idempotency_retry_action_id(recovery_env: dict[str, Any]) -> None:
    """Test 14: Cada reintento genera un action_id único derivado sin duplicar ejecuciones."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_14"

    skill.should_fail_on.add("paint")
    r1 = ctrl.process_turn("abre paint", session_id=session_id)
    orig_id = r1.action_id

    rec_ctx = ctrl.get_recovery_context(session_id)
    assert rec_ctx is not None
    assert rec_ctx.original_action_id == orig_id

    skill.should_fail_on.clear()
    r2 = ctrl.process_turn("intenta de nuevo", session_id=session_id)

    assert r2.action_id is not None
    assert orig_id is not None
    assert r2.action_id != orig_id
    assert "retry-1-" in r2.action_id or orig_id in r2.action_id


def test_15_retry_safety_sensitive_action_requires_confirmation(recovery_env: dict[str, Any]) -> None:
    """Test 15: Reintentar una acción sensible (HIGH) pasa por ExecutionGate y pide confirmación."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_15"

    # Acción de alto riesgo que requiere confirmación (cierra chrome)
    r1 = ctrl.process_turn("cierra chrome", session_id=session_id)
    assert r1.status == ConversationalActionStatus.WAITING_CONFIRMATION

    # Usuario confirma pero la skill falla
    skill.should_fail_on.add("chrome")
    r2 = ctrl.process_turn("sí", session_id=session_id)
    assert r2.status == ConversationalActionStatus.FAILED
    assert r2.recovery_available is True

    # El usuario pide reintentar la acción de alto riesgo
    # Durante el reintento, vuelve a pasar por ExecutionGate y pide confirmación
    r3 = ctrl.process_turn("intenta de nuevo", session_id=session_id)
    assert r3.status == ConversationalActionStatus.WAITING_CONFIRMATION
    assert ctrl.get_pending(session_id) is not None


def test_16_retry_limit_no_infinite_loops(recovery_env: dict[str, Any]) -> None:
    """Test 16: El límite max_retries evita loops infinitos (LIMIT_EXCEEDED)."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]
    session_id = "sess_rec_16"

    ctrl.max_retries = 2
    skill.should_fail_on.add("calculadora")

    # Intento 0: Falla inicial
    r0 = ctrl.process_turn("abre calculadora", session_id=session_id)
    assert r0.status == ConversationalActionStatus.FAILED
    assert r0.recovery_available is True

    # Reintento 1: Falla
    r1 = ctrl.process_turn("intenta de nuevo", session_id=session_id)
    assert r1.status == ConversationalActionStatus.FAILED
    assert r1.recovery_available is True

    # Reintento 2: Falla (alcanza el límite de 2)
    r2 = ctrl.process_turn("intenta de nuevo", session_id=session_id)
    assert r2.status == ConversationalActionStatus.FAILED
    assert r2.recovery_state == ActionRecoveryState.LIMIT_EXCEEDED
    assert r2.recovery_available is False
    assert "Ya lo intenté varias veces" in r2.response_text

    # Siguiente turno: ya no hay recovery
    r3 = ctrl.process_turn("intenta de nuevo", session_id=session_id)
    assert r3.recovery_available is False


def test_17_anti_false_success(recovery_env: dict[str, Any]) -> None:
    """Test 17: FAILURE, VERIFIED_FAILURE y UNVERIFIED nunca producen COMPLETED (Anti-False Success)."""
    ctrl: ConversationalActionController = recovery_env["controller"]
    skill: MockAppSkill = recovery_env["mock_skill"]

    # Caso 1: Execution failure
    skill.should_fail_on.add("notepad")
    r1 = ctrl.process_turn("abre bloc de notas", session_id="sess_afs_1")
    assert r1.status != ConversationalActionStatus.COMPLETED
    assert r1.status == ConversationalActionStatus.FAILED

    # Caso 2: Verification failure
    skill.should_fail_on.clear()
    v_fail = MockVerifier(mode="failure")
    r2 = ctrl.process_turn("abre bloc de notas", session_id="sess_afs_2", custom_verifier=v_fail)
    assert r2.status != ConversationalActionStatus.COMPLETED
    assert r2.status == ConversationalActionStatus.FAILED

    # Caso 3: Unverified
    v_unver = MockVerifier(mode="unverified")
    r3 = ctrl.process_turn("abre bloc de notas", session_id="sess_afs_3", custom_verifier=v_unver)
    assert r3.status != ConversationalActionStatus.COMPLETED
    assert r3.status in (ConversationalActionStatus.FAILED, ConversationalActionStatus.EXECUTING)
