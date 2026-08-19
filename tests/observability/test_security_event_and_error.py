"""Tests del SecurityEventEmitter y ErrorRecorder — Etapa 17.0.

Verifica:
- SecurityEvent: campos, hash, severidades, tipos
- Emisión y consulta por severidad/tipo/correlación
- ErrorRecord: campos, hash, sanitización de stack trace
- ErrorRecorder: deduplicación, consultas, sink
- Privacidad: ningún campo contiene datos sensibles en metadatos
"""

from __future__ import annotations

import pytest

from core.observability.context import ObservabilityContext, reset_context, set_current_context
from core.observability.error_models import ErrorCategory, ErrorRecord
from core.observability.error_recorder import ErrorRecorder, MemoryErrorSink, sanitize_stack_trace
from core.observability.security_event_emitter import MemorySecurityEventSink, SecurityEventEmitter
from core.observability.security_event_models import SecurityEvent, SecurityEventType, SecuritySeverity


# ──────────────────────────────────────────────────────────────────────────────
# SecurityEventEmitter Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSecurityEventModel:
    def test_security_event_has_hash(self) -> None:
        evt = SecurityEvent(
            event_type=SecurityEventType.REGISTRY_ALLOWLIST_VIOLATION,
            severity=SecuritySeverity.MEDIUM,
            component="boundary.registry",
            description="Key path outside allowlist",
        )
        assert evt.event_hash
        assert len(evt.event_hash) == 64  # SHA-256 hex

    def test_security_event_immutable(self) -> None:
        evt = SecurityEvent(
            event_type=SecurityEventType.EMERGENCY_STOP_ACTIVATED,
            severity=SecuritySeverity.CRITICAL,
            component="emergency_stop",
            description="test",
        )
        with pytest.raises((AttributeError, TypeError)):
            evt.severity = SecuritySeverity.LOW  # type: ignore[misc]

    def test_to_dict_no_sensitive_fields(self) -> None:
        evt = SecurityEvent(
            event_type=SecurityEventType.SENSITIVE_DATA_IN_CLIPBOARD,
            severity=SecuritySeverity.LOW,
            component="boundary.clipboard",
            description="1 secret redacted",
            metadata={"redaction_count": 1},
        )
        d = evt.to_dict()
        # Los metadatos no contienen contenido crudo del clipboard
        assert "clip_content" not in d
        assert "raw_text" not in d
        assert d["metadata"]["redaction_count"] == 1


class TestSecurityEventEmitter:
    def _fresh(self) -> SecurityEventEmitter:
        return SecurityEventEmitter()

    def test_emit_violation_creates_event(self) -> None:
        emitter = self._fresh()
        evt = emitter.emit_violation(
            event_type=SecurityEventType.REGISTRY_ALLOWLIST_VIOLATION,
            severity=SecuritySeverity.MEDIUM,
            component="boundary.registry",
            description="allowlist violation",
            blocked=True,
        )
        assert evt.event_type == SecurityEventType.REGISTRY_ALLOWLIST_VIOLATION
        assert evt.blocked is True

    def test_emit_violation_auto_fills_correlation_from_context(self) -> None:
        ctx = ObservabilityContext.create(session_id="s", component="test")
        token = set_current_context(ctx)
        try:
            emitter = self._fresh()
            evt = emitter.emit_violation(
                event_type=SecurityEventType.PRIVILEGE_ESCALATION_ATTEMPT,
                severity=SecuritySeverity.CRITICAL,
                component="autonomy",
                description="privilege escalation attempt",
            )
            assert evt.correlation_id == ctx.correlation_id
            assert evt.session_id == ctx.session_id
        finally:
            reset_context(token)

    def test_memory_sink_stores_events(self) -> None:
        emitter = self._fresh()
        sink = emitter.get_memory_sink()
        emitter.emit_violation(
            SecurityEventType.EMERGENCY_STOP_ACTIVATED,
            SecuritySeverity.CRITICAL,
            "emergency_stop",
            "stop triggered",
        )
        assert len(sink) == 1

    def test_get_by_severity(self) -> None:
        emitter = self._fresh()
        emitter.emit_violation(SecurityEventType.EMERGENCY_STOP_ACTIVATED, SecuritySeverity.CRITICAL, "c", "d")
        emitter.emit_violation(SecurityEventType.REGISTRY_ALLOWLIST_VIOLATION, SecuritySeverity.MEDIUM, "c", "d")
        sink = emitter.get_memory_sink()
        criticals = sink.get_critical()
        assert len(criticals) == 1
        assert str(criticals[0].severity) == "CRITICAL"

    def test_get_high_and_above(self) -> None:
        emitter = self._fresh()
        emitter.emit_violation(SecurityEventType.EMERGENCY_STOP_ACTIVATED, SecuritySeverity.CRITICAL, "c", "d")
        emitter.emit_violation(SecurityEventType.CONFIRMATION_REPLAY_ATTACK, SecuritySeverity.HIGH, "c", "d")
        emitter.emit_violation(SecurityEventType.REGISTRY_ALLOWLIST_VIOLATION, SecuritySeverity.MEDIUM, "c", "d")
        sink = emitter.get_memory_sink()
        high_plus = sink.get_high_and_above()
        assert len(high_plus) == 2

    def test_get_by_correlation(self) -> None:
        emitter = self._fresh()
        emitter.emit_violation(
            SecurityEventType.PATH_TRAVERSAL_ATTEMPT,
            SecuritySeverity.MEDIUM,
            "boundary.fs",
            "path traversal",
            correlation_id="corr-xyz",
        )
        emitter.emit_violation(
            SecurityEventType.BROWSER_BLOCKED_DOMAIN_ATTEMPT,
            SecuritySeverity.MEDIUM,
            "boundary.browser",
            "domain blocked",
            correlation_id="corr-abc",
        )
        sink = emitter.get_memory_sink()
        evts = sink.get_by_correlation("corr-xyz")
        assert len(evts) == 1

    def test_failing_sink_does_not_crash_emitter(self) -> None:
        class FailingSink:
            def emit(self, e):  # type: ignore[no-untyped-def]
                raise RuntimeError("sink broken")

        emitter = self._fresh()
        emitter.register_sink(FailingSink())
        # No debe propagarse la excepción
        emitter.emit_violation(
            SecurityEventType.EMERGENCY_STOP_ACTIVATED,
            SecuritySeverity.CRITICAL,
            "component",
            "description",
        )

    def test_description_truncated_at_1000_chars(self) -> None:
        emitter = self._fresh()
        long_desc = "x" * 5000
        evt = emitter.emit_violation(
            SecurityEventType.UNKNOWN_SECURITY_ANOMALY,
            SecuritySeverity.INFO,
            "c",
            long_desc,
        )
        assert len(evt.description) <= 1000


# ──────────────────────────────────────────────────────────────────────────────
# ErrorRecorder Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSanitizeStackTrace:
    def test_removes_source_code_lines(self) -> None:
        try:
            secret_val = "password123"  # noqa: F841
            raise ValueError("sanitization test error")
        except ValueError as exc:
            sanitized = sanitize_stack_trace(exc)
        # Las líneas de código fuente que contienen valores deben eliminarse
        assert "password123" not in sanitized
        # Pero el nombre de la excepción debe estar presente
        assert "ValueError" in sanitized

    def test_limits_to_4000_chars(self) -> None:
        try:
            raise RuntimeError("x" * 100)
        except RuntimeError as exc:
            sanitized = sanitize_stack_trace(exc)
        assert len(sanitized) <= 4000


class TestErrorRecord:
    def test_error_record_has_hash(self) -> None:
        record = ErrorRecord(
            component="boundary.registry",
            error_type="RegistrySecurityViolationError",
            error_category=ErrorCategory.SECURITY,
            message="allowlist violation",
        )
        assert record.event_hash
        assert len(record.event_hash) == 64

    def test_error_record_immutable(self) -> None:
        record = ErrorRecord(
            component="test",
            error_type="TestError",
            error_category=ErrorCategory.RUNTIME,
            message="test",
        )
        with pytest.raises((AttributeError, TypeError)):
            record.message = "tampered"  # type: ignore[misc]

    def test_to_dict_structure(self) -> None:
        record = ErrorRecord(
            component="executor",
            error_type="RuntimeError",
            error_category=ErrorCategory.RUNTIME,
            message="something went wrong",
            tool_name="registry.write",
            operation="write",
        )
        d = record.to_dict()
        assert d["component"] == "executor"
        assert d["error_type"] == "RuntimeError"
        assert d["tool_name"] == "registry.write"
        assert "event_hash" in d


class TestErrorRecorder:
    def _fresh(self) -> ErrorRecorder:
        return ErrorRecorder()

    def test_record_creates_error_record(self) -> None:
        recorder = self._fresh()
        try:
            raise ValueError("test error")
        except ValueError as exc:
            record = recorder.record(exc, component="test.component", error_category=ErrorCategory.VALIDATION)
        assert record.error_type == "ValueError"
        assert record.component == "test.component"

    def test_record_auto_fills_context(self) -> None:
        ctx = ObservabilityContext.create(session_id="s", component="test", task_id="t-1")
        token = set_current_context(ctx)
        try:
            recorder = self._fresh()
            try:
                raise RuntimeError("ctx error")
            except RuntimeError as exc:
                record = recorder.record(exc, component="test")
            assert record.correlation_id == ctx.correlation_id
            assert record.task_id == "t-1"
        finally:
            reset_context(token)

    def test_record_stored_in_memory_sink(self) -> None:
        recorder = self._fresh()
        try:
            raise FileNotFoundError("file missing")
        except FileNotFoundError as exc:
            recorder.record(exc, component="filesystem")
        assert len(recorder.get_memory_sink()) == 1

    def test_deduplication_by_hash(self) -> None:
        """El mismo error no se registra dos veces (dedup por hash)."""
        recorder = self._fresh()
        try:
            raise ValueError("duplicate error")
        except ValueError as exc:
            err = exc

        record1 = recorder.record(err, component="c", error_category=ErrorCategory.RUNTIME)
        # Para que sea el mismo hash, crear record con el mismo error_id y event_hash
        record2 = ErrorRecord(
            component=record1.component,
            error_type=record1.error_type,
            error_category=record1.error_category,
            message=record1.message,
            correlation_id=record1.correlation_id,
            session_id=record1.session_id,
            error_id=record1.error_id,
            timestamp=record1.timestamp,
            event_hash=record1.event_hash,
        )
        added = recorder.get_memory_sink().emit(record2)
        assert added is False  # deduplicado

    def test_get_by_category(self) -> None:
        recorder = self._fresh()
        try:
            raise PermissionError("denied")
        except PermissionError as exc:
            recorder.record(exc, component="security", error_category=ErrorCategory.SECURITY)
        try:
            raise TimeoutError("timeout")
        except TimeoutError as exc:
            recorder.record(exc, component="network", error_category=ErrorCategory.TIMEOUT)

        security_errs = recorder.get_memory_sink().get_by_category(ErrorCategory.SECURITY)
        assert len(security_errs) == 1
        assert security_errs[0].error_category == ErrorCategory.SECURITY

    def test_message_truncated_at_1000_chars(self) -> None:
        recorder = self._fresh()
        long_msg = "x" * 5000
        try:
            raise RuntimeError(long_msg)
        except RuntimeError as exc:
            record = recorder.record(exc, component="c")
        assert len(record.message) <= 1000
