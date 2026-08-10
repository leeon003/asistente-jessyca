"""Pruebas de evasión de frontera de shell PowerShell y CMD (Subetapa 07.6)."""

from __future__ import annotations

from core.cmd_boundary import CMDExecutionBoundary
from core.powershell_boundary import PowerShellExecutionBoundary


def test_e2e_boundary_rejects_bypass_flags_and_obfuscation() -> None:
    ps_b = PowerShellExecutionBoundary()
    cmd_b = CMDExecutionBoundary()

    # PowerShell bypass attempts
    ps_res = ps_b.validate_and_build("powershell.exe", ["-EncodedCommand", "aWV4"], "bnd-1")
    assert ps_res.is_valid is False

    ps_res2 = ps_b.validate_and_build("powershell.exe", ["Invoke-Expression", "calc"], "bnd-2")
    assert ps_res2.is_valid is False

    # CMD bypass attempts
    cmd_res = cmd_b.validate_and_build("cmd.exe", ["/c", "whoami"], "bnd-3")
    assert cmd_res.is_valid is False

    cmd_res2 = cmd_b.validate_and_build("cmd.exe", ["dir", "&", "calc"], "bnd-4")
    assert cmd_res2.is_valid is False
