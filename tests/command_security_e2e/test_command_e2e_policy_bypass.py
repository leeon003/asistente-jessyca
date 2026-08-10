"""Pruebas de evación de la política de lista blanca (Subetapa 07.6)."""

from __future__ import annotations

from core.command_policy import CommandPolicyManager


def test_e2e_policy_rejects_partial_name_matches_and_spoofing() -> None:
    policy_mgr = CommandPolicyManager()

    spoofed_inputs = [
        "git-malicious.exe status",
        "git_fake.exe log",
        "fake_git.exe",
        "git.cmd status",
    ]

    for raw in spoofed_inputs:
        res = policy_mgr.evaluate_command(raw, "policy-bypass-req")
        assert res.allowed is False
