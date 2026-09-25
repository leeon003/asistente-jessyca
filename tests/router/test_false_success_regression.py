"""tests/router/test_false_success_regression.py

Tests de regresión para los dos bugs de false_success detectados en Fase 6:

Bug 1: ShadowLogger.update_execution_metrics no recalculaba el campo 'success'
       tras actualizar tool_result y error → success quedaba como True aunque
       tool_result='failed' y error != None.

Bug 2: Phase6Logger.detect_alerts disparaba false_success alert cuando
       success=False (ya prevenido correctamente), en lugar de solo cuando
       success=True pero verification=FAILED (genuine false-success).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.llm.experimental_router import (
    Phase6Logger,
    RouterDecision,
    RouterMode,
    ShadowLogger,
    TaskCategory,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _make_decision(model: str = "gemma4:e4b") -> RouterDecision:
    return RouterDecision(
        recommended_model=model,
        fallback_chain=[model],
        reason="Test decision",
        confidence=0.9,
        task_type=TaskCategory.OTHER,
        estimated_complexity="low",
        nemotron_available=False,
        is_voice_command=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# BUG 1: ShadowLogger.update_execution_metrics debe recalcular 'success'
# ─────────────────────────────────────────────────────────────────────────────


class TestShadowLoggerSuccessRecalculation:
    """Regresión: update_execution_metrics debe recalcular 'success' al actualizar
    tool_result y error reales. Antes del fix, success permanecía True aunque la
    herramienta hubiera fallado."""

    def test_success_recalculated_to_false_when_tool_fails(self, tmp_path: Path) -> None:
        """Cuando update_execution_metrics recibe tool_result='failed', success debe ser False."""
        log_file = tmp_path / "shadow_test.jsonl"
        shadow = ShadowLogger(log_path=log_file)
        req_id = "req-regression-bug1-youtube"

        # Registro inicial (antes de la ejecución de la herramienta)
        shadow.log_decision(
            request_id=req_id,
            user_text="Reproduce la música playing Your Face en YouTube",
            current_model="gemma4:e4b",
            decision=_make_decision(),
            execution_model="gemma4:e4b",
            router_mode=RouterMode.SHADOW,
        )

        # Verificar que el registro inicial tiene success=True (herramienta aún no ejecutada)
        entries = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        assert entries[-1]["success"] is True, "El registro inicial debería ser success=True"

        # Actualizar con resultado real de la herramienta (falló)
        shadow.update_execution_metrics(
            request_id=req_id,
            tool_selected="browser.youtube",
            tool_result="failed",
            verification_result="FAILED",
            error="Se solicitó reproducir playing Your Face en YouTube.",
            execution_latency_ms=739.1,
            total_latency_ms=744.8,
        )

        # BUG 1 FIX: success debe ser False tras el update
        updated_entries = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        updated = next((e for e in updated_entries if e["request_id"] == req_id), None)
        assert updated is not None
        assert updated["tool_result"] == "failed"
        assert updated["verification_result"] == "FAILED"
        assert updated["success"] is False, (
            "BUG 1 REGRESIÓN: success debe ser False cuando tool_result='failed'"
        )

    def test_success_recalculated_to_false_when_verification_fails(self, tmp_path: Path) -> None:
        """Cuando update_execution_metrics recibe verification_result='FAILED', success debe ser False."""
        log_file = tmp_path / "shadow_test2.jsonl"
        shadow = ShadowLogger(log_path=log_file)
        req_id = "req-regression-bug1-notepad"

        shadow.log_decision(
            request_id=req_id,
            user_text="abre el bloc de notas",
            current_model="gemma4:e4b",
            decision=_make_decision(),
            execution_model="gemma4:e4b",
            router_mode=RouterMode.SHADOW,
        )

        shadow.update_execution_metrics(
            request_id=req_id,
            tool_selected="windows.launch_app",
            tool_result="failed",
            verification_result="FAILED",
            error="Intenté abrir notepad, pero Windows no confirmó que se haya abierto.",
            execution_latency_ms=2564.2,
            total_latency_ms=2564.86,
        )

        updated_entries = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        updated = next((e for e in updated_entries if e["request_id"] == req_id), None)
        assert updated is not None
        assert updated["success"] is False, (
            "BUG 1 REGRESIÓN: success debe ser False cuando verification_result='FAILED'"
        )

    def test_success_stays_true_when_tool_succeeds(self, tmp_path: Path) -> None:
        """Cuando la herramienta tiene éxito y está verificada, success debe permanecer True."""
        log_file = tmp_path / "shadow_test3.jsonl"
        shadow = ShadowLogger(log_path=log_file)
        req_id = "req-regression-success-ok"

        shadow.log_decision(
            request_id=req_id,
            user_text="abre el bloc de notas",
            current_model="gemma4:e4b",
            decision=_make_decision(),
            execution_model="gemma4:e4b",
            router_mode=RouterMode.SHADOW,
        )

        shadow.update_execution_metrics(
            request_id=req_id,
            tool_selected="windows.launch_app",
            tool_result="succeeded",
            verification_result="VERIFIED",
            error=None,
            execution_latency_ms=312.0,
            total_latency_ms=313.5,
        )

        updated_entries = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        updated = next((e for e in updated_entries if e["request_id"] == req_id), None)
        assert updated is not None
        assert updated["success"] is True, "success debe ser True cuando herramienta verificada con éxito"


# ─────────────────────────────────────────────────────────────────────────────
# BUG 2: Phase6Logger.detect_alerts — false_success solo si success=True
# ─────────────────────────────────────────────────────────────────────────────


class TestPhase6LoggerFalseSuccessDetection:
    """Regresión: detect_alerts NO debe disparar false_success cuando success=False
    porque eso significa que el sistema YA previno el false-success correctamente.
    El alert solo es válido cuando success=True pero verification!=VERIFIED."""

    def _base_detect_kwargs(self, **overrides):
        base = dict(
            recommended_model="gemma4:e4b",
            selected_model="gemma4:e4b",
            execution_model="gemma4:e4b",
            fallback=False,
            fallback_reason=None,
            inference_latency_ms=0.0,
            timeout_threshold_ms=15000.0,
            vram_after_mb=1536.0,
            vram_budget_mb=10752.0,
            tool_executed=True,
            verification="FAILED",
            total_latency_ms=744.8,
        )
        base.update(overrides)
        return base

    def test_no_false_success_alert_when_success_is_false(self, tmp_path: Path) -> None:
        """BUG 2 FIX: Si success=False + verification=FAILED → NO false_success (ya prevenido)."""
        logger = Phase6Logger(log_path=tmp_path / "p6.jsonl")
        alerts = logger.detect_alerts(**self._base_detect_kwargs(success=False))
        assert "false_success" not in alerts, (
            "BUG 2 REGRESIÓN: false_success no debe dispararse cuando success=False "
            "(el sistema ya previno el false-success correctamente)"
        )

    def test_false_success_alert_fires_when_success_true_unverified(self, tmp_path: Path) -> None:
        """El alert SÍ debe dispararse cuando success=True pero verification=FAILED."""
        logger = Phase6Logger(log_path=tmp_path / "p6.jsonl")
        alerts = logger.detect_alerts(**self._base_detect_kwargs(success=True))
        assert "false_success" in alerts, (
            "false_success debe dispararse cuando success=True pero verification=FAILED"
        )

    def test_no_false_success_when_tool_not_executed(self, tmp_path: Path) -> None:
        """Sin herramienta ejecutada (tool_executed=False), no hay false_success."""
        logger = Phase6Logger(log_path=tmp_path / "p6.jsonl")
        alerts = logger.detect_alerts(**self._base_detect_kwargs(tool_executed=False, success=True))
        assert "false_success" not in alerts

    def test_no_false_success_when_verified(self, tmp_path: Path) -> None:
        """Si la verificación es VERIFIED, no hay false_success aunque success=True."""
        logger = Phase6Logger(log_path=tmp_path / "p6.jsonl")
        alerts = logger.detect_alerts(**self._base_detect_kwargs(verification="VERIFIED", success=True))
        assert "false_success" not in alerts

    def test_log_interaction_false_success_youtube_scenario(self, tmp_path: Path) -> None:
        """Reproduce el escenario de YouTube: tool_executed=False (no se pasó), success=False.
        El Phase6Logger no debe disparar false_success porque el sistema ya lo previno."""
        logger = Phase6Logger(log_path=tmp_path / "p6_yt.jsonl")
        entry = logger.log_interaction(
            request_id="req-d21955cd-regression",
            router_enabled=False,
            intent="youtube_play",
            recommended_model="auto-routed",
            selected_model="auto-routed",
            execution_model="auto-routed",
            tool_latency_ms=739.1,
            total_latency_ms=744.8,
            vram_before_mb=1536,
            vram_after_mb=1536,
            success=False,          # El sistema ya marcó el fallo
            verification="FAILED",
            tool_executed=False,    # Phase6Logger no tiene certeza de que la herramienta se ejecutó
        )
        assert "false_success" not in entry["alerts"], (
            "YouTube scenario: false_success no debe aparecer cuando success=False"
        )

    def test_log_interaction_false_success_notepad_scenario(self, tmp_path: Path) -> None:
        """Reproduce el escenario de Notepad: tool_executed=True, success=False, verification=FAILED.
        El Phase6Logger NO debe disparar false_success (el ExecutionVerifier ya lo previno)."""
        logger = Phase6Logger(log_path=tmp_path / "p6_np.jsonl")
        entry = logger.log_interaction(
            request_id="req-017ce00b-regression",
            router_enabled=False,
            intent="open_application",
            recommended_model="llama3.2",
            selected_model="llama3.2",
            execution_model="llama3.2",
            tool_latency_ms=2563.22,
            total_latency_ms=2564.86,
            vram_before_mb=1536,
            vram_after_mb=1536,
            success=False,         # El ExecutionVerifier previno el false-success
            verification="FAILED",
            tool_executed=True,    # La herramienta fue invocada pero no verificada
        )
        assert "false_success" not in entry["alerts"], (
            "Notepad scenario: false_success no debe aparecer cuando success=False "
            "(FALSE SUCCESS PREVENTED por ExecutionVerifier)"
        )
