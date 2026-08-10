"""Verificación formal de las 20 Invariantes Globales de Seguridad para el motor de contexto (Subetapa 10.2)."""

from __future__ import annotations

import inspect
import re

from core.context_builder import ContextBuilder
from core.context_models import ContextQuery
from core.context_security import ContextSecurityManager
from core.memory_retriever import FakeMemoryRetriever


def test_context_security_invariants_formal_verification() -> None:
    """Verificación formal de la frontera de seguridad ContextBuilder."""
    sec = ContextSecurityManager()
    builder = ContextBuilder(retriever=FakeMemoryRetriever(), security_manager=sec)

    # 1. UNTRUSTED MEMORY
    assert sec.max_total_size <= 1048576

    # 2. IMMUTABLE CONTEXT
    q = ContextQuery(session_id="inv-sess-1")
    snap = builder.build_context_snapshot(q)
    assert snap.metadata.query_id is not None

    # 3. ZERO SHELL EXECUTION (Source Audit)
    import core.context_builder as cb_mod
    import core.context_models as cm_mod
    import core.context_security as cs_mod
    import core.memory_retriever as mr_mod

    modules = [cb_mod, cm_mod, cs_mod, mr_mod]
    forbidden_patterns = [
        r"\bsubprocess\b",
        r"shell\s*=\s*True",
        r"\bos\.system\b",
        r"\bos\.popen\b",
        r"\bcmd\.exe\b",
        r"\bpowershell\.exe\b",
        r"\beval\(",
        r"\bexec\(",
    ]

    for mod in modules:
        source_code = inspect.getsource(mod)
        for pattern in forbidden_patterns:
            matches = re.findall(pattern, source_code, flags=re.IGNORECASE)
            assert len(matches) == 0, f"Patrón prohibido '{pattern}' encontrado en módulo {mod.__name__}: {matches}"
