"""Pruebas obligatorias de Anti-False-Success y Gobernanza de Ejecución.

Verifica de forma estricta e inviolable:
1. Executor ausente no produce éxito.
2. Prueba fallida conserva el fallo.
3. Aprobación sin evidencia no produce VERIFIED_SUCCESS.
4. Evidencia sintética no certifica efectos físicos.
5. Backend ausente se informa como tal (UI Backend & Browser Agent).
6. Un resultado cacheado conserva su estado de verificación.
"""

from __future__ import annotations

import builtins
import os

import pytest

from core.agents.browser_agent import BrowserAgent
from core.control_plane.models import AgentLoopState
from core.exceptions import UIBackendUnavailableError
from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import (
    OrcaAdeMode,
    OrcaTaskContract,
)
from core.orca_ade.orchestrator import OrcaGovernedOrchestrator
from core.ui_inspection_models import (
    ObservationProvenance,
    ObservationStatus,
    UIElementRequest,
)
from tools.desktop.ui_backend import WindowsUIAutomationBackend


class TestFalseSuccessAndExecutionGovernance:
    """Batería obligatoria anti-simulación y verificación física de resultados."""

    # -------------------------------------------------------------------------
    # 1. Executor ausente no produce éxito
    # -------------------------------------------------------------------------
    def test_executor_absent_does_not_produce_success(self) -> None:
        """Si falta el executor, el sistema devuelve UNAVAILABLE y verified=False."""
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.CONTROLLED)
        contract = adapter.create_task_contract(
            objective="Tarea sin ejecutor conectado",
            workspace="ws_no_exec_adapter",
            decision_id="dec_no_exec_01",
        )

        # En OrcaAdeAdapter
        result_adapter = adapter.execute_governed_task(contract, executor=None)
        assert result_adapter.status == "UNAVAILABLE"
        assert result_adapter.verified is False
        assert result_adapter.status != "VERIFIED_SUCCESS"

        # En OrcaGovernedOrchestrator
        orchestrator = OrcaGovernedOrchestrator(executor=None)
        result_orch = orchestrator.dispatch_task(
            objective="Tarea sin ejecutor en orquestador",
            workspace="ws_no_exec_orch",
            decision_id="dec_no_exec_02",
            jde_decision="ALLOW",
            executor=None,
        )
        assert result_orch.status == "UNAVAILABLE"
        assert result_orch.verified is False
        assert result_orch.status != "VERIFIED_SUCCESS"

    # -------------------------------------------------------------------------
    # 2. Prueba fallida conserva el fallo
    # -------------------------------------------------------------------------
    def test_failed_test_preserves_failure(self) -> None:
        """Cuando un comando o prueba falla (exit_code != 0), el resultado conserva el fallo."""
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.CONTROLLED)
        ws_name = "ws_failed_test"
        full_ws = os.path.join(adapter._base_worktree_dir, ws_name)
        os.makedirs(full_ws, exist_ok=True)

        real_file = os.path.join(full_ws, "script.py")
        with open(real_file, "w", encoding="utf-8") as f:
            f.write("print('error')\n")

        # Executor que reporta fallo en pruebas
        def failing_test_executor(contract: OrcaTaskContract) -> dict:
            return {
                "changed_files": [real_file],
                "tests": {"passed": False, "exit_code": 1, "error": "AssertionError: test failed"},
                "evidence": [{"type": "TEST_RUN", "exit_code": 1, "passed": False}],
            }

        orchestrator = OrcaGovernedOrchestrator(executor=failing_test_executor)
        result = orchestrator.dispatch_task(
            objective="Ejecución con pruebas fallidas",
            workspace=ws_name,
            decision_id="dec_fail_01",
            jde_decision="ALLOW",
        )

        assert result.status == "FAILED"
        assert result.verified is False
        assert result.tests.get("passed") is False
        assert result.tests.get("exit_code") == 1

        # También a nivel de Adapter
        contract = adapter.create_task_contract(
            objective="Ejecución con fallos en adapter",
            workspace=ws_name,
            decision_id="dec_fail_02",
        )
        res_adapter = adapter.execute_governed_task(contract, executor=failing_test_executor)
        assert res_adapter.status == "FAILED"
        assert res_adapter.verified is False
        assert res_adapter.tests.get("passed") is False

    # -------------------------------------------------------------------------
    # 3. Aprobación sin evidencia no produce VERIFIED_SUCCESS
    # -------------------------------------------------------------------------
    def test_approval_without_evidence_does_not_produce_verified_success(self) -> None:
        """Una aprobación nunca sustituye la comprobación.

        Aprobar sin evidencia física produce APPROVED_UNVERIFIED, no VERIFIED_SUCCESS.
        """
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.CONTROLLED)
        ws_name = "ws_approval_gate"
        full_ws = os.path.join(adapter._base_worktree_dir, ws_name)
        os.makedirs(full_ws, exist_ok=True)

        real_file = os.path.join(full_ws, "mod.py")
        with open(real_file, "w", encoding="utf-8") as f:
            f.write("# changes\n")

        def valid_executor(contract: OrcaTaskContract) -> dict:
            return {
                "changed_files": [real_file],
                "tests": {"passed": True, "exit_code": 0},
                "evidence": [],  # Sin evidencia física de verificación
            }

        orchestrator = OrcaGovernedOrchestrator(executor=valid_executor)
        res = orchestrator.dispatch_task(
            objective="Tarea pendiente de revisión",
            workspace=ws_name,
            decision_id="dec_rev_01",
            jde_decision="ALLOW",
            requires_review=True,
        )
        assert res.status == "CLAIMED_SUCCESS"
        assert res.review_status == "PENDING"
        assert res.verified is False

        # Aprobación SIN evidencia física adicional
        approved_res = orchestrator.approve_review(
            task_id=res.task_id,
            approver_authority="JDE_LEAD",
            verification_evidence=None,
        )
        # Regla: ejecutar, aprobar y verificar son estados distintos.
        assert approved_res.status == "APPROVED_UNVERIFIED"
        assert approved_res.review_status == "APPROVED"
        assert approved_res.verified is False

        # Si se aporta evidencia física verificable, entonces sí es VERIFIED_SUCCESS
        res2 = orchestrator.dispatch_task(
            objective="Tarea con evidencia posterior",
            workspace=ws_name,
            decision_id="dec_rev_02",
            jde_decision="ALLOW",
            requires_review=True,
        )
        approved_with_ev = orchestrator.approve_review(
            task_id=res2.task_id,
            approver_authority="JDE_LEAD",
            verification_evidence=[{"type": "PHYSICAL_CHECK", "verified_on_disk": True, "synthetic": False}],
        )
        assert approved_with_ev.status == "VERIFIED_SUCCESS"
        assert approved_with_ev.verified is True

    # -------------------------------------------------------------------------
    # 4. Evidencia sintética no certifica efectos físicos
    # -------------------------------------------------------------------------
    def test_synthetic_evidence_does_not_certify_physical_effects(self) -> None:
        """Evidencia marcada como sintética no debe certificar VERIFIED_SUCCESS."""
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.CONTROLLED)
        ws_name = "ws_synthetic_check"
        full_ws = os.path.join(adapter._base_worktree_dir, ws_name)
        os.makedirs(full_ws, exist_ok=True)

        real_file = os.path.join(full_ws, "target.py")
        with open(real_file, "w", encoding="utf-8") as f:
            f.write("# code\n")

        def synthetic_executor(contract: OrcaTaskContract) -> dict:
            return {
                "changed_files": [real_file],
                "tests": {"passed": True, "exit_code": 0},
                "evidence": [
                    {"type": "SIMULATED_TEST", "synthetic": True, "provenance": "SYNTHETIC_TEST"},
                ],
            }

        orchestrator = OrcaGovernedOrchestrator(executor=synthetic_executor)
        result = orchestrator.dispatch_task(
            objective="Tarea con evidencia sintética",
            workspace=ws_name,
            decision_id="dec_synth_01",
            jde_decision="ALLOW",
            requires_review=False,
        )
        # Evidencia sintética no puede resultar en VERIFIED_SUCCESS
        assert result.status == "UNVERIFIED"
        assert result.verified is False

        # Mismo comportamiento si se intenta aprobar con evidencia sintética
        res_review = orchestrator.dispatch_task(
            objective="Tarea para aprobar con evidencia falsa",
            workspace=ws_name,
            decision_id="dec_synth_02",
            jde_decision="ALLOW",
            requires_review=True,
        )
        res_approved_synth = orchestrator.approve_review(
            task_id=res_review.task_id,
            approver_authority="JDE",
            verification_evidence=[{"type": "FAKE_EVIDENCE", "synthetic": True}],
        )
        assert res_approved_synth.status == "APPROVED_UNVERIFIED"
        assert res_approved_synth.verified is False

    # -------------------------------------------------------------------------
    # 5. Backend ausente se informa como tal
    # -------------------------------------------------------------------------
    def test_backend_unavailable_reported_as_such(self, monkeypatch) -> None:
        """Cuando un backend de UI o Browser no está disponible, se informa como tal sin fingir."""
        # A) UI Automation Backend: simular fallo de importación de uiautomation
        real_import = builtins.__import__

        def fake_import_uia(name, *args, **kwargs):
            if "uiautomation" in name:
                raise ImportError("No module named 'uiautomation'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import_uia)

        ui_backend = WindowsUIAutomationBackend()

        with pytest.raises(UIBackendUnavailableError) as exc_info:
            ui_backend.list_windows()
        assert "no disponible" in str(exc_info.value)

        with pytest.raises(UIBackendUnavailableError) as exc_info2:
            ui_backend.get_active_window()
        assert "no disponible" in str(exc_info2.value)

        # La inspección retorna estado explícito BACKEND_UNAVAILABLE y sin ventanas inventadas
        result = ui_backend.inspect_ui(UIElementRequest(window_title="Inexistente"))
        assert result.metadata.status == ObservationStatus.BACKEND_UNAVAILABLE
        assert result.metadata.provenance == ObservationProvenance.UNAVAILABLE
        assert len(result.elements_flat) == 0

        # B) Browser Agent: en entorno de producción sin playwright
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("JESSYCA_BROWSER_MODE", raising=False)

        def fake_import_pw(name, *args, **kwargs):
            if "playwright" in name:
                raise ImportError("No module named 'playwright'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import_pw)

        agent = BrowserAgent()
        assert agent.is_available() is False

        # Al ejecutar una navegación, devuelve fallo explícito sin fingir éxito
        loop_res = agent.execute_intent("Abrir https://example.com")
        assert loop_res.final_state == AgentLoopState.STOPPED_ERROR
        assert loop_res.output_metadata.get("status") == "BROWSER_UNAVAILABLE"
        assert loop_res.output_metadata.get("provenance") == "UNAVAILABLE"

    # -------------------------------------------------------------------------
    # 6. Un resultado cacheado conserva su estado de verificación
    # -------------------------------------------------------------------------
    def test_cached_result_preserves_verification_state(self) -> None:
        """Un cache hit de un resultado no verificado (o unverified) NO debe convertirse en verificado."""
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.CONTROLLED)
        ws_name = "ws_cache_preservation"
        full_ws = os.path.join(adapter._base_worktree_dir, ws_name)
        os.makedirs(full_ws, exist_ok=True)

        real_file = os.path.join(full_ws, "cache_target.py")
        with open(real_file, "w", encoding="utf-8") as f:
            f.write("# cache test\n")

        # Executor que produce un resultado NO verificado (sin evidencia física)
        def unverified_executor(contract: OrcaTaskContract) -> dict:
            return {
                "changed_files": [real_file],
                "tests": {"passed": True, "exit_code": 0},
                "evidence": [],  # Sin evidencia física
            }

        orchestrator = OrcaGovernedOrchestrator(executor=unverified_executor)

        # 1. Ejecución con requires_review=True -> CLAIMED_SUCCESS (verified=False)
        res1 = orchestrator.dispatch_task(
            objective="Tarea para verificar preservación de cache",
            workspace=ws_name,
            decision_id="dec_cache_01",
            jde_decision="ALLOW",
            requires_review=True,
        )
        assert res1.status == "CLAIMED_SUCCESS"
        assert res1.verified is False

        # 2. Segunda ejecución idéntica -> debe ser CACHE_HIT pero CONSERVAR verified=False
        res2 = orchestrator.dispatch_task(
            objective="Tarea para verificar preservación de cache",
            workspace=ws_name,
            decision_id="dec_cache_02",
            jde_decision="ALLOW",
            requires_review=True,
        )
        assert res2.status == "CACHE_HIT"
        assert res2.verified is False  # Inviolable: cache hit no inventa verificación
        assert res2.metadata.get("cache_hit") is True

        # 3. También en OrcaAdeAdapter
        contract1 = adapter.create_task_contract(
            objective="Cache en adapter unverified",
            workspace=ws_name,
            decision_id="dec_cache_ad_01",
        )
        ad_res1 = adapter.execute_governed_task(contract1, executor=unverified_executor)
        assert ad_res1.verified is False

        contract2 = adapter.create_task_contract(
            objective="Cache en adapter unverified",
            workspace=ws_name,
            decision_id="dec_cache_ad_02",
        )
        ad_res2 = adapter.execute_governed_task(contract2, executor=unverified_executor)
        assert ad_res2.status == "CACHE_HIT"
        assert ad_res2.verified is False
