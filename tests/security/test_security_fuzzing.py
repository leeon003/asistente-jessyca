"""Pruebas de fuzzing controlado para validación de entradas e inmunidad a tipos confusos (Subetapa 04.7)."""

from __future__ import annotations

import pytest

from core.audit_logger import sanitize_audit_data
from core.confirmation import compute_action_fingerprint
from core.risk_engine import RiskEngine
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)
from core.security_policy import SecurityPolicyEvaluator, create_default_security_policy

fuzz_inputs = [
    "",
    "   ",
    "\0\a\b\t\n\r",
    "A" * 50000,
    "🔥🚀💻🛡️⚡",
    "'; DROP TABLE users; --",
    "<script>alert(1)</script>",
    "../../../../../../Windows/System32",
    "HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet",
]


def test_fuzzing_risk_engine() -> None:
    engine = RiskEngine()
    for inp in fuzz_inputs:
        ctx = SecurityContext(user="fuzzer", tool_name="fuzz_tool", parameters={"arg": inp})
        meta = ToolSecurityMetadata(tool_name="fuzz_tool", risk_level=SecurityLevel.SAFE)
        req = SecurityRequest(context=ctx, metadata=meta, action=inp[:50] or "execute")

        assessment = engine.evaluate_risk(req)
        assert assessment is not None
        assert assessment.risk_level in (SecurityLevel.SAFE, SecurityLevel.WARNING, SecurityLevel.DANGEROUS, SecurityLevel.CRITICAL)


def test_fuzzing_action_fingerprint() -> None:
    for inp in fuzz_inputs:
        fp = compute_action_fingerprint(inp, inp[:20] or "op", {"key": inp})
        assert isinstance(fp, str)
        assert len(fp) == 64  # Hex SHA-256 len


def test_fuzzing_sanitizer() -> None:
    huge_dict = {f"key_{i}": "X" * 2000 for i in range(10)}
    huge_dict["password"] = "secret_pass"

    sanitized = sanitize_audit_data(huge_dict, max_str_len=50)
    assert sanitized["password"] == "[REDACTED]"
    assert "[TRUNCATED]" in sanitized["key_0"]


def test_fuzzing_policy_evaluator_unhandled_inputs() -> None:
    evaluator = SecurityPolicyEvaluator()
    policy = create_default_security_policy()

    for inp in fuzz_inputs:
        u_val = inp.strip() if inp and inp.strip() else "system"
        t_val = inp.strip() if inp and inp.strip() else "tool"
        ctx = SecurityContext(user=u_val, tool_name=t_val, parameters={"operation": inp})
        meta = ToolSecurityMetadata(tool_name=t_val, risk_level=SecurityLevel.SAFE)
        risk_eng = RiskEngine()

        try:
            assessment = risk_eng.evaluate_risk(ctx, {"operation": inp})
            decision = evaluator.evaluate_policy(ctx, meta, assessment, policy)
            assert decision is not None
        except Exception as e:
            pytest.fail(f"Fuzzing causó una excepción no controlada con input '{inp[:30]}': {e}")
