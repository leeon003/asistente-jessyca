"""Pruebas de seguridad adversariales y falsos positivos (Subetapa 07.5)."""

from __future__ import annotations

from core.command_output import SecretRedactor


def test_false_positive_preservation() -> None:
    raw = "Password policy is enabled on system. Token count: 10."
    sanitized, count = SecretRedactor.redact(raw)

    # No debe redactar indiscriminadamente palabras informativas sin valor asignado
    assert "Password policy is enabled" in sanitized
    assert count == 0


def test_redaction_real_secrets_with_assignments() -> None:
    raw = "Password policy enabled. Current password: 'mySecretPassword123'"
    sanitized, count = SecretRedactor.redact(raw)

    assert "mySecretPassword123" not in sanitized
    assert count >= 1
