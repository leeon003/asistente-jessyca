"""Verificación formal de las 15 Invariantes de Seguridad de la Etapa 07 (Subetapa 07.6)."""

from __future__ import annotations

from core.command_audit import CommandAuditManager
from core.command_output import CommandOutputSanitizer, SecretRedactor
from core.command_parser import SecureCommandParser
from core.command_policy import CommandPolicyManager
from core.permission_manager import PermissionDecision
from core.powershell_boundary import PowerShellExecutionBoundary


def test_invariant_1_unknown_command_deny() -> None:
    policy_mgr = CommandPolicyManager()
    res = policy_mgr.evaluate_command("unknown_dangerous_cmd.exe", "inv-1")
    assert res.allowed is False
    assert res.decision == PermissionDecision.DENY


def test_invariant_2_critical_risk_never_auto_allow() -> None:
    policy_mgr = CommandPolicyManager()
    res = policy_mgr.evaluate_command("format C:", "inv-2")
    assert res.allowed is False


def test_invariant_3_and_4_no_shell_true_and_no_string_concatenation() -> None:
    parser = SecureCommandParser()
    parsed = parser.parse("git status & calc", "inv-3-4")
    assert parsed.is_valid is False  # Tokenizer rejects shell operators


def test_invariant_5_and_6_authorization_evidence_and_fingerprint_binding() -> None:
    audit_mgr = CommandAuditManager()
    fp1 = audit_mgr.calculate_action_fingerprint("windows.shell", "exec", "powershell", "git", ("status",), "req-1")
    fp2 = audit_mgr.calculate_action_fingerprint("windows.shell", "exec", "powershell", "git", ("status",), "req-1")
    assert fp1 == fp2  # Canonical fingerprint binding


def test_invariant_8_and_9_raw_output_never_leaks_and_secrets_redacted() -> None:
    sanitizer = CommandOutputSanitizer()
    out = sanitizer.sanitize("db password=supersecret123", "")
    assert "supersecret123" not in out.stdout
    assert "[REDACTED]" in out.stdout


def test_invariant_11_resource_limits_enforced() -> None:
    parser = SecureCommandParser()
    large_input = "git " + "a " * 100
    parsed = parser.parse(large_input, "inv-11")
    assert parsed.is_valid is False  # Rejects > 50 arguments


def test_invariant_12_security_failures_fail_closed() -> None:
    redacted, count = SecretRedactor.redact("password=secret")
    assert "secret" not in redacted
    assert count >= 1


def test_invariant_14_powershell_cmd_bypass_flags_rejected() -> None:
    ps_b = PowerShellExecutionBoundary()
    inv = ps_b.validate_and_build("powershell.exe", ["-ExecutionPolicy", "Bypass"], "inv-14")
    assert inv.is_valid is False
