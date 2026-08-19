"""Tests del TraceManager — Etapa 17.0.

Verifica:
- start_span / end_span lifecycle
- Context manager 'with span():'
- Status OK / ERROR / CANCELLED
- Propagación de parent_span_id
- InMemoryTraceStore queries
- Sink registration y emisión
"""

from __future__ import annotations

import pytest

from core.observability.context import (
    ObservabilityContext,
    reset_context,
    set_current_context,
)
from core.observability.span_models import SpanStatus
from core.observability.trace_manager import InMemoryTraceStore, TraceManager


def _make_ctx(session: str = "sess-1", component: str = "test") -> ObservabilityContext:
    return ObservabilityContext.create(session_id=session, component=component)


class TestSpanLifecycle:
    """Tests del ciclo de vida de un span."""

    def test_start_span_returns_unfinished_span(self) -> None:
        mgr = TraceManager()
        ctx = _make_ctx()
        span = mgr.start_span("executor.execute", ctx=ctx)
        assert not span.is_finished
        assert span.name == "executor.execute"
        assert span.trace_id == ctx.correlation_id
        assert span.session_id == ctx.session_id

    def test_end_span_records_duration(self) -> None:
        mgr = TraceManager()
        ctx = _make_ctx()
        span = mgr.start_span("test.op", ctx=ctx)
        mgr.end_span(span, status=SpanStatus.OK)
        assert span.is_finished
        assert span.duration_ms is not None
        assert span.duration_ms >= 0.0
        assert span.status == SpanStatus.OK

    def test_end_span_persists_in_store(self) -> None:
        mgr = TraceManager()
        ctx = _make_ctx()
        span = mgr.start_span("store.op", ctx=ctx)
        mgr.end_span(span)
        assert len(mgr.get_store()) == 1

    def test_end_span_with_error(self) -> None:
        mgr = TraceManager()
        ctx = _make_ctx()
        span = mgr.start_span("failing.op", ctx=ctx)
        mgr.end_span(span, status=SpanStatus.ERROR, error_type="ValueError", error_message="bad value")
        assert span.status == SpanStatus.ERROR
        assert span.error_type == "ValueError"

    def test_span_attributes(self) -> None:
        mgr = TraceManager()
        ctx = _make_ctx()
        span = mgr.start_span("policy.eval", attributes={"tool.name": "registry.write"}, ctx=ctx)
        assert span.attributes["tool.name"] == "registry.write"
        span.set_attribute("risk.level", "DANGEROUS")
        assert span.attributes["risk.level"] == "DANGEROUS"
        mgr.end_span(span)

    def test_span_events(self) -> None:
        mgr = TraceManager()
        ctx = _make_ctx()
        span = mgr.start_span("wait.op", ctx=ctx)
        span.add_event("confirmation.requested", {"timeout_s": 30})
        span.add_event("confirmation.approved")
        assert len(span.events) == 2
        assert span.events[0].name == "confirmation.requested"
        mgr.end_span(span)


class TestContextManagerSpan:
    """Tests del context manager 'with trace_manager.span()'."""

    def test_context_manager_ok(self) -> None:
        mgr = TraceManager()
        ctx = _make_ctx()
        with mgr.span("cm.op", ctx=ctx) as s:
            s.set_attribute("k", "v")
        assert s.is_finished
        assert s.status == SpanStatus.OK

    def test_context_manager_on_exception(self) -> None:
        mgr = TraceManager()
        ctx = _make_ctx()
        with pytest.raises(RuntimeError):
            with mgr.span("fail.op", ctx=ctx) as s:
                raise RuntimeError("test error")
        assert s.is_finished
        assert s.status == SpanStatus.ERROR
        assert s.error_type == "RuntimeError"

    def test_nested_spans_parent_propagation(self) -> None:
        mgr = TraceManager()
        ctx = _make_ctx()
        with mgr.span("outer", ctx=ctx) as outer:
            with mgr.span("inner", ctx=ctx) as inner:
                pass
        assert inner.parent_span_id == outer.span_id

    def test_nested_spans_share_trace_id(self) -> None:
        mgr = TraceManager()
        ctx = _make_ctx()
        with mgr.span("root", ctx=ctx) as root:
            with mgr.span("child", ctx=ctx) as child:
                pass
        assert root.trace_id == child.trace_id == ctx.correlation_id


class TestInMemoryTraceStore:
    """Tests del InMemoryTraceStore."""

    def test_store_respects_max_size(self) -> None:
        store = InMemoryTraceStore(max_size=3)
        mgr = TraceManager(max_store_size=3)
        ctx = _make_ctx()
        for i in range(5):
            span = mgr.start_span(f"op.{i}", ctx=ctx)
            mgr.end_span(span)
        # Store circular: solo los últimos 3
        assert len(mgr.get_store()) == 3

    def test_get_by_trace(self) -> None:
        mgr = TraceManager()
        ctx_a = _make_ctx(session="a")
        ctx_b = _make_ctx(session="b")
        with mgr.span("op.a", ctx=ctx_a):
            pass
        with mgr.span("op.b", ctx=ctx_b):
            pass
        spans_a = mgr.get_spans_for_trace(ctx_a.correlation_id)
        assert len(spans_a) == 1
        assert spans_a[0].session_id == "a"

    def test_get_by_session(self) -> None:
        mgr = TraceManager()
        ctx = _make_ctx(session="my-session")
        with mgr.span("op.1", ctx=ctx):
            pass
        with mgr.span("op.2", ctx=ctx):
            pass
        spans = mgr.get_store().get_by_session("my-session")
        assert len(spans) == 2


class TestTraceManagerSink:
    """Tests de registro y uso de sinks personalizados."""

    def test_custom_sink_receives_finished_spans(self) -> None:
        received = []

        class FakeSink:
            def emit(self, span):  # type: ignore[no-untyped-def]
                received.append(span)

        mgr = TraceManager()
        mgr.register_sink(FakeSink())
        ctx = _make_ctx()
        with mgr.span("sink.test", ctx=ctx):
            pass
        assert len(received) == 1
        assert received[0].name == "sink.test"

    def test_failing_sink_does_not_crash_manager(self) -> None:
        class FailingSink:
            def emit(self, span):  # type: ignore[no-untyped-def]
                raise RuntimeError("sink broken")

        mgr = TraceManager()
        mgr.register_sink(FailingSink())
        ctx = _make_ctx()
        # No debe propagarse la excepción del sink
        with mgr.span("robust.op", ctx=ctx):
            pass


class TestContextVarInheritance:
    """Tests de propagación del ObservabilityContext al span."""

    def test_span_inherits_task_and_action_ids(self) -> None:
        ctx = ObservabilityContext.create(
            session_id="s",
            component="executor",
            task_id="task-42",
            action_id="action-7",
        )
        mgr = TraceManager()
        span = mgr.start_span("test.op", ctx=ctx)
        assert span.task_id == "task-42"
        assert span.action_id == "action-7"
        mgr.end_span(span)

    def test_span_inherits_plugin_id(self) -> None:
        ctx = ObservabilityContext.create(
            session_id="s",
            component="plugin",
            plugin_id="my-plugin-v1",
        )
        mgr = TraceManager()
        span = mgr.start_span("plugin.execute", ctx=ctx)
        assert span.plugin_id == "my-plugin-v1"
        mgr.end_span(span)

    def test_span_uses_contextvar_when_no_ctx_provided(self) -> None:
        ctx = _make_ctx(session="ctx-var-session")
        mgr = TraceManager()
        token = set_current_context(ctx)
        try:
            span = mgr.start_span("implicit.op")  # sin ctx explícito
            assert span.trace_id == ctx.correlation_id
            mgr.end_span(span)
        finally:
            reset_context(token)
