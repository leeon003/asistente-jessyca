"""Pruebas para los modos de ejecución del JDE Runtime Binding (Fase 1).

Verifica:
- SHADOW: evalúa, registra en contrato/auditoría, pero NUNCA bloquea.
- CONTROLLED: evalúa y bloquea rigurosamente según veredicto.
- ACTIVE: no activable accidentalmente en Fase 1 (bloqueado/degradado a CONTROLLED).
- Fail-Safe ante valores nulos, vacíos o corruptos.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from core.jde.authority import (
    ActionRiskTier,
    AuthorityDecision,
    AuthorityGateResult,
    AuthorityMode,
)
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeMode,
    JDERuntimeVerdictType,
    reset_jde_runtime_binding,
)


@pytest.fixture(autouse=True)
def clean_env():
    reset_jde_runtime_binding()
    orig = os.environ.get("JDE_RUNTIME_MODE")
    if "JDE_RUNTIME_MODE" in os.environ:
        del os.environ["JDE_RUNTIME_MODE"]
    yield
    reset_jde_runtime_binding()
    if orig is not None:
        os.environ["JDE_RUNTIME_MODE"] = orig
    elif "JDE_RUNTIME_MODE" in os.environ:
        del os.environ["JDE_RUNTIME_MODE"]


def test_shadow_mode_never_blocks():
    """En modo SHADOW, incluso si el veredicto es DENY, la ejecución NUNCA se bloquea."""
    mock_gate = MagicMock()
    mock_gate.is_kill_switch_active = False
    mock_gate.current_mode = AuthorityMode.SHADOW
    mock_gate.evaluate_authority.return_value = AuthorityGateResult(
        mode=AuthorityMode.SHADOW,
        decision=AuthorityDecision.DENY,
        can_execute=False,
        can_block=False,
        risk_tier=ActionRiskTier.HIGH,
        action="critical_cmd",
        tool="windows.cmd",
        is_authorized=False,
        requires_human_confirmation=False,
        reason="Peligro extremo en evaluación JDE.",
    )

    binding = JDERuntimeBinding(mode=JDERuntimeMode.SHADOW, authority_gate=mock_gate)
    assert binding.current_mode == JDERuntimeMode.SHADOW

    verdict = binding.evaluate(
        intent="run_critical_cmd",
        action="critical_cmd",
        tool="windows.cmd",
    )

    # Invariante SHADOW: nunca bloquea la ejecución en el runtime
    assert verdict.verdict == JDERuntimeVerdictType.ALLOW
    assert not verdict.is_blocked
    assert verdict.can_proceed_to_execution
    assert verdict.runtime_mode == JDERuntimeMode.SHADOW
    assert verdict.contract is not None
    assert "Shadow mode activo" in verdict.reason


def test_controlled_mode_enforces_blocks():
    """En modo CONTROLLED, DENY y REQUIRE_REVIEW bloquean estrictamente."""
    mock_gate = MagicMock()
    mock_gate.is_kill_switch_active = False
    mock_gate.current_mode = AuthorityMode.CONTROLLED
    mock_gate.evaluate_authority.return_value = AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.DENY,
        can_execute=False,
        can_block=True,
        risk_tier=ActionRiskTier.HIGH,
        action="format_disk",
        tool="windows.disk",
        is_authorized=False,
        requires_human_confirmation=False,
        reason="Operación no autorizada.",
    )

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=mock_gate)
    assert binding.current_mode == JDERuntimeMode.CONTROLLED

    verdict = binding.evaluate(
        intent="format",
        action="format_disk",
        tool="windows.disk",
    )

    assert verdict.verdict == JDERuntimeVerdictType.DENY
    assert verdict.is_blocked
    assert not verdict.can_proceed_to_execution


def test_active_mode_is_protected_against_accidental_activation():
    """ACTIVE no debe activarse en Fase 1; si se solicita vía variable de entorno o set_mode, se degrada a CONTROLLED."""
    os.environ["JDE_RUNTIME_MODE"] = "ACTIVE"
    binding = JDERuntimeBinding()
    assert binding.current_mode == JDERuntimeMode.CONTROLLED

    # Intento explícito de cambio a ACTIVE
    ok, msg = binding.set_mode(JDERuntimeMode.ACTIVE)
    assert not ok
    assert "Fase 1" in msg
    assert binding.current_mode == JDERuntimeMode.CONTROLLED


def test_invalid_mode_falls_back_to_controlled():
    """Cualquier modo inválido o desconocido debe caer de forma segura en CONTROLLED."""
    binding = JDERuntimeBinding(mode="UNKNOWN_CORRUPT_MODE")
    assert binding.current_mode == JDERuntimeMode.CONTROLLED

    binding_none = JDERuntimeBinding(mode=None)
    assert binding_none.current_mode == JDERuntimeMode.CONTROLLED
