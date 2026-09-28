"""Pruebas unitarias para JDE Runtime Binding (Fase 1).

Verifica:
- Inicialización y singleton get_jde_runtime_binding / reset_jde_runtime_binding.
- Veredictos ALLOW, DENY, REQUIRE_REVIEW.
- Contrato determinista con fingerprint SHA-256.
- Recibo estructurado de acción.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

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
    get_jde_runtime_binding,
    reset_jde_runtime_binding,
)
from core.jde.states import DecisionState


@pytest.fixture(autouse=True)
def clean_runtime_binding_env():
    """Limpia el singleton y variables de entorno antes y después de cada test."""
    reset_jde_runtime_binding()
    orig_env = os.environ.get("JDE_RUNTIME_MODE")
    orig_ks = os.environ.get("JDE_KILL_SWITCH")
    if "JDE_RUNTIME_MODE" in os.environ:
        del os.environ["JDE_RUNTIME_MODE"]
    if "JDE_KILL_SWITCH" in os.environ:
        del os.environ["JDE_KILL_SWITCH"]
    yield
    reset_jde_runtime_binding()
    if orig_env is not None:
        os.environ["JDE_RUNTIME_MODE"] = orig_env
    elif "JDE_RUNTIME_MODE" in os.environ:
        del os.environ["JDE_RUNTIME_MODE"]
    if orig_ks is not None:
        os.environ["JDE_KILL_SWITCH"] = orig_ks
    elif "JDE_KILL_SWITCH" in os.environ:
        del os.environ["JDE_KILL_SWITCH"]


def test_runtime_binding_singleton():
    """Verifica que get_jde_runtime_binding devuelva una instancia singleton consistente."""
    binding1 = get_jde_runtime_binding()
    binding2 = get_jde_runtime_binding()
    assert binding1 is binding2
    assert binding1.current_mode == JDERuntimeMode.CONTROLLED

    reset_jde_runtime_binding()
    binding3 = get_jde_runtime_binding()
    assert binding3 is not binding1


def test_runtime_binding_default_mode_is_controlled():
    """Verifica que el modo inicial obligatorio sea estrictamente CONTROLLED."""
    binding = JDERuntimeBinding()
    assert binding.current_mode == JDERuntimeMode.CONTROLLED


def test_evaluate_allow():
    """Verifica veredicto ALLOW cuando AuthorityGate autoriza la acción."""
    mock_gate = MagicMock()
    mock_gate.is_kill_switch_active = False
    mock_gate.current_mode = AuthorityMode.FULL
    mock_gate.evaluate_authority.return_value = AuthorityGateResult(
        mode=AuthorityMode.FULL,
        decision=AuthorityDecision.ALLOW,
        can_execute=True,
        can_block=True,
        risk_tier=ActionRiskTier.LOW,
        action="inspect_status",
        tool="system.info",
        is_authorized=True,
        requires_human_confirmation=False,
        reason="Acción de bajo riesgo autorizada.",
    )

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=mock_gate)
    verdict = binding.evaluate(
        intent="get_system_info",
        action="inspect_status",
        tool="system.info",
        parameters={"detail": "summary"},
    )

    assert verdict.verdict == JDERuntimeVerdictType.ALLOW
    assert not verdict.is_blocked
    assert not verdict.requires_human_confirmation
    assert verdict.can_proceed_to_execution
    assert verdict.contract is not None
    assert verdict.contract.decision_status == DecisionState.AUTHORIZED
    assert len(verdict.contract.fingerprint) == 64  # SHA-256


def test_evaluate_deny():
    """Verifica veredicto DENY cuando AuthorityGate deniega la acción."""
    mock_gate = MagicMock()
    mock_gate.is_kill_switch_active = False
    mock_gate.current_mode = AuthorityMode.CONTROLLED
    mock_gate.evaluate_authority.return_value = AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.DENY,
        can_execute=False,
        can_block=True,
        risk_tier=ActionRiskTier.HIGH,
        action="delete_all",
        tool="windows.files",
        is_authorized=False,
        requires_human_confirmation=False,
        reason="Acción destructiva no permitida.",
    )

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=mock_gate)
    verdict = binding.evaluate(
        intent="delete_everything",
        action="delete_all",
        tool="windows.files",
        parameters={"path": "C:\\Windows"},
    )

    assert verdict.verdict == JDERuntimeVerdictType.DENY
    assert verdict.is_blocked
    assert not verdict.can_proceed_to_execution
    assert "Acción destructiva no permitida" in verdict.reason
    assert verdict.receipt is not None
    assert verdict.receipt.final_status == DecisionState.DENIED


def test_evaluate_require_review_unconfirmed():
    """Verifica veredicto REQUIRE_REVIEW cuando la acción requiere confirmación y aún no ha sido confirmada."""
    mock_gate = MagicMock()
    mock_gate.is_kill_switch_active = False
    mock_gate.current_mode = AuthorityMode.CONTROLLED
    mock_gate.evaluate_authority.return_value = AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.REQUIRE_VERIFICATION,
        can_execute=False,
        can_block=True,
        risk_tier=ActionRiskTier.HIGH,
        action="kill_process",
        tool="windows.apps",
        is_authorized=False,
        requires_human_confirmation=True,
        reason="Cierre forzado requiere confirmación humana.",
    )

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=mock_gate)
    verdict = binding.evaluate(
        intent="close_notepad",
        action="kill_process",
        tool="windows.apps",
        parameters={"app_name": "notepad"},
        user_confirmed=False,
    )

    assert verdict.verdict == JDERuntimeVerdictType.REQUIRE_REVIEW
    assert verdict.is_blocked
    assert verdict.requires_human_confirmation
    assert not verdict.can_proceed_to_execution
    assert verdict.contract is not None
    assert verdict.contract.decision_status == DecisionState.REQUIRES_CONFIRMATION


def test_evaluate_require_review_confirmed():
    """Verifica que al confirmar explícitamente, REQUIRE_REVIEW pase a ALLOW."""
    mock_gate = MagicMock()
    mock_gate.is_kill_switch_active = False
    mock_gate.current_mode = AuthorityMode.CONTROLLED
    mock_gate.evaluate_authority.return_value = AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.REQUIRE_VERIFICATION,
        can_execute=False,
        can_block=True,
        risk_tier=ActionRiskTier.HIGH,
        action="kill_process",
        tool="windows.apps",
        is_authorized=False,
        requires_human_confirmation=True,
        reason="Cierre forzado requiere confirmación.",
    )

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=mock_gate)
    verdict = binding.evaluate(
        intent="close_notepad",
        action="kill_process",
        tool="windows.apps",
        parameters={"app_name": "notepad"},
        user_confirmed=True,
    )

    assert verdict.verdict == JDERuntimeVerdictType.ALLOW
    assert not verdict.is_blocked
    assert verdict.can_proceed_to_execution
