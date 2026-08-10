"""Pruebas de fuzzing controlado para CommandPolicyManager (Subetapa 07.1)."""

from __future__ import annotations

from core.command_policy import CommandPolicyManager
from core.permission_manager import PermissionDecision


def test_controlled_command_policy_fuzzing() -> None:
    mgr = CommandPolicyManager()

    fuzz_payloads = [
        ("", []),
        ("   ", ["arg1"]),
        ("git\x00", ["status"]),
        ("git", ["status\x00"]),
        ("echo", ["a" * 2000]),  # Long argument
        ("echo", ["arg"] * 100),  # Massive argument list
        ("git", ["&& whoami"]),
        ("powershell.exe", ["-command", "dir"]),
    ]

    for exe, args in fuzz_payloads:
        res = mgr.evaluate_command(exe, args)
        assert res.decision == PermissionDecision.DENY
