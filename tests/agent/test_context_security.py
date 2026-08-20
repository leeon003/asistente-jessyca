"""Pruebas de la frontera de seguridad ContextSecurityManager (Subetapa 10.2)."""

from __future__ import annotations

import pytest

from core.context_models import ContextQuery
from core.context_security import (
    ContextSecurityError,
    ContextSecurityManager,
)


def test_context_security_manager_validates_query() -> None:
    sec = ContextSecurityManager()

    valid_q = ContextQuery(session_id="valid-session-123")
    res = sec.validate_query(valid_q)
    assert res.session_id == "valid-session-123"

    # Recomendar o rechazar null bytes
    with pytest.raises(ContextSecurityError):
        sec.validate_query(ContextQuery(session_id="invalid\x00session"))

    # Rechazar cantidades negativas o tipos flotantes para enteros
    with pytest.raises(ContextSecurityError):
        sec.validate_query(ContextQuery(session_id="s1", max_messages=-5))  # type: ignore

    with pytest.raises(ContextSecurityError):
        sec.validate_query(ContextQuery(session_id="s1", max_messages=True))  # type: ignore


def test_context_security_manager_sanitizes_text_and_redacts_secrets() -> None:
    sec = ContextSecurityManager()

    clean = sec.sanitize_text("texto\x00_normal")
    assert "\x00" not in clean

    # Redacción de API Keys
    redacted = sec.sanitize_text("API Key = AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
