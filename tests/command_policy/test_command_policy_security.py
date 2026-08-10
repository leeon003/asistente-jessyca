"""Pruebas de seguridad adversariales de políticas de comandos (Subetapa 07.1)."""

from __future__ import annotations

from core.command_policy import CommandPolicyManager, ShellMetacharacterDetector
from core.permission_manager import PermissionDecision


def test_shell_metacharacter_detection() -> None:
    assert ShellMetacharacterDetector.contains_dangerous_metacharacters("echo hello && calc.exe") is True
    assert ShellMetacharacterDetector.contains_dangerous_metacharacters("dir | grep test") is True
    assert ShellMetacharacterDetector.contains_dangerous_metacharacters("git status; rm -rf /") is True
    assert ShellMetacharacterDetector.contains_dangerous_metacharacters("echo $(whoami)") is True
    assert ShellMetacharacterDetector.contains_dangerous_metacharacters("git status") is False


def test_metacharacter_injection_rejection() -> None:
    mgr = CommandPolicyManager()

    malicious_inputs = [
        ("echo", ["hello && calc.exe"]),
        ("dir", ["| dir"]),
        ("git", ["status; whoami"]),
        ("echo", ["`whoami`"]),
        ("echo", ["$(whoami)"]),
        ("git", ["> output.txt"]),
        ("git", ["< input.txt"]),
    ]

    for exec_name, args in malicious_inputs:
        res = mgr.evaluate_command(exec_name, args)
        assert res.decision == PermissionDecision.DENY
        assert "Rechazado" in res.reason or "operadores" in res.reason


def test_restricted_executables_rejection() -> None:
    mgr = CommandPolicyManager()

    restricted = ["powershell.exe", "pwsh.exe", "cmd.exe", "powershell", "cmd"]

    for exe in restricted:
        res = mgr.evaluate_command(exe)
        assert res.decision == PermissionDecision.DENY
        assert "restringido" in res.reason or "FAIL-SAFE DENY" in res.reason
