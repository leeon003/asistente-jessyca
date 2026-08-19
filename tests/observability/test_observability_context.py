"""Tests del ObservabilityContext — Etapa 17.0.

Verifica:
- Creación y propagación de IDs de correlación
- Derivación de contextos hijo
- ContextVar propagation (set/get/reset)
- run_with_context()
- get_or_create_context()
"""

from __future__ import annotations

import threading

import pytest

from core.observability.context import (
    ObservabilityContext,
    get_current_context,
    get_or_create_context,
    reset_context,
    run_with_context,
    set_current_context,
)


class TestObservabilityContext:
    """Tests de creación y campos del ObservabilityContext."""

    def test_create_generates_correlation_id(self) -> None:
        ctx = ObservabilityContext.create(session_id="sess-1", component="test")
        assert ctx.correlation_id
        assert len(ctx.correlation_id) == 36  # UUID v4

    def test_create_root_generates_session_id(self) -> None:
        ctx = ObservabilityContext.create_root(component="test")
        assert ctx.session_id
        assert len(ctx.session_id) == 36

    def test_create_accepts_explicit_correlation_id(self) -> None:
        ctx = ObservabilityContext.create(
            session_id="sess-1",
            component="test",
            correlation_id="my-fixed-id",
        )
        assert ctx.correlation_id == "my-fixed-id"

    def test_immutability(self) -> None:
        ctx = ObservabilityContext.create_root(component="test")
        with pytest.raises((AttributeError, TypeError)):
            ctx.correlation_id = "tampered"  # type: ignore[misc]

    def test_derive_inherits_parent_ids(self) -> None:
        parent = ObservabilityContext.create(
            session_id="sess-abc",
            component="executor",
            task_id="task-1",
        )
        child = parent.derive(component="boundary.registry", action_id="action-1")
        assert child.correlation_id == parent.correlation_id
        assert child.session_id == parent.session_id
        assert child.task_id == "task-1"      # heredado
        assert child.action_id == "action-1"  # sobreescrito
        assert child.component == "boundary.registry"

    def test_derive_preserves_plugin_id(self) -> None:
        parent = ObservabilityContext.create(
            session_id="sess-xyz",
            component="plugin",
            plugin_id="my-plugin-v1",
        )
        child = parent.derive(component="plugin.sandbox")
        assert child.plugin_id == "my-plugin-v1"

    def test_to_dict_contains_required_keys(self) -> None:
        ctx = ObservabilityContext.create(session_id="s", component="c")
        d = ctx.to_dict()
        for key in ("correlation_id", "session_id", "task_id", "action_id", "plugin_id", "component", "user_id"):
            assert key in d


class TestContextVarPropagation:
    """Tests de propagación por ContextVar."""

    def test_get_current_context_none_by_default(self) -> None:
        # Ejecutar en hilo nuevo para aislamiento
        result = []

        def check() -> None:
            result.append(get_current_context())

        t = threading.Thread(target=check)
        t.start()
        t.join()
        assert result[0] is None

    def test_set_and_get_current_context(self) -> None:
        ctx = ObservabilityContext.create(session_id="s", component="test")
        token = set_current_context(ctx)
        try:
            retrieved = get_current_context()
            assert retrieved is ctx
        finally:
            reset_context(token)

    def test_reset_restores_previous_context(self) -> None:
        ctx = ObservabilityContext.create(session_id="s1", component="test")
        token = set_current_context(ctx)
        reset_context(token)
        assert get_current_context() is None

    def test_run_with_context_sets_and_restores(self) -> None:
        ctx = ObservabilityContext.create(session_id="s", component="test")

        captured = []

        def work() -> None:
            captured.append(get_current_context())

        run_with_context(ctx, work)
        assert captured[0] is ctx
        # Después de run_with_context, el contexto debe estar restaurado
        assert get_current_context() is None

    def test_run_with_context_restores_on_exception(self) -> None:
        ctx = ObservabilityContext.create(session_id="s", component="test")

        with pytest.raises(ValueError, match="boom"):
            run_with_context(ctx, lambda: (_ for _ in ()).throw(ValueError("boom")))  # type: ignore[arg-type]

        assert get_current_context() is None

    def test_thread_isolation(self) -> None:
        """Contextos en hilos distintos son independientes."""
        ctx_main = ObservabilityContext.create(session_id="main", component="main")
        thread_ctx: list[ObservabilityContext | None] = []

        def thread_work() -> None:
            # Hilo secundario no tiene contexto activo
            thread_ctx.append(get_current_context())

        token = set_current_context(ctx_main)
        try:
            t = threading.Thread(target=thread_work)
            t.start()
            t.join()
        finally:
            reset_context(token)

        assert thread_ctx[0] is None  # hilo secundario no hereda contexto


class TestGetOrCreateContext:
    """Tests de get_or_create_context."""

    def test_creates_root_when_no_context_active(self) -> None:
        ctx = get_or_create_context(component="boundary.registry")
        assert ctx.component == "boundary.registry"
        assert ctx.correlation_id

    def test_derives_from_active_context(self) -> None:
        parent = ObservabilityContext.create(session_id="s", component="executor")
        token = set_current_context(parent)
        try:
            child = get_or_create_context(component="boundary.registry")
            assert child.correlation_id == parent.correlation_id
            assert child.session_id == parent.session_id
            assert child.component == "boundary.registry"
        finally:
            reset_context(token)
