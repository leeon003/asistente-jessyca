"""Tests unitarios e integración para Structured Telemetry (Etapa 17.1).

Verifica:
1. CorrelationId & ActionId (generación, validación, inmutabilidad).
2. EventSeverity & EventCategory (categorías obligatorias de la Etapa 17.1).
3. TraceContext (creación, derivación, serialización y deserialización).
4. Sanitización Bounded y Redacción de Secretos con SecretRedactor.
5. StructuredEvent (formato machine-readable, límites de tamaño, to_dict/to_json/from_dict/from_json).
6. StructuredEventEmitter & JsonlStructuredEventExporter.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.observability import (
    ActionId,
    CorrelationId,
    EventCategory,
    EventSeverity,
    JsonlStructuredEventExporter,
    StructuredEvent,
    StructuredEventEmitter,
    StructuredTelemetryEmitter,
    TraceContext,
    get_structured_telemetry_emitter,
    sanitize_bounded_metadata,
)


class TestIdentifiers:
    """Pruebas para CorrelationId y ActionId."""

    def test_correlation_id_generation_and_validation(self) -> None:
        cid = CorrelationId.generate(prefix="corr_test_")
        assert cid.value.startswith("corr_test_")
        assert len(str(cid)) > 10
        assert repr(cid).startswith("CorrelationId('corr_test_")

        # Inmutabilidad
        with pytest.raises(Exception):
            cid.value = "new_val"  # type: ignore[misc]

        # Validación de no vacío
        with pytest.raises(ValueError, match="no puede estar vacío"):
            CorrelationId("   ")

    def test_action_id_generation_and_validation(self) -> None:
        aid = ActionId.generate(prefix="act_test_")
        assert aid.value.startswith("act_test_")
        assert str(aid) == aid.value
        assert repr(aid).startswith("ActionId('act_test_")

        # Inmutabilidad
        with pytest.raises(Exception):
            aid.value = "new_val"  # type: ignore[misc]

        with pytest.raises(ValueError, match="no puede estar vacío"):
            ActionId("")


class TestTaxonomy:
    """Pruebas para EventSeverity y EventCategory."""

    def test_all_10_required_categories_present(self) -> None:
        required_categories = {
            "ACTION",
            "TOOL",
            "SECURITY",
            "MEMORY",
            "BROWSER",
            "DESKTOP",
            "SCHEDULER",
            "PLUGIN",
            "SYSTEM",
            "ERROR",
        }
        actual_categories = {cat.value for cat in EventCategory}
        assert required_categories == actual_categories

    def test_severities_present(self) -> None:
        required_severities = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        actual_severities = {sev.value for sev in EventSeverity}
        assert required_severities == actual_severities


class TestTraceContext:
    """Pruebas para TraceContext."""

    def test_trace_context_lifecycle_and_derive(self) -> None:
        root_tc = TraceContext(
            correlation_id="corr-root-123",
            session_id="sess-abc",
            task_id="task-01",
        )
        assert root_tc.correlation_id == "corr-root-123"
        assert root_tc.action_id is None

        # Derivación a acción hija
        child_tc = root_tc.derive(action_id="act-child-456", plugin_id="plugin-file")
        assert child_tc.correlation_id == "corr-root-123"
        assert child_tc.session_id == "sess-abc"
        assert child_tc.task_id == "task-01"
        assert child_tc.action_id == "act-child-456"
        assert child_tc.plugin_id == "plugin-file"

    def test_trace_context_serialization_roundtrip(self) -> None:
        tc = TraceContext(
            correlation_id="corr-001",
            action_id="act-001",
            session_id="sess-001",
            task_id="task-001",
            plugin_id="plugin-001",
            span_id="span-001",
            parent_span_id="span-parent",
            sampled=True,
            baggage={"env": "prod"},
        )
        data = tc.to_dict()
        restored = TraceContext.from_dict(data)
        assert tc == restored


class TestBoundedSanitizationAndRedaction:
    """Pruebas para sanitize_bounded_metadata y SecretRedactor."""

    def test_secret_redaction_in_strings(self) -> None:
        raw_text = "Conectando con password=SuperSecretPassword123 y token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.xyz"
        sanitized = sanitize_bounded_metadata(raw_text)
        assert "SuperSecretPassword123" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_sensitive_keys_redacted(self) -> None:
        payload = {
            "normal_field": "public_data",
            "password": "my_cleartext_password",
            "api_key": "sk-1234567890abcdef",
            "clipboard_content": "texto copiado confidencial",
            "raw_screenshot": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
            "raw_audio": b"\x00\x01\x02\x03\x04\x05",
        }
        sanitized = sanitize_bounded_metadata(payload)
        assert sanitized["normal_field"] == "public_data"
        assert sanitized["password"] == "[REDACTED_SENSITIVE_VALUE]"
        assert sanitized["api_key"] == "[REDACTED_SENSITIVE_VALUE]"
        assert sanitized["clipboard_content"] == "[REDACTED_SENSITIVE_VALUE]"
        assert sanitized["raw_screenshot"] == "[REDACTED_SENSITIVE_VALUE]"
        assert sanitized["raw_audio"] == "[REDACTED_SENSITIVE_VALUE]"

    def test_binary_data_handled_cleanly_when_not_in_sensitive_key(self) -> None:
        payload = {"data_blob": b"some binary data"}
        sanitized = sanitize_bounded_metadata(payload)
        assert sanitized["data_blob"].startswith("[BINARY_DATA len=16 sha256_prefix=")

    def test_max_string_length_bounded(self) -> None:
        long_str = "A" * 2000
        sanitized = sanitize_bounded_metadata(long_str, max_string_len=100)
        assert len(sanitized) <= 120
        assert sanitized.endswith("...[TRUNCATED]")

    def test_max_keys_bounded(self) -> None:
        payload = {f"key_{i}": i for i in range(100)}
        sanitized = sanitize_bounded_metadata(payload, max_keys=10)
        assert len(sanitized) == 11  # 10 keys + _truncated_keys_count
        assert sanitized["_truncated_keys_count"] == 90

    def test_max_list_items_bounded(self) -> None:
        items = list(range(50))
        sanitized = sanitize_bounded_metadata(items, max_list_items=5)
        assert len(sanitized) == 6  # 5 items + [LIST_TRUNCATED +45 items]
        assert sanitized[5] == "[LIST_TRUNCATED +45 items]"

    def test_max_depth_bounded(self) -> None:
        nested: dict[str, Any] = {"level1": {"level2": {"level3": {"level4": {"level5": {"level6": "deep"}}}}}}
        sanitized = sanitize_bounded_metadata(nested, max_depth=3)
        assert sanitized["level1"]["level2"]["level3"]["level4"] == "[DEPTH_LIMIT_EXCEEDED]"


class TestStructuredEvent:
    """Pruebas para StructuredEvent (creación, serialización machine-readable)."""

    def test_structured_event_creation_and_auto_redaction(self) -> None:
        event = StructuredEvent.create(
            name="tool.execute_powershell",
            category=EventCategory.TOOL,
            correlation_id="corr-999",
            action_id="act-888",
            severity=EventSeverity.INFO,
            payload={
                "command": "Get-Process -Name secret_svc",
                "api_key": "sk-secret123",
                "normal_param": "test_param",
            },
            duration_ms=45.2,
        )

        assert event.name == "tool.execute_powershell"
        assert event.category == EventCategory.TOOL
        assert event.severity == EventSeverity.INFO
        assert event.correlation_id == "corr-999"
        assert event.action_id == "act-888"
        assert event.duration_ms == 45.2

        # Verificación de que el payload fue sanitizado automáticamente
        assert event.payload["api_key"] == "[REDACTED_SENSITIVE_VALUE]"
        assert event.payload["normal_param"] == "test_param"

    def test_machine_readable_json_roundtrip(self) -> None:
        tc = TraceContext(correlation_id="corr-json", action_id="act-json")
        event = StructuredEvent.create(
            name="memory.retrieve",
            category=EventCategory.MEMORY,
            correlation_id="corr-json",
            action_id="act-json",
            trace_context=tc,
            payload={"query": "consulta normal", "limit": 5},
            duration_ms=12.5,
        )

        json_str = event.to_json()
        assert isinstance(json_str, str)

        # Parsear JSON crudo para verificar formato machine-readable
        parsed = json.loads(json_str)
        assert parsed["name"] == "memory.retrieve"
        assert parsed["category"] == "MEMORY"
        assert parsed["severity"] == "INFO"
        assert parsed["correlation_id"] == "corr-json"
        assert parsed["action_id"] == "act-json"
        assert parsed["payload"] == {"query": "consulta normal", "limit": 5}
        assert parsed["duration_ms"] == 12.5
        assert parsed["trace_context"]["correlation_id"] == "corr-json"

        # Reconstruir desde JSON
        restored = StructuredEvent.from_json(json_str)
        assert restored.event_id == event.event_id
        assert restored.name == event.name
        assert restored.category == event.category
        assert restored.correlation_id == event.correlation_id


class TestStructuredTelemetryEmitterAndExporter:
    """Pruebas para StructuredTelemetryEmitter y JsonlStructuredEventExporter."""

    def test_emitter_and_jsonl_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test_telemetry.jsonl"
            exporter = JsonlStructuredEventExporter(file_path)

            try:
                emitter = StructuredTelemetryEmitter()
                emitter.register_sink(exporter)

                ev1 = emitter.emit_action(
                    name="user_request_received",
                    correlation_id="corr-emit-1",
                    action_id="act-emit-1",
                    payload={"user": "admin", "intent": "list_files"},
                )

                ev2 = emitter.emit_tool(
                    tool_name="filesystem",
                    operation="list",
                    correlation_id="corr-emit-1",
                    action_id="act-emit-2",
                    parameters={"path": "C:\\safe"},
                    duration_ms=8.4,
                )

                ev3 = emitter.emit_security(
                    name="unauthorized_access_blocked",
                    correlation_id="corr-emit-1",
                    severity=EventSeverity.WARNING,
                    payload={"attempted_tool": "registry.write"},
                )

                ev4 = emitter.emit_error(
                    name="tool_execution_failed",
                    correlation_id="corr-emit-1",
                    error_detail={"error_type": "FileNotFoundError", "path": "C:\\missing"},
                )

                exporter.flush()
            finally:
                exporter.close()

            # Leer y verificar archivo JSONL generado
            assert file_path.exists()
            lines = file_path.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 4

            events = [json.loads(line) for line in lines]
            assert events[0]["name"] == "user_request_received"
            assert events[0]["category"] == "ACTION"

            assert events[1]["name"] == "filesystem.list"
            assert events[1]["category"] == "TOOL"

            assert events[2]["name"] == "unauthorized_access_blocked"
            assert events[2]["category"] == "SECURITY"
            assert events[2]["severity"] == "WARNING"

            assert events[3]["name"] == "tool_execution_failed"
            assert events[3]["category"] == "ERROR"
            assert events[3]["severity"] == "ERROR"

    def test_global_singleton_emitter(self) -> None:
        emitter1 = get_structured_telemetry_emitter()
        emitter2 = get_structured_telemetry_emitter()
        assert emitter1 is emitter2
