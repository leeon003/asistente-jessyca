"""Pruebas de fuzzing para la frontera de seguridad de construcción de contexto (Subetapa 10.2)."""

from __future__ import annotations

import pytest

from core.context_models import ContextQuery
from core.context_security import ContextSecurityError, ContextSecurityManager


def test_controlled_context_fuzzing() -> None:
    sec = ContextSecurityManager()

    # SessionId malformados
    with pytest.raises((ContextSecurityError, ValueError)):
        sec.validate_query(ContextQuery(session_id=""))


    with pytest.raises(ContextSecurityError):
        sec.validate_query(ContextQuery(session_id="sid_\x00_null"))

    with pytest.raises(ContextSecurityError):
        sec.validate_query(ContextQuery(session_id="a" * 200))

    # Valores negativos o tipos incorrectos
    with pytest.raises(ContextSecurityError):
        sec.validate_query(ContextQuery(session_id="s1", max_messages=-1))

    with pytest.raises(ContextSecurityError):
        sec.validate_query(ContextQuery(session_id="s1", max_total_size=0))
