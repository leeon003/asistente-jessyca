"""Pruebas de la frontera de seguridad SessionSecurityManager (Subetapa 10.1)."""

from __future__ import annotations

import pytest

from core.session_models import SessionStatus
from core.session_security import (
    SessionLimitExceededError,
    SessionSecurityError,
    SessionSecurityManager,
)


def test_session_security_manager_validates_session_id() -> None:
    sec = SessionSecurityManager()

    valid_sid = sec.validate_session_id("valid-uuid-123")
    assert str(valid_sid) == "valid-uuid-123"

    with pytest.raises(SessionSecurityError):
        sec.validate_session_id("")

    with pytest.raises(SessionSecurityError):
        sec.validate_session_id("invalid\x00session")


def test_session_security_manager_blocks_terminal_state_transitions() -> None:
    sec = SessionSecurityManager()

    # Transición permitida
    sec.validate_status_transition(SessionStatus.ACTIVE, SessionStatus.PAUSED)

    # Transición denegada desde estado terminal
    with pytest.raises(SessionSecurityError):
        sec.validate_status_transition(SessionStatus.EMERGENCY_STOPPED, SessionStatus.ACTIVE)

    with pytest.raises(SessionSecurityError):
        sec.validate_status_transition(SessionStatus.CANCELLED, SessionStatus.ACTIVE)


def test_session_security_manager_sanitizes_text_and_redacts_secrets() -> None:
    sec = SessionSecurityManager()

    clean = sec.sanitize_text("usuario_normal\x00_texto")
    assert "\x00" not in clean

    # Verificación de redacción vía SecretRedactor
    redacted = sec.sanitize_text("mi clave es AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
