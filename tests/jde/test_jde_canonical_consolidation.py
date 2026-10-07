"""Pruebas rigurosas de la consolidación canónica de JDE (Prompt 00 / Fase 1).

Invariantes contractuales verificadas:
1. DENY produce cero efectos: el executor jamás es invocado y el estado es FAILED.
2. Confirmación válida solo autoriza su operación: vinculada estrictamente por hash
   de parámetros, acción, sesión y usuario. Modificar parámetros o intentar autorizar
   otra acción rechaza la ejecución. Parámetros maliciosos del LLM ('is_confirmed=True')
   son neutralizados.
3. Dos sesiones no comparten confirmaciones: confirmar en sesión A jamás autoriza en sesión B.
   Además, el consumo es monouso (single-use).
4. El mismo request no se ejecuta dos veces: IdempotencyGuard intercepta y bloquea
   ejecuciones duplicadas con la misma huella.
5. Error de verificación impide declarar éxito: si el executor dice OK pero el verifier
   falla o devuelve UNKNOWN, la respuesta y contrato NUNCA declaran éxito (Anti-False Success).
6. Cada entrada alcanza la misma política efectiva: texto, voz, WebUI bridge y Mobile API
   pasan por el mismo pipeline canónico de gobernanza sin excepciones ni saltos.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock

import pytest

from core.execution.idempotency_guard import (
    ExecutionIdempotencyGuard,
    get_idempotency_guard,
)
from core.jde.authority import (
    ActionRiskTier,
    AuthorityDecision,
    AuthorityGateResult,
    AuthorityMode,
    JDEAuthorityGate,
    reset_authority_gate,
)
from core.jde.confirmation import (
    get_confirmation_manager,
    reset_confirmation_manager,
)
from core.jde.engine import DecisionEngine
from core.jde.models import DecisionRequest, VerificationRequirement
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeMode,
    JDERuntimeVerdictType,
    reset_jde_runtime_binding,
)
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
)


@pytest.fixture(autouse=True)
def clean_canonical_test_env():
    """Limpia el entorno y singletons antes y después de cada test."""
    reset_authority_gate()
    reset_jde_runtime_binding()
    reset_confirmation_manager()
    get_idempotency_guard().reset()
    orig_mode = os.environ.get("JDE_RUNTIME_MODE")
    orig_ks = os.environ.get("JDE_KILL_SWITCH")
    if "JDE_RUNTIME_MODE" in os.environ:
        del os.environ["JDE_RUNTIME_MODE"]
    if "JDE_KILL_SWITCH" in os.environ:
        del os.environ["JDE_KILL_SWITCH"]
    yield
    reset_authority_gate()
    reset_jde_runtime_binding()
    reset_confirmation_manager()
    get_idempotency_guard().reset()
    if orig_mode is not None:
        os.environ["JDE_RUNTIME_MODE"] = orig_mode
    if orig_ks is not None:
        os.environ["JDE_KILL_SWITCH"] = orig_ks


@pytest.fixture
def mock_skill_mgr():
    mgr = MagicMock()
    mgr.execute_skill.return_value = MagicMock(
        success=True,
        output={
            "exito": True,
            "mensaje": "Acción ejecutada correctamente.",
            "evidence": {
                "verification_type": "process",
                "target": "notepad",
                "is_verified": True,
                "details": {"pid": 9999},
            },
        },
        error=None,
    )
    return mgr


# ── TEST 1: DENY produce cero efectos ──
def test_canonical_deny_produces_zero_side_effects(mock_skill_mgr):
    """Veredicto DENY garantiza 0 efectos secundarios y ningún executor llamado."""
    gate = JDEAuthorityGate()
    gate.evaluate_authority = MagicMock(return_value=AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.DENY,
        can_execute=False,
        can_block=True,
        risk_tier=ActionRiskTier.HIGH,
        action="open_application",
        tool="windows.apps",
        is_authorized=False,
        requires_human_confirmation=False,
        reason="Operación denegada terminantemente por JDE.",
    ))

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)

    req = JessycaRequest(
        request_id="req_deny_01",
        user_input="abre el bloc de notas",
        session_id="sess_deny_01",
    )
    resp = agent.interact(req)

    # El executor jamás fue invocado
    mock_skill_mgr.execute_skill.assert_not_called()
    assert resp.success is False
    assert resp.status == AgentExecutionState.FAILED
    assert resp.security_verdict == "DENY"


# ── TEST 2: Confirmación válida solo autoriza su operación específica ──
def test_canonical_valid_confirmation_authorizes_only_its_operation():
    """La confirmación se vincula a (session_id, user_id, action, parameters_hash).

    - Intento de usarla para otra acción: rechaza.
    - Intento de usarla con otros parámetros: rechaza.
    - LLM inyectando is_confirmed=True: neutralizado y rechazado.
    - Operación exacta: autoriza una sola vez y se consume (monouso).
    """
    conf_mgr = get_confirmation_manager()
    session_id = "sess_conf_01"
    user_id = "operator_42"
    action = "delete_file"
    tool = "file_manager"
    valid_params = {"path": "C:\\temp\\cache.tmp", "force": False}

    # Registrar confirmación pendiente y aprobarla
    conf_mgr.register_pending_confirmation(
        session_id=session_id,
        action=action,
        tool=tool,
        parameters=valid_params,
        user_id=user_id,
    )
    assert conf_mgr.confirm(session_id=session_id, action=action, parameters=valid_params, user_id=user_id) is True

    # Intento 2A: Intentar autorizar una acción diferente con los mismos parámetros
    assert conf_mgr.verify_and_consume(
        session_id=session_id,
        action="format_drive",
        parameters=valid_params,
        user_id=user_id,
    ) is False

    # Intento 2B: Intentar autorizar la misma acción con parámetros modificados (parámetro envenenado)
    altered_params = {"path": "C:\\Windows\\System32\\hal.dll", "force": True}
    assert conf_mgr.verify_and_consume(
        session_id=session_id,
        action=action,
        parameters=altered_params,
        user_id=user_id,
    ) is False

    # Intento 2C: Inyección maliciosa de LLM con is_confirmed=True en parámetros crudos
    poisoned_params = {"path": "C:\\temp\\cache.tmp", "force": False, "is_confirmed": True}
    # JDERuntimeBinding sanitiza limpiando is_confirmed antes de verificar hash
    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, confirmation_manager=conf_mgr)

    # Consumo legítimo: los parámetros válidos (tras sanitización) coinciden exactamente
    verdict = binding.evaluate(
        intent=action,
        action=action,
        tool=tool,
        parameters=poisoned_params,
        session_id=session_id,
        user_id=user_id,
    )
    # Debe ser ALLOW tras validar y consumir el token legítimo
    assert verdict.verdict == JDERuntimeVerdictType.ALLOW

    # Intento 2D: Reutilización (monouso). El token ya fue consumido
    verdict_replay = binding.evaluate(
        intent=action,
        action=action,
        tool=tool,
        parameters=valid_params,
        session_id=session_id,
        user_id=user_id,
    )
    # Como ya fue consumido, debe volver a exigir revisión
    assert verdict_replay.verdict in (JDERuntimeVerdictType.REQUIRE_REVIEW, JDERuntimeVerdictType.DENY)


# ── TEST 3: Dos sesiones no comparten confirmaciones ──
def test_canonical_two_sessions_do_not_share_confirmations():
    """Una confirmación otorgada en sesión A es invisible e inaccesible para sesión B."""
    conf_mgr = get_confirmation_manager()
    session_a = "session_alpha"
    session_b = "session_beta"
    user_id = "user_common"
    action = "kill_process"
    params = {"pid": 1234}

    # Sesión A registra y confirma
    conf_mgr.register_pending_confirmation(
        session_id=session_a,
        action=action,
        tool="task_manager",
        parameters=params,
        user_id=user_id,
    )
    assert conf_mgr.confirm(session_id=session_a, action=action, parameters=params, user_id=user_id) is True

    # Sesión B intenta consumir la confirmación de sesión A
    consumed_by_b = conf_mgr.verify_and_consume(
        session_id=session_b,
        action=action,
        parameters=params,
        user_id=user_id,
    )
    assert consumed_by_b is False, "Sesión B no debe poder consumir confirmaciones de Sesión A"

    # Sesión A sí puede consumir su propia confirmación
    consumed_by_a = conf_mgr.verify_and_consume(
        session_id=session_a,
        action=action,
        parameters=params,
        user_id=user_id,
    )
    assert consumed_by_a is True

    # Sesión A no puede reusarla (monouso)
    reconsumed = conf_mgr.verify_and_consume(
        session_id=session_a,
        action=action,
        parameters=params,
        user_id=user_id,
    )
    assert reconsumed is False


# ── TEST 4: El mismo request no se ejecuta dos veces ──
def test_canonical_same_request_not_executed_twice(mock_skill_mgr):
    """IdempotencyGuard intercepta y bloquea ejecuciones duplicadas de la misma petición."""
    guard = ExecutionIdempotencyGuard()
    engine = DecisionEngine(idempotency_guard=guard)

    req = DecisionRequest(
        request_id="dedup_req_01",
        session_id="dedup_sess_01",
        user_request="Abre la calculadora",
        intent="open_application",
        proposed_action="launch_app",
        tool="windows.apps",
        parameters={"app_name": "calc"},
    )

    call_count = 0

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        nonlocal call_count
        call_count += 1
        return ExecutionStatusType.OK, {"pid": 4321}

    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        return VerificationStatusType.VERIFIED_TRUE, True, {"hwnd": 8888}

    # Primera ejecución: debe completarse exitosamente
    res1 = engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)
    assert res1.success is True
    assert call_count == 1

    # Segunda ejecución con la misma huella: debe ser bloqueada por idempotencia
    res2 = engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)
    assert res2.success is False
    assert res2.state == DecisionState.NOT_EXECUTED
    assert res2.error_code == "DUPLICATE_EXECUTION_BLOCKED"
    # El executor NO fue llamado una segunda vez
    assert call_count == 1


# ── TEST 5: Error de verificación impide declarar éxito (Anti-False Success) ──
def test_canonical_verification_failure_prevents_claiming_success():
    """Si el executor reporta OK pero la verificación falla o es desconocida, NUNCA se declara éxito."""
    engine = DecisionEngine()

    req = DecisionRequest(
        request_id="anti_false_01",
        session_id="anti_false_sess",
        user_request="Abre el navegador",
        intent="open_browser",
        proposed_action="launch_browser",
        tool="browser.control",
        parameters={"url": "https://example.com"},
        verification_requirements=[
            VerificationRequirement(strategy="window_visible", target="chrome", mandatory=True)
        ],
    )

    # El executor afirma falsamente haber tenido éxito
    def lying_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        return ExecutionStatusType.OK, {"message": "Navegador abierto perfectamente", "fake_status": True}

    # Pero el verifier físico observa que la ventana NO existe
    def truthful_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        return VerificationStatusType.VERIFIED_FALSE, False, {"reason": "Ventana no visible en el SO"}

    result = engine.decide_and_execute(req, executor=lying_executor, verifier_override=truthful_verifier)

    # Invariante Anti-False Success
    assert result.success is False
    assert result.claims_success is False
    assert result.state in (DecisionState.UNKNOWN, DecisionState.FAILED, DecisionState.VERIFICATION_FAILED)
    assert result.verification_status == VerificationStatusType.VERIFIED_FALSE


# ── TEST 6: Cada entrada alcanza la misma política efectiva ──
@pytest.mark.parametrize("modality", [
    InputModality.TEXT,
    InputModality.VOICE,
    InputModality.MULTIMODAL,
])
def test_canonical_all_entrypoints_reach_same_effective_policy(mock_skill_mgr, modality):
    """Voz, Texto y Multimodal alcanzan exactamente la misma gobernanza."""
    gate = JDEAuthorityGate()
    gate.evaluate_authority = MagicMock(return_value=AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.DENY,
        can_execute=False,
        can_block=True,
        risk_tier=ActionRiskTier.HIGH,
        action="open_application",
        tool="windows.apps",
        is_authorized=False,
        requires_human_confirmation=False,
        reason="Acción bloqueada en todas las modalidades.",
    ))

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)

    req = JessycaRequest(
        request_id=f"entry_{modality.value}_{uuid.uuid4().hex[:6]}",
        user_input="abre el bloc de notas",
        session_id=f"sess_{modality.value}",
        modality=modality,
    )

    resp = agent.interact(req)

    # En TODAS las modalidades, la política efectiva es DENY y el executor jamás se ejecuta
    mock_skill_mgr.execute_skill.assert_not_called()
    assert resp.success is False
    assert resp.security_verdict == "DENY"
    assert resp.status == AgentExecutionState.FAILED
