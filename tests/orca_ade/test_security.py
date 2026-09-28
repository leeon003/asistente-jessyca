"""Tests de Seguridad y Batería Adversaria: ORCA + ADE (Fase 1)."""

from __future__ import annotations

import pytest

from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import OrcaAdeMode, ProposalActionType
from core.security import RiskLevel


class TestOrcaAdeSecurity:
    """Verifica la inmunidad ante inyecciones, fuga de secretos y path traversal."""

    def test_secret_redaction_comprehensive(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        raw_text = (
            "Connecting with password='Secret123!' and token Bearer abcdef1234567890 "
            "sk-abcdefghijklmnopqrstuvwxyz123456 and ghp_1234567890abcdefghij1234567890 "
            "postgres://user:superpass@localhost:5432/db"
        )
        redacted = adapter.redact_secrets(raw_text)

        assert "Secret123!" not in redacted
        assert "abcdef1234567890" not in redacted
        assert "sk-abcdefgh" not in redacted
        assert "ghp_123456" not in redacted
        assert "superpass" not in redacted
        assert "[REDACTED" in redacted

    @pytest.mark.parametrize(
        "malicious_path",
        [
            "../../secret.txt",
            "..\\..\\config.json",
            "%2e%2e%2fenv",
            "foo/\x00/bar",
            "C:\\Windows\\System32\\cmd.exe",
            "/etc/passwd",
        ],
    )
    def test_path_traversal_rejection(self, malicious_path: str) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        with pytest.raises(ValueError, match="(traversal|forbidden|Null byte|escapes)"):
            adapter.validate_and_confine_path(malicious_path)

    def test_dangerous_commands_blocked_even_with_allow_override(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        proposal = adapter.create_proposal(
            capability="worktree_isolation",
            action_type=ProposalActionType.RUN_TESTS,
            title="Dangerous task",
            description="Testing command filter",
            proposed_commands=["rm -rf /", "shutdown /s"],
            estimated_risk=RiskLevel.CRITICAL,
        )
        # Incluso si un llamador intenta simular ALLOW, la propuesta insegura se bloquea
        result = adapter.evaluate_proposal(proposal, jde_decision_override="ALLOW")
        assert result.status == "DENIED"
        assert result.jde_decision == "DENY"
        assert len(result.errors) > 0
