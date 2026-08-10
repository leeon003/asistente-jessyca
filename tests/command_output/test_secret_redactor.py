"""Pruebas del SecretRedactor (Subetapa 07.5)."""

from __future__ import annotations

from core.command_output import SecretRedactor


def test_secret_redactor_passwords_and_keys() -> None:
    raw_input = "db_connection password=supersecret123; api_key=sk_test_999;"
    sanitized, count = SecretRedactor.redact(raw_input)

    assert count >= 2
    assert "supersecret123" not in sanitized
    assert "sk_test_999" not in sanitized
    assert "[REDACTED]" in sanitized


def test_secret_redactor_bearer_and_jwt() -> None:
    jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    raw_input = f"Authorization: Bearer {jwt_token}"

    sanitized, count = SecretRedactor.redact(raw_input)

    assert count >= 1
    assert jwt_token not in sanitized
    assert "[REDACTED" in sanitized


def test_secret_redactor_private_keys() -> None:
    raw_input = """
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC
-----END PRIVATE KEY-----
"""
    sanitized, count = SecretRedactor.redact(raw_input)

    assert count == 1
    assert "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC" not in sanitized
    assert "[REDACTED_PRIVATE_KEY]" in sanitized


def test_secret_redactor_connection_strings() -> None:
    raw = "Server=myServerAddress;Database=myDataBase;User Id=myUsername;Password=myPassword;"
    sanitized, count = SecretRedactor.redact(raw)

    assert count >= 1
    assert "myPassword" not in sanitized
