"""Pruebas de fuzzing controlado para la frontera de seguridad de sesión (Subetapa 10.1)."""

from __future__ import annotations

import pytest

from core.session_security import (
    SessionSecurityError,
    SessionSecurityManager,
)


def test_controlled_session_fuzzing() -> None:
    sec = SessionSecurityManager()

    # SessionId malformados
    with pytest.raises(SessionSecurityError):
        sec.validate_session_id("")

    with pytest.raises(SessionSecurityError):
        sec.validate_session_id("sid_with_\x00_null")

    with pytest.raises(SessionSecurityError):
        sec.validate_session_id("a" * 200)

    # Facts malformados
    with pytest.raises(SessionSecurityError):
        sec.validate_fact("", "value", 1.0)

    with pytest.raises(SessionSecurityError):
        sec.validate_fact("key", "value", 1.5)

    with pytest.raises(SessionSecurityError):
        sec.validate_fact("key", "value", -0.1)

    # Confianza con NaN/Infinity
    with pytest.raises(SessionSecurityError):
        sec.validate_fact("key", "value", float("nan"))
