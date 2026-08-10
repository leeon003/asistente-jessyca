"""Pruebas adversariales para AuditLogger, sanitización de secretos y manejo de fallos (Subetapa 04.7)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.audit_logger import AuditEvent, AuditEventType, AuditFailureMode, AuditLogger, FileAuditSink, MemoryAuditSink, sanitize_audit_data


def test_audit_event_pre_persistence_secret_redaction() -> None:
    mem_sink = MemoryAuditSink()
    logger = AuditLogger(sinks=[mem_sink])

    params = {
        "user_id": "u123",
        "password": "MySuperSecretPassword123",
        "api_key": "sk-proj-99999",
        "nested": {
            "access_token": "bearer_abc_xyz",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----",
        },
        "list_of_secrets": [
            {"credential": "pass_in_list"},
            "public_string",
        ],
    }

    event = AuditEvent(
        event_type=AuditEventType.REQUEST_RECEIVED,
        user="test_user",
        parameters=params,
    )
    logger.log_audit_event(event)

    recorded = mem_sink.get_events()[0]
    rec_dict = recorded.to_dict()

    assert rec_dict["parameters"]["password"] == "[REDACTED]"
    assert rec_dict["parameters"]["api_key"] == "[REDACTED]"
    assert rec_dict["parameters"]["nested"]["access_token"] == "[REDACTED]"
    assert rec_dict["parameters"]["nested"]["private_key"] == "[REDACTED]"
    assert rec_dict["parameters"]["list_of_secrets"][0]["credential"] == "[REDACTED]"
    assert rec_dict["parameters"]["list_of_secrets"][1] == "public_string"


def test_audit_event_frozen_immutability() -> None:
    event = AuditEvent(
        event_type=AuditEventType.REQUEST_RECEIVED,
        user="original_user",
    )

    # Modificar cualquier propiedad debe lanzar FrozenInstanceError
    with pytest.raises(Exception):
        event.user = "tampered_user"  # type: ignore[misc]

    with pytest.raises(Exception):
        event.requires_elevation = True  # type: ignore[misc]


class FailingSink:
    def emit(self, event: AuditEvent) -> None:
        raise OSError("Disk failure / Write permission denied")


def test_audit_sink_failure_best_effort_isolation() -> None:
    failing_sink = FailingSink()
    mem_sink = MemoryAuditSink()
    logger = AuditLogger(sinks=[failing_sink, mem_sink], failure_mode=AuditFailureMode.BEST_EFFORT)

    # El fallo de un sink en BEST_EFFORT no interrumpe el flujo ni lanza excepciones no controladas
    event = AuditEvent(event_type=AuditEventType.SECURITY_ALERT, reason="Critical alert test")
    result_event = logger.log_audit_event(event)

    assert result_event.event_id == event.event_id
    assert len(mem_sink.get_events()) == 1


def test_file_audit_sink_concurrency_and_rotation() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        # FileAuditSink con tamaño máximo pequeño (200 bytes) para forzar rotación
        sink = FileAuditSink(audit_dir=tmp_dir, file_name="audit_rot.jsonl", max_bytes=200, backup_count=3)
        logger = AuditLogger(sinks=[sink])

        for i in range(10):
            logger.log_audit_event(AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED, request_id=f"req_{i}"))

        base_file = Path(tmp_dir) / "audit_rot.jsonl"
        backup_file = Path(tmp_dir) / "audit_rot.jsonl.1"
        assert base_file.exists()
        assert backup_file.exists()
