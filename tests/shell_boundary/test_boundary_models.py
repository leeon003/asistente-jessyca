"""Pruebas de los modelos inmutables de fronteras de shell (Subetapa 07.3)."""

from __future__ import annotations

import pytest

from core.cmd_boundary import CMDInvocation
from core.permission_manager import PermissionDecision
from core.powershell_boundary import ExecutionBoundaryDecision, PowerShellInvocation


def test_powershell_invocation_immutability() -> None:
    inv = PowerShellInvocation(
        executable="powershell.exe",
        mandatory_flags=("-NoProfile", "-NonInteractive"),
        arguments=("Get-Process",),
        action_fingerprint="abc123hash",
        request_id="req-1",
        is_valid=True,
    )

    assert inv.executable == "powershell.exe"
    assert inv.mandatory_flags == ("-NoProfile", "-NonInteractive")

    with pytest.raises(AttributeError):
        inv.is_valid = False  # type: ignore

    d = inv.to_dict()
    assert d["action_fingerprint"] == "abc123hash"


def test_cmd_invocation_and_decision_immutability() -> None:
    cmd = CMDInvocation(
        executable="cmd.exe",
        arguments=("dir",),
        action_fingerprint="def456hash",
        request_id="req-2",
        is_valid=True,
    )
    assert cmd.to_dict()["action_fingerprint"] == "def456hash"

    dec = ExecutionBoundaryDecision(
        allowed=True,
        reason="Autorizado",
        decision=PermissionDecision.ALLOW,
        shell_type="powershell",
    )
    assert dec.to_dict()["shell_type"] == "powershell"
