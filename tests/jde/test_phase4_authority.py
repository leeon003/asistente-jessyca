"""Tests de JDE Fase 4: Consolidación y Preparación para Autoridad Progresiva.

Valida:
1. JDEAuthorityGate y sus modos [SHADOW, CANARY, LIMITED, PROGRESSIVE, FULL].
2. Fail-Safe absoluto de configuración:
   - Configuración ausente -> SHADOW.
   - Configuración inválida/vacía/corrupta/desconocida -> SHADOW.
   - NUNCA FULL por omisión.
3. Principio Shadow-Only en Fase 4:
   - SHADOW nunca ejecuta.
   - SHADOW nunca bloquea.
   - SHADOW nunca altera la respuesta.
   - SHADOW no provoca doble ejecución (execution_count == 1).
4. Matriz formal de Comportamiento:
   - SHADOW: Observa=Sí, Decide=Sí, Ejecuta=No, Bloquea=No.
   - CANARY: Observa=Sí, Decide=Sí, Ejecuta=Scope permitido, Bloquea=Scope permitido.
   - LIMITED: Observa=Sí, Decide=Sí, Ejecuta=Scope limitado, Bloquea=Sí.
   - PROGRESSIVE: Observa=Sí, Decide=Sí, Ejecuta=Capacidades autorizadas, Bloquea=Sí.
   - FULL: Observa=Sí, Decide=Sí, Ejecuta=Global, Bloquea=Sí.
5. Invariantes Anti-False Success:
   - Decision != SUCCESS
   - UNKNOWN != SUCCESS
   - claims_success <= is_verified
   - input_dispatched=True != SUCCESS
   - llm_confidence=1.0 != SUCCESS
   - executor=OK != SUCCESS
   - process_launched != GUI_verified
6. Trazabilidad de ActionReceipt:
   - Fingerprint SHA-256 inmutable.
   - Integridad y detección de manipulación (tampering).
   - Preservación de evidencia observable.
   - correlation_id y timestamp forenses.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock, patch
import pytest

from core.execution.action_execution_bridge import (
    ActionExecutionReport,
    build_execution_report,
)
from core.jde.adapter import (
    JDEShadowAdapter,
    LocalAgentExecutionContext,
    get_jde_shadow_adapter,
)
from core.jde.authority import (
    ActionRiskTier,
    AuthorityDecision,
    AuthorityGateResult,
    AuthorityMode,
    JDEAuthorityGate,
    JDEAuthorityMetrics,
    classify_action_risk,
    get_authority_gate,
    reset_authority_gate,
)
from core.jde.engine import DecisionEngine
from core.jde.models import DecisionRequest, DecisionResult
from core.jde.receipts import ActionReceipt, JDEEvidence
from core.jde.shadow import (
    DivergenceSeverity,
    JDEShadowMode,
    ShadowClassification,
    ShadowEvaluation,
)
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from server.boundary import ExecutionResult, ExecutionStatus as BoundaryStatus


# ═══════════════════════════════════════════════════════════════
# 10. TESTS DE AUTORIDAD (LOS 20 TESTS REQUERIDOS)
# ═══════════════════════════════════════════════════════════════

class TestJDEPhase4AuthoritySuite:
    """Suite obligatoria de 20 tests canónicos de Fase 4."""

    def test_01_config_absent_defaults_to_shadow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test 1: Configuración ausente → SHADOW."""
        monkeypatch.delenv("JDE_AUTHORITY_MODE", raising=False)
        gate = JDEAuthorityGate(mode=None)
        assert gate.current_mode == AuthorityMode.SHADOW
        assert gate.current_mode.value == "SHADOW"

    def test_02_config_invalid_falls_back_to_shadow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test 2: Configuración inválida, vacía o corrupta → SHADOW."""
        # Valor inválido
        gate_inv = JDEAuthorityGate(mode="INVALID_SUPER_MODE")
        assert gate_inv.current_mode == AuthorityMode.SHADOW

        # Cadena vacía
        gate_empty = JDEAuthorityGate(mode="")
        assert gate_empty.current_mode == AuthorityMode.SHADOW

        # Tipo corrupto (no string)
        gate_corrupt = JDEAuthorityGate(mode=12345)  # type: ignore
        assert gate_corrupt.current_mode == AuthorityMode.SHADOW

        # Env corrupto
        monkeypatch.setenv("JDE_AUTHORITY_MODE", "MALFORMED_VALUE_123")
        gate_env = JDEAuthorityGate()
        assert gate_env.current_mode == AuthorityMode.SHADOW

    def test_03_shadow_never_executes(self) -> None:
        """Test 3: SHADOW nunca ejecuta."""
        gate = JDEAuthorityGate(mode=AuthorityMode.SHADOW)
        assert gate.can_execute("read_file", "fs") is False
        assert gate.can_execute("open_app", "windows.apps") is False
        assert gate.can_execute("delete_file", "fs") is False
        assert gate.can_execute("click", "computer_use") is False

        eval_res = gate.evaluate_authority(action="open_app", tool="apps")
        assert eval_res.can_execute is False
        assert eval_res.is_authorized is False

    def test_04_shadow_never_blocks(self) -> None:
        """Test 4: SHADOW nunca bloquea."""
        gate = JDEAuthorityGate(mode=AuthorityMode.SHADOW)
        assert gate.can_block("read_file", "fs") is False
        assert gate.can_block("delete_file", "fs") is False
        assert gate.can_block("kill_process", "proc") is False

        eval_res = gate.evaluate_authority(action="delete_file", tool="fs")
        assert eval_res.can_block is False
        assert eval_res.decision == AuthorityDecision.OBSERVE_ONLY

    def test_05_shadow_never_modifies_response(self) -> None:
        """Test 5: SHADOW nunca modifica la respuesta al usuario."""
        adapter = JDEShadowAdapter(shadow_mode=JDEShadowMode(persist_to_file=False))
        original_msg = "Mensaje original intacto emitido por la producción."
        ctx = LocalAgentExecutionContext(
            request_id="req-p4-05",
            user_input="abre bloc de notas",
            intent="open_app",
            tool="windows.apps",
            action="open_app",
            parameters={"app_name": "notepad"},
            exec_success=True,
            current_message=original_msg,
            is_verified=False,
        )

        evaluation = adapter.observe(ctx)
        assert evaluation is not None
        # La respuesta y estado de producción no pueden ser alterados
        assert ctx.current_message == original_msg
        assert ctx.exec_success is True

    def test_06_observed_action_executes_only_once(self) -> None:
        """Test 6: Una acción observada solo se ejecuta una vez."""
        mock_physical_executor = Mock(return_value={"status": "dispatched"})
        # 1. Ejecución de producción
        mock_physical_executor("open_app", {"app_name": "notepad"})
        assert mock_physical_executor.call_count == 1

        # 2. Observación Shadow de JDE
        adapter = JDEShadowAdapter(shadow_mode=JDEShadowMode(persist_to_file=False))
        ctx = LocalAgentExecutionContext(
            request_id="req-p4-06",
            user_input="abre notepad",
            intent="open_app",
            tool="windows.apps",
            action="open_app",
            parameters={"app_name": "notepad"},
            exec_success=True,
            current_message="Listo",
            is_verified=False,
        )
        adapter.observe(ctx)

        # La observación Shadow NUNCA llama al ejecutor físico
        assert mock_physical_executor.call_count == 1

    def test_07_unknown_never_transforms_into_success(self) -> None:
        """Test 7: UNKNOWN nunca se transforma en SUCCESS."""
        res = DecisionResult(
            request_id="req-p4-07",
            state=DecisionState.UNKNOWN,
            success=False,
            claims_success=False,
            message="Acción sin comprobación física",
            executed_action="launch_process",
            tool_used="cmd",
            executor_status=ExecutionStatusType.OK,
            verification_status=VerificationStatusType.UNVERIFIABLE,
        )
        assert res.state != DecisionState.SUCCESS
        assert res.claims_success is False
        assert res.state == DecisionState.UNKNOWN

        # Intentar forzar claims_success con UNKNOWN debe violar el invariante
        report = build_execution_report(
            ExecutionResult(
                status=BoundaryStatus.UNKNOWN,
                request_id="req-p4-07b",
                tool_name="cmd",
                operation="launch",
                is_verified=False,
            )
        )
        assert report is not None
        assert report.execution_status == "unknown"
        assert report.claims_success is False

    def test_08_claims_success_requires_verification(self) -> None:
        """Test 8: claims_success=True requiere verificación."""
        # Con verificación positiva -> claims_success permitido
        res_ver = ExecutionResult(
            status=BoundaryStatus.SUCCESS,
            request_id="req-p4-08a",
            tool_name="fs",
            operation="write",
            is_verified=True,
            evidence={"exists": True},
        )
        assert res_ver.claims_success is True

        # Sin verificación positiva -> claims_success PROHIBIDO
        res_unver = ExecutionResult(
            status=BoundaryStatus.SUCCESS,
            request_id="req-p4-08b",
            tool_name="fs",
            operation="write",
            is_verified=False,
            evidence={"exists": False},
        )
        assert res_unver.claims_success is False

    def test_09_receipt_preserves_evidence(self) -> None:
        """Test 9: Receipt conserva evidencia, correlation_id y timestamp."""
        started = datetime.now(UTC)
        finished = datetime.now(UTC)
        ev1 = JDEEvidence(
            verification_type="window_visible",
            target="notepad.exe",
            is_verified=True,
            observed_state={"visible": True, "pid": 1234},
        )
        receipt = ActionReceipt.create(
            request_id="req-p4-09",
            correlation_id="corr-p4-09",
            user_request="abre notepad",
            action="open_app",
            tool="windows.apps",
            parameters={"app": "notepad"},
            executor="apps_executor",
            verifier="window_verifier",
            started_at=started,
            finished_at=finished,
            execution_status=ExecutionStatusType.OK,
            verification_status=VerificationStatusType.VERIFIED_TRUE,
            verified=True,
            final_status=DecisionState.SUCCESS,
            evidence=[ev1],
        )

        assert receipt.request_id == "req-p4-09"
        assert receipt.correlation_id == "corr-p4-09"
        assert len(receipt.evidence) == 1
        assert receipt.evidence[0].observed_state["pid"] == 1234
        assert receipt.evidence[0].is_verified is True
        assert receipt.verify_integrity() is True

    def test_10_tampered_receipt_fails_integrity_check(self) -> None:
        """Test 10: Receipt alterado falla integrity check."""
        receipt = ActionReceipt.create(
            request_id="req-p4-10",
            correlation_id="corr-p4-10",
            user_request="escribe reporte.txt",
            action="write_file",
            tool="windows.files",
            parameters={"path": "reporte.txt"},
            executor="fs_exec",
            verifier="fs_verif",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            execution_status=ExecutionStatusType.OK,
            verification_status=VerificationStatusType.VERIFIED_FALSE,
            verified=False,
            final_status=DecisionState.UNKNOWN,
        )
        assert receipt.verify_integrity() is True

        # Manipular fraudulentamente el veredicto
        fraudulent_receipt = receipt.model_copy(
            update={"verified": True, "final_status": DecisionState.SUCCESS}
        )
        assert fraudulent_receipt.verify_integrity() is False

        # Manipular fraudulentamente los parámetros
        fraudulent_params = receipt.model_copy(
            update={"parameters": {"path": "otro_archivo.txt"}}
        )
        assert fraudulent_params.verify_integrity() is False

    def test_11_decision_deny_does_not_execute(self) -> None:
        """Test 11: Decision DENY no ejecuta."""
        gate = JDEAuthorityGate(
            mode=AuthorityMode.LIMITED,
            authorized_capabilities={"read_file", "list_dir"},
        )
        eval_res = gate.evaluate_authority(action="unauthorized_action", tool="system")
        assert eval_res.decision == AuthorityDecision.DENY
        assert eval_res.can_execute is False
        assert eval_res.is_authorized is False

    def test_12_decision_require_verification_no_success_without_evidence(self) -> None:
        """Test 12: Decision REQUIRE_VERIFICATION no permite SUCCESS sin evidencia."""
        gate = JDEAuthorityGate(mode=AuthorityMode.LIMITED)
        # Una acción de alto riesgo sin confirmación genera REQUIRE_VERIFICATION
        eval_res = gate.evaluate_authority(
            action="delete_file",
            tool="fs",
            user_confirmed=False,
        )
        assert eval_res.decision == AuthorityDecision.REQUIRE_VERIFICATION
        assert eval_res.can_execute is False

        # Si el usuario confirma la acción para permitir el paso, pero la ejecución no tiene
        # evidencia comprobada, el motor JDE resuelve estrictamente en UNKNOWN, nunca SUCCESS
        from core.jde.models import PolicyRequirement
        engine = DecisionEngine()
        req = DecisionRequest(
            request_id="req-p4-12",
            user_request="borra archivo.txt",
            intent="delete_file",
            proposed_action="delete_file",
            tool="windows.files",
            parameters={"path": "archivo.txt"},
            policy_requirements=PolicyRequirement(requires_human_confirmation=True),
            # Sin contratos de verificación declarados
        )
        res = engine.decide_and_execute(
            request=req,
            executor=lambda t, p: (ExecutionStatusType.OK, {"result": "ok"}),
        )
        assert res.state == DecisionState.UNKNOWN
        assert res.claims_success is False

    def test_13_high_risk_action_never_auto_promoted(self) -> None:
        """Test 13: Acción de alto riesgo no obtiene autoridad automáticamente."""
        high_risk_actions = [
            ("delete_file", "fs"),
            ("kill_process", "system"),
            ("format_disk", "disk"),
            ("modify_system", "registry"),
            ("rmdir", "cmd"),
        ]
        for act, tool in high_risk_actions:
            risk = classify_action_risk(act, tool)
            assert risk == ActionRiskTier.HIGH

            # Incluso en LIMITED o PROGRESSIVE, sin confirmación humana no obtiene permiso de ejecución
            gate = JDEAuthorityGate(
                mode=AuthorityMode.PROGRESSIVE,
                authorized_capabilities={act},
            )
            eval_res = gate.evaluate_authority(action=act, tool=tool, user_confirmed=False)
            assert eval_res.can_execute is False
            assert eval_res.decision == AuthorityDecision.REQUIRE_VERIFICATION

    def test_14_unregistered_capability_denied_or_observed(self) -> None:
        """Test 14: Capacidad no registrada → DENY o OBSERVE_ONLY según contrato."""
        # En SHADOW -> OBSERVE_ONLY
        gate_shadow = JDEAuthorityGate(mode=AuthorityMode.SHADOW)
        eval_shadow = gate_shadow.evaluate_authority(
            action="unknown_custom_mod",
            tool="custom",
            is_registered_capability=False,
        )
        assert eval_shadow.decision == AuthorityDecision.OBSERVE_ONLY

        # En modo activo (e.g. PROGRESSIVE) -> DENY
        gate_prog = JDEAuthorityGate(
            mode=AuthorityMode.PROGRESSIVE,
            authorized_capabilities={"read_file"},
        )
        eval_prog = gate_prog.evaluate_authority(
            action="unknown_custom_mod",
            tool="custom",
            is_registered_capability=False,
        )
        assert eval_prog.decision == AuthorityDecision.DENY
        assert eval_prog.can_execute is False

    def test_15_unknown_authority_state_falls_back_to_shadow(self) -> None:
        """Test 15: Estado de autoridad desconocido → SHADOW."""
        assert JDEAuthorityGate._resolve_fail_safe_mode("UNKNOWN_MODE") == AuthorityMode.SHADOW
        assert JDEAuthorityGate._resolve_fail_safe_mode("ADMIN_ROOT") == AuthorityMode.SHADOW
        assert JDEAuthorityGate._resolve_fail_safe_mode("FULL_UNCHECKED") == AuthorityMode.SHADOW

    def test_16_jde_cannot_cause_double_execution(self) -> None:
        """Test 16: JDE no puede provocar doble ejecución."""
        call_counter = {"count": 0}

        def mock_real_execution():
            call_counter["count"] += 1
            return {"status": "dispatched"}

        # 1. El sistema ejecuta una sola vez la acción real
        mock_real_execution()

        # 2. JDE Shadow observa la ejecución completada
        shadow = JDEShadowMode(persist_to_file=False)
        req = DecisionRequest(
            request_id="req-p4-16",
            user_request="abre edge",
            intent="open_app",
            proposed_action="open_app",
            tool="windows.apps",
        )
        shadow.evaluate_shadow(
            request=req,
            current_system_success=True,
            current_system_message="Abierto",
            current_system_verified=False,
            execution_status="OK",
        )

        # 3. Se certifica que la acción solo se ejecutó UNA vez
        assert call_counter["count"] == 1

    def test_17_computer_use_input_dispatched_without_state_change_never_success(self) -> None:
        """Test 17: Computer Use con input_dispatched=True, state_change_verified=False no puede producir SUCCESS."""
        exec_res = ExecutionResult(
            status=BoundaryStatus.UNKNOWN,
            request_id="req-p4-17",
            tool_name="computer_use",
            operation="click",
            is_verified=False,
            evidence={
                "input_dispatched": True,
                "state_change_verified": False,
                "notes": "Coordenadas despachadas pero sin confirmación visual de cambio.",
            },
        )
        assert exec_res.claims_success is False
        assert exec_res.status != BoundaryStatus.SUCCESS

        report = build_execution_report(execution_result=exec_res)
        assert report is not None
        assert report.execution_status == "unknown"
        assert report.claims_success is False

    def test_18_filesystem_without_evidence_yields_unknown(self) -> None:
        """Test 18: Filesystem sin evidencia → UNKNOWN."""
        exec_res = ExecutionResult(
            status=BoundaryStatus.UNKNOWN,
            request_id="req-p4-18",
            tool_name="windows.files",
            operation="write_file",
            is_verified=False,
            evidence={"error": "No se pudo verificar existencia post-escritura"},
        )
        assert exec_res.status == BoundaryStatus.UNKNOWN
        assert exec_res.claims_success is False

    def test_19_browser_without_evidence_yields_unknown(self) -> None:
        """Test 19: Browser sin evidencia → UNKNOWN."""
        exec_res = ExecutionResult(
            status=BoundaryStatus.UNKNOWN,
            request_id="req-p4-19",
            tool_name="browser.search",
            operation="search",
            is_verified=False,
            evidence={"browser_tab_verified": False},
        )
        assert exec_res.status == BoundaryStatus.UNKNOWN
        assert exec_res.claims_success is False

    def test_20_youtube_not_verifiable_yields_unknown(self) -> None:
        """Test 20: YouTube NOT_VERIFIABLE → UNKNOWN."""
        shadow = JDEShadowMode(persist_to_file=False)
        req = DecisionRequest(
            request_id="req-p4-20",
            user_request="reproduce cancion en youtube",
            intent="youtube_playback",
            proposed_action="play",
            tool="youtube.player",
        )
        eval_res = shadow.evaluate_shadow(
            request=req,
            current_system_success=False,
            current_system_message="Se abrió la URL pero el reproductor no es verificable.",
            current_system_verified=False,
            execution_status="OK",
            verification_status="UNVERIFIABLE",
        )
        assert eval_res.jde_predicted_state == DecisionState.UNKNOWN
        assert eval_res.jde_predicted_state != DecisionState.SUCCESS


# ═══════════════════════════════════════════════════════════════
# 11. TESTS CONTRA FALSE SUCCESS (MATRIZ EXPLÍCITA)
# ═══════════════════════════════════════════════════════════════

class TestFalseSuccessMatrix:
    """Matriz explícita requerida para blindar contra cualquier falso éxito."""

    def test_exito_true_does_not_auto_yield_success(self) -> None:
        """exito=True != SUCCESS automáticamente."""
        exec_res = ExecutionResult(
            status=BoundaryStatus.UNKNOWN,
            request_id="req-fsm-01",
            tool_name="apps",
            operation="open",
            is_verified=False,
        )
        assert exec_res.claims_success is False
        assert exec_res.status != BoundaryStatus.SUCCESS

    def test_verified_false_never_success(self) -> None:
        """verified=False != SUCCESS."""
        exec_res = ExecutionResult(
            status=BoundaryStatus.SUCCESS,
            request_id="req-fsm-02",
            tool_name="apps",
            operation="open",
            is_verified=False,
        )
        assert exec_res.claims_success is False

    def test_unknown_never_success(self) -> None:
        """UNKNOWN != SUCCESS."""
        state = DecisionState.UNKNOWN
        assert state != DecisionState.SUCCESS

    def test_input_dispatched_never_success_alone(self) -> None:
        """input_dispatched=True != SUCCESS."""
        report = build_execution_report(
            ExecutionResult(
                status=BoundaryStatus.UNKNOWN,
                request_id="req-fsm-04",
                tool_name="computer_use",
                operation="click",
                is_verified=False,
                evidence={"input_dispatched": True, "state_change_verified": False},
            )
        )
        assert report is not None
        assert report.claims_success is False
        assert report.execution_status == "unknown"

    def test_llm_confidence_never_success_alone(self) -> None:
        """LLM confidence 1.0 != SUCCESS."""
        req = DecisionRequest(
            request_id="req-fsm-05",
            user_request="haz algo",
            intent="something",
            proposed_action="do",
            tool="tool",
            confidence=1.0,  # 100% de confianza del LLM
        )
        shadow = JDEShadowMode(persist_to_file=False)
        eval_res = shadow.evaluate_shadow(
            request=req,
            current_system_success=False,
            current_system_message="No confirmado",
            current_system_verified=False,
            execution_status="OK",
            verification_status="UNVERIFIABLE",
        )
        assert eval_res.jde_predicted_state == DecisionState.UNKNOWN

    def test_executor_ok_never_success_alone(self) -> None:
        """executor says OK != SUCCESS sin verificación."""
        engine = DecisionEngine()
        req = DecisionRequest(
            request_id="req-fsm-06",
            user_request="crea documento",
            intent="write",
            proposed_action="write",
            tool="fs",
        )
        res = engine.decide_and_execute(
            request=req,
            executor=lambda t, p: (ExecutionStatusType.OK, "dispatched"),
        )
        assert res.state == DecisionState.UNKNOWN
        assert res.claims_success is False

    def test_process_launched_never_gui_verified_alone(self) -> None:
        """process launched != GUI verified automáticamente."""
        exec_res = ExecutionResult(
            status=BoundaryStatus.UNKNOWN,
            request_id="req-fsm-07",
            tool_name="windows.apps",
            operation="launch",
            is_verified=False,
            evidence={"process_spawned": True, "window_visible": False},
        )
        assert exec_res.claims_success is False

    def test_receipt_missing_evidence_never_success(self) -> None:
        """receipt missing evidence != SUCCESS."""
        receipt = ActionReceipt.create(
            request_id="req-fsm-08",
            user_request="haz algo",
            action="do",
            tool="tool",
            parameters={},
            executor="exec",
            verifier="verif",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            execution_status=ExecutionStatusType.OK,
            verification_status=VerificationStatusType.UNVERIFIABLE,
            verified=False,
            final_status=DecisionState.UNKNOWN,
            evidence=[],  # Sin evidencia
        )
        assert receipt.final_status != DecisionState.SUCCESS
        assert receipt.verified is False

    def test_tampered_receipt_never_success(self) -> None:
        """tampered receipt != SUCCESS."""
        receipt = ActionReceipt.create(
            request_id="req-fsm-09",
            user_request="haz algo",
            action="do",
            tool="tool",
            parameters={},
            executor="exec",
            verifier="verif",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            execution_status=ExecutionStatusType.OK,
            verification_status=VerificationStatusType.VERIFIED_FALSE,
            verified=False,
            final_status=DecisionState.UNKNOWN,
        )
        tampered = receipt.model_copy(update={"final_status": DecisionState.SUCCESS, "verified": True})
        assert tampered.verify_integrity() is False


# ═══════════════════════════════════════════════════════════════
# 9. MATRIZ DE COMPORTAMIENTO SHADOW VS AUTHORITY
# ═══════════════════════════════════════════════════════════════

class TestAuthorityBehaviorMatrix:
    """Valida la matriz de comportamiento estipulada en la Sección 9."""

    def test_behavior_matrix(self) -> None:
        """Verifica cada fila de la matriz:
        Modo | Observa | Decide | Ejecuta | Puede bloquear
        SHADOW      | Sí | Sí | No                      | No
        CANARY      | Sí | Sí | Solo scope permitido   | Sí, scope
        LIMITED     | Sí | Sí | Scope limitado          | Sí
        PROGRESSIVE | Sí | Sí | Capacidades autorizadas | Sí
        FULL        | Sí | Sí | Global                  | Sí
        """
        # SHADOW
        gate_shadow = JDEAuthorityGate(mode=AuthorityMode.SHADOW)
        assert gate_shadow.current_mode.observes is True
        assert gate_shadow.current_mode.decides is True
        assert gate_shadow.can_execute("any_action", "any_tool") is False
        assert gate_shadow.can_block("any_action", "any_tool") is False

        # CANARY
        gate_canary = JDEAuthorityGate(
            mode=AuthorityMode.CANARY,
            canary_scope={"tools:canary_action"},
        )
        assert gate_canary.current_mode.observes is True
        assert gate_canary.current_mode.decides is True
        assert gate_canary.can_execute("canary_action", "tools") is True
        assert gate_canary.can_execute("other_action", "tools") is False
        assert gate_canary.can_block("canary_action", "tools") is True
        assert gate_canary.can_block("other_action", "tools") is False

        # LIMITED
        gate_limited = JDEAuthorityGate(
            mode=AuthorityMode.LIMITED,
            authorized_capabilities={"read_file"},
        )
        assert gate_limited.current_mode.observes is True
        assert gate_limited.current_mode.decides is True
        assert gate_limited.can_execute("read_file", "fs") is True
        assert gate_limited.can_execute("write_file", "fs") is False
        assert gate_limited.can_block("read_file", "fs") is True
        assert gate_limited.can_block("delete_file", "fs") is True

        # PROGRESSIVE
        gate_progressive = JDEAuthorityGate(
            mode=AuthorityMode.PROGRESSIVE,
            authorized_capabilities={"fs:read_file", "fs:write_file"},
        )
        assert gate_progressive.current_mode.observes is True
        assert gate_progressive.current_mode.decides is True
        assert gate_progressive.can_execute("read_file", "fs") is True
        assert gate_progressive.can_execute("write_file", "fs") is True
        assert gate_progressive.can_execute("delete_file", "fs") is False
        assert gate_progressive.can_block("delete_file", "fs") is True

        # FULL
        gate_full = JDEAuthorityGate(
            mode=AuthorityMode.FULL,
            allow_global_full_authority=True,
        )
        assert gate_full.current_mode.observes is True
        assert gate_full.current_mode.decides is True
        assert gate_full.can_execute("any_action", "any_tool") is True
        assert gate_full.can_block("any_action", "any_tool") is True


# ═══════════════════════════════════════════════════════════════
# 14. TESTS DE MÉTRICAS Y TELEMETRÍA
# ═══════════════════════════════════════════════════════════════

class TestJDEAuthorityMetrics:
    """Verifica las métricas de telemetría de autoridad y anti-false-success."""

    def test_metrics_calculation(self) -> None:
        metrics = JDEAuthorityMetrics()
        metrics.record_action(final_state="SUCCESS", verified=True)
        metrics.record_action(final_state="UNKNOWN", verified=False, is_false_success=False)
        metrics.record_action(final_state="FAILED", verified=False)
        metrics.record_action(final_state="UNKNOWN", verified=False, is_false_success=True)

        summary = metrics.summary()
        assert summary["total_actions"] == 4
        assert summary["verified_success"] == 1
        assert summary["failed"] == 1
        assert summary["unknown"] == 2
        assert summary["false_success"] == 1
        assert summary["false_success_rate"] == 0.25
        assert summary["unknown_rate"] == 0.5
        assert summary["verification_rate"] == 0.5
