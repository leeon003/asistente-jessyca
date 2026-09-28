"""Tests del Modo Sombra (Shadow Mode): ORCA + ADE (Fase 1)."""

from __future__ import annotations

import pytest

from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import OrcaAdeMode
from core.orca_ade.shadow import OrcaAdeShadowEvaluator


class TestOrcaAdeShadow:
    """Verifica que el modo sombra registre telemetría con cero efectos colaterales."""

    def test_shadow_evaluation_records_telemetry_with_zero_side_effects(self) -> None:
        shadow = OrcaAdeShadowEvaluator()
        assert shadow.adapter.mode == OrcaAdeMode.SHADOW

        record = shadow.evaluate_shadow_request(
            request_text="Refactorizar módulo de autenticación con 2 ramas",
            jde_decision="ALLOW",
            existing_handler_output="Respuesta estándar de JESSYCA Core",
        )

        assert record.side_effects == 0
        assert record.jde_expected_decision == "ALLOW"
        assert record.latency_ms > 0
        assert len(record.differences) > 0
        assert "Orca propone" in record.differences[0]
        assert len(shadow.history) == 1

    def test_shadow_evaluation_with_jde_deny(self) -> None:
        shadow = OrcaAdeShadowEvaluator()
        record = shadow.evaluate_shadow_request(
            request_text="Ejecutar script peligroso con drop database",
            jde_decision="DENY",
        )
        assert record.side_effects == 0
        assert record.jde_expected_decision == "DENY"
        assert "rechaza" in record.differences[0]

    def test_multiple_shadow_evaluations_preserve_zero_side_effects(self) -> None:
        shadow = OrcaAdeShadowEvaluator()
        requests = [
            "Crear tests para router",
            "Inspeccionar UI en design mode",
            "Optimizar cálculo de métricas",
        ]
        for req in requests:
            rec = shadow.evaluate_shadow_request(req)
            assert rec.side_effects == 0

        assert len(shadow.history) == 3
