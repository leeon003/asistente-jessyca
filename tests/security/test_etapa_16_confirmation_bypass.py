"""Etapa 16.0 — Vector 11: Confirmation Bypass Audit.

Verifica que ConfirmationManager resiste:
- M-06: Auto-APPROVED cuando provider=None
- Replay attacks (C-02 relacionado)
- Fingerprint mismatch detection
- TTL expiration enforcement
- Consumo único de confirmación
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.confirmation import (
    ConfirmationManager,
    ConfirmationStatus,
    MockConfirmationProvider,
    compute_action_fingerprint,
)


class TestConfirmationAutoApproveM06:
    """AUDIT M-06: Auto-APPROVED cuando no se pasa provider."""

    def test_no_provider_uses_mock_approved_by_default(self) -> None:
        """M-06 AUDIT: submit_request() sin provider debe aplicar Fail-Safe DENY (REJECTED)."""
        manager = ConfirmationManager()
        req = manager.create_request(
            tool_name="dangerous.operation",
            operation="delete",
            parameters={"path": "C:/important/data"},
            reason="Test M-06 auto-approve risk",
        )

        # Sin pasar provider — el fallback de seguridad es REJECTED
        result = manager.submit_request(req)  # Sin provider
        assert str(result.status).lower() == "rejected", (
            "Fail-Safe DENY: submit_request() sin provider explícito debe resultar en estado REJECTED."
        )

    def test_with_explicit_reject_provider_is_rejected(self) -> None:
        """Con provider REJECTED, la confirmación debe ser rechazada."""
        manager = ConfirmationManager()
        req = manager.create_request(
            tool_name="test.tool",
            operation="execute",
            parameters={},
        )
        result = manager.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.REJECTED))
        assert str(result.status).lower() == "rejected", (
            "Provider REJECTED debe resultar en confirmación rechazada."
        )

    def test_with_explicit_approve_provider_is_approved(self) -> None:
        """Con provider APPROVED, la confirmación debe ser aprobada."""
        manager = ConfirmationManager()
        req = manager.create_request(
            tool_name="test.tool",
            operation="execute",
            parameters={},
        )
        result = manager.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))
        assert str(result.status).lower() == "approved"


class TestReplayAttackPrevention:
    """Verifica que el sistema resiste replay attacks en confirmaciones."""

    def test_consume_twice_blocked(self) -> None:
        """Una confirmación aprobada sólo puede ser consumida una vez."""
        manager = ConfirmationManager()
        req = manager.create_request(
            tool_name="system.change_transaction",
            operation="execute",
            parameters={"res": "test_resource"},
        )
        manager.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

        # Primer consumo — exitoso
        first = manager.consume_confirmation(
            req.request_id, "system.change_transaction", "execute", {"res": "test_resource"}
        )
        assert first is True

        # Segundo consumo — DEBE ser rechazado (replay attack)
        second = manager.consume_confirmation(
            req.request_id, "system.change_transaction", "execute", {"res": "test_resource"}
        )
        assert second is False, (
            "[AUDIT] Replay attack: confirmación consumida dos veces. "
            "El mecanismo de consumo único falló."
        )

    def test_fingerprint_mismatch_blocked(self) -> None:
        """Consumir con parámetros distintos (fingerprint distinto) debe fallar."""
        manager = ConfirmationManager()
        req = manager.create_request(
            tool_name="system.change_transaction",
            operation="execute",
            parameters={"resource": "safe_resource"},
        )
        manager.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

        # Intentar consumir con parámetros diferentes (fingerprint diferente)
        result = manager.consume_confirmation(
            req.request_id,
            "system.change_transaction",
            "execute",
            {"resource": "DIFFERENT_MALICIOUS_RESOURCE"},  # Parámetros distintos
        )
        assert result is False, (
            "[AUDIT] Fingerprint mismatch no fue detectado. "
            "Confirmación consumida con parámetros distintos a los originales."
        )

    def test_session_mismatch_blocked(self) -> None:
        """Consumir confirmación desde session_id diferente debe fallar."""
        manager = ConfirmationManager()
        req = manager.create_request(
            tool_name="tool.x",
            operation="execute",
            parameters={},
            session_id="session-A",
        )
        manager.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

        result = manager.consume_confirmation(
            req.request_id, "tool.x", "execute", {}, session_id="session-EVIL"
        )
        assert result is False, (
            "[AUDIT] Session mismatch no fue detectado en consume_confirmation()."
        )


class TestConfirmationTTLEnforcement:
    """Verifica expiración correcta de confirmaciones."""

    def test_expired_confirmation_returns_none_on_get(self) -> None:
        """Confirmación expirada no debe ser retornada por get_pending_request()."""
        manager = ConfirmationManager()
        req = manager.create_request(
            tool_name="tool.expiry",
            operation="execute",
            parameters={},
            ttl_seconds=60,
        )

        # Forzar expiración
        req.expires_at = datetime.now(UTC) - timedelta(seconds=1)

        result = manager.get_pending_request(req.request_id)
        assert result is None, (
            "[AUDIT] get_pending_request() retornó una confirmación expirada."
        )

    def test_expired_confirmation_cannot_be_consumed(self) -> None:
        """Confirmación aprobada pero expirada no puede ser consumida."""
        manager = ConfirmationManager()
        req = manager.create_request(
            tool_name="tool.expiry",
            operation="execute",
            parameters={"key": "value"},
            ttl_seconds=60,
        )
        manager.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

        # Forzar expiración después de aprobación
        req.expires_at = datetime.now(UTC) - timedelta(seconds=1)

        result = manager.consume_confirmation(
            req.request_id, "tool.expiry", "execute", {"key": "value"}
        )
        assert result is False, (
            "[AUDIT] Confirmación aprobada pero expirada fue consumida exitosamente."
        )

    def test_pending_request_with_valid_ttl_returned(self) -> None:
        """Confirmación no expirada debe ser retornada correctamente."""
        manager = ConfirmationManager()
        req = manager.create_request(
            tool_name="tool.valid",
            operation="execute",
            parameters={},
            ttl_seconds=300,
        )

        result = manager.get_pending_request(req.request_id)
        assert result is not None
        assert result.request_id == req.request_id


class TestFingerprintIntegrity:
    """Verifica integridad del ActionFingerprint SHA-256."""

    def test_same_params_same_fingerprint(self) -> None:
        """Los mismos parámetros deben producir el mismo fingerprint."""
        fp1 = compute_action_fingerprint("tool.x", "execute", {"key": "value"})
        fp2 = compute_action_fingerprint("tool.x", "execute", {"key": "value"})
        assert fp1 == fp2

    def test_different_params_different_fingerprint(self) -> None:
        """Parámetros distintos deben producir fingerprints distintos."""
        fp1 = compute_action_fingerprint("tool.x", "execute", {"key": "value_a"})
        fp2 = compute_action_fingerprint("tool.x", "execute", {"key": "value_b"})
        assert fp1 != fp2

    def test_fingerprint_is_sha256(self) -> None:
        """El fingerprint debe ser un hash SHA-256 de 64 caracteres hex."""
        fp = compute_action_fingerprint("tool.x", "execute", {})
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)
