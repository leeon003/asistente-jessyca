"""Pruebas de binding criptográfico de autorización (Subetapa 07.3)."""

from __future__ import annotations

from core.powershell_boundary import PowerShellExecutionBoundary


def test_powershell_fingerprint_generation_and_integrity() -> None:
    boundary = PowerShellExecutionBoundary()

    inv1 = boundary.validate_and_build("powershell.exe", ["Get-Process"], "req-401")
    inv2 = boundary.validate_and_build("powershell.exe", ["Get-Process"], "req-401")

    # Mismos parámetros producen exactamente el mismo fingerprint
    assert inv1.action_fingerprint == inv2.action_fingerprint
    assert len(inv1.action_fingerprint) == 64  # SHA-256 hex length

    # Alterar el request_id produce un fingerprint distinto
    inv3 = boundary.validate_and_build("powershell.exe", ["Get-Process"], "req-402")
    assert inv1.action_fingerprint != inv3.action_fingerprint
