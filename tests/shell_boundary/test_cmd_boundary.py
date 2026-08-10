"""Pruebas del CMDExecutionBoundary (Subetapa 07.3)."""

from __future__ import annotations

from core.cmd_boundary import CMDExecutionBoundary


def test_cmd_boundary_rejects_forbidden_flags() -> None:
    boundary = CMDExecutionBoundary()

    forbidden_inputs = [
        ["/c", "dir"],
        ["/k", "echo hello"],
        ["/s", "/c", "dir"],
    ]

    for args in forbidden_inputs:
        inv = boundary.validate_and_build("cmd.exe", args, "req-201")
        assert inv.is_valid is False
        assert "/c" in inv.rejection_reason or "prohibidas" in inv.rejection_reason.lower()


def test_cmd_boundary_rejects_operators_and_nested_shells() -> None:
    boundary = CMDExecutionBoundary()

    malicious_inputs = [
        ["dir", "&", "whoami"],
        ["dir", "&&", "calc"],
        ["dir", "|", "grep"],
        ["dir", ">", "out.txt"],
        ["powershell.exe"],
    ]

    for args in malicious_inputs:
        inv = boundary.validate_and_build("cmd.exe", args, "req-202")
        assert inv.is_valid is False
        assert "Rechazado" in inv.rejection_reason
