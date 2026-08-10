"""Pruebas de seguridad adversariales de fronteras de shell (Subetapa 07.3)."""

from __future__ import annotations

from core.powershell_boundary import PowerShellExecutionBoundary


def test_powershell_obfuscation_and_case_folding_rejection() -> None:
    boundary = PowerShellExecutionBoundary()

    obfuscated_inputs = [
        ["Invoke-Expression", "Get-Process"],
        ["iex", "Get-Process"],
        ["IeX", "Get-Service"],
        ["iEx", "Get-ChildItem"],
        ["INVOKE-EXPRESSION", "whoami"],
        ["Start-Process", "calc.exe"],
        ["New-Object", "Net.WebClient"],
        ["&", "{Get-Process}"],
    ]

    for args in obfuscated_inputs:
        inv = boundary.validate_and_build("powershell.exe", args, "req-301")
        assert inv.is_valid is False
        assert "obfuscación" in inv.rejection_reason.lower() or "dinámica" in inv.rejection_reason.lower()
