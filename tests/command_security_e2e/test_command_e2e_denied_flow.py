"""Prueba End-to-End del flujo denegado de comandos no autorizados (Subetapa 07.6)."""

from __future__ import annotations

from core.command_policy import CommandPolicyManager
from core.permission_manager import PermissionDecision


def test_e2e_denied_unregistered_command() -> None:
    policy_mgr = CommandPolicyManager()
    raw_input = "malicious_tool.exe --run"

    eval_result = policy_mgr.evaluate_command(raw_input, "e2e-req-102")

    assert eval_result.allowed is False
    assert eval_result.decision == PermissionDecision.DENY
    assert "no autorizado" in eval_result.reason.lower() or "desconocido" in eval_result.reason.lower()
