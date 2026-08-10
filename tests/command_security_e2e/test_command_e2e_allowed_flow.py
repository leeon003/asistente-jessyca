"""Prueba End-to-End del flujo permitido de ejecución de comandos (Subetapa 07.6)."""

from __future__ import annotations

from core.command_audit import CommandAuditManager
from core.command_output import CommandOutputSanitizer
from core.command_parser import SecureCommandParser
from core.command_policy import CommandPolicyManager
from core.powershell_boundary import PowerShellExecutionBoundary


def test_e2e_allowed_command_flow() -> None:
    policy_mgr = CommandPolicyManager()
    parser = SecureCommandParser()
    ps_boundary = PowerShellExecutionBoundary()
    sanitizer = CommandOutputSanitizer()
    audit_mgr = CommandAuditManager()

    raw_input = "git status"
    req_id = "e2e-req-101"

    # 1. Evaluación de política
    policy_eval = policy_mgr.evaluate_command(raw_input, req_id)
    assert policy_eval.allowed is True

    # 2. Parseo seguro de comando
    parsed_cmd = parser.parse(raw_input, req_id)
    assert parsed_cmd.is_valid is True
    assert parsed_cmd.executable == "git"

    # 3. Validación por frontera de shell (PowerShell)
    ps_inv = ps_boundary.validate_and_build("powershell.exe", parsed_cmd.arguments, req_id)
    assert ps_inv.is_valid is True

    # 4. Sanitización de la salida
    sanitized_out = sanitizer.sanitize("On branch main. Nothing to commit.", "", req_id)
    assert sanitized_out.is_sanitized is True

    # 5. Registro de auditoría
    audit_event = audit_mgr.log_command_completion(
        request_id=req_id,
        tool_name="windows.shell",
        operation="execute_command",
        shell_type="powershell",
        executable="powershell.exe",
        fingerprint=ps_inv.action_fingerprint,
        risk_level=policy_eval.risk_level,
        decision=policy_eval.decision,
        duration_ms=15.0,
    )

    assert audit_event.request_id == req_id
    assert audit_event.normalized_executable == "powershell.exe"
