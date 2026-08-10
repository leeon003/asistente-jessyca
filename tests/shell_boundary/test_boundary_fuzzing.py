"""Pruebas de fuzzing controlado para fronteras de shell (Subetapa 07.3)."""

from __future__ import annotations

from core.cmd_boundary import CMDExecutionBoundary
from core.powershell_boundary import PowerShellExecutionBoundary


def test_controlled_shell_boundary_fuzzing() -> None:
    ps_b = PowerShellExecutionBoundary()
    cmd_b = CMDExecutionBoundary()

    ps_fuzz = [
        ["-EncodedCommand", "aWV4"],
        ["-ExecutionPolicy", "Bypass"],
        ["Invoke-Expression", "calc"],
        ["a" * 3000],  # Long argument
    ]

    for args in ps_fuzz:
        inv = ps_b.validate_and_build("powershell.exe", args, "fuzz-req")
        assert inv.is_valid is False

    cmd_fuzz = [
        ["/c", "dir"],
        ["dir", "&", "calc"],
        ["a" * 3000],
    ]

    for args in cmd_fuzz:
        inv = cmd_b.validate_and_build("cmd.exe", args, "fuzz-req")
        assert inv.is_valid is False
