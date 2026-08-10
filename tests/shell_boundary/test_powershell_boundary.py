"""Pruebas del PowerShellExecutionBoundary (Subetapa 07.3)."""

from __future__ import annotations

from core.powershell_boundary import PowerShellExecutionBoundary


def test_powershell_boundary_enforces_mandatory_flags() -> None:
    boundary = PowerShellExecutionBoundary()
    inv = boundary.validate_and_build("powershell.exe", ["Get-Process"], "req-101")

    assert inv.is_valid is True
    assert "-NoProfile" in inv.mandatory_flags
    assert "-NonInteractive" in inv.mandatory_flags
    assert inv.arguments == ("Get-Process",)


def test_powershell_boundary_rejects_bypass_flags() -> None:
    boundary = PowerShellExecutionBoundary()

    bypass_inputs = [
        ["-EncodedCommand", "aWV4KGFyZ3Mp"],
        ["-ExecutionPolicy", "Bypass"],
        ["-ExecutionPolicy", "Unrestricted"],
        ["-Command", "Get-Process"],
        ["-c", "Get-Service"],
    ]

    for args in bypass_inputs:
        inv = boundary.validate_and_build("powershell.exe", args, "req-102")
        assert inv.is_valid is False
        assert "bypass" in inv.rejection_reason.lower() or "prohibida" in inv.rejection_reason.lower()
