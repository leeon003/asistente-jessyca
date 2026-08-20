"""Pruebas unitarias de seguridad y regresión para Audit Logger (Subetapa 04.6).

Cubre los 30 escenarios requeridos:
1. AuditEvent válido.
2. event_id único.
3. timestamp UTC.
4. request_id.
5. correlation_id.
6. session_id.
7. event types.
8. FileAuditSink.
9. MemoryAuditSink.
10. JSONL.
11. Múltiples eventos.
12. Concurrencia.
13. Sanitización password.
14. Sanitización token.
15. Sanitización api_key.
16. Sanitización secret.
17. Sanitización credential.
18. Sanitización nested.
19. Listas.
20. Metadata.
21. Truncamiento.
22. Evento inmutable.
23. Fallo del sink.
24. AuditLogger desacoplado.
25. No ejecución de herramientas.
26. No modificación de policy.
27. No decisión de permisos.
28. Correlación de eventos.
29. Event ordering.
30. Regresión 04.1–04.5.
"""

from __future__ import annotations

import json
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.audit_logger import (
    AuditEvent,
    AuditEventType,
    AuditFailureMode,
    AuditLogger,
    FileAuditSink,
    MemoryAuditSink,
    sanitize_audit_data,
)
from core.confirmation import ConfirmationManager
from core.permission_manager import PermissionManager
from core.risk_engine import RiskEngine
from core.security_architecture import SecurityContext, SecurityLevel, ToolSecurityMetadata
from core.security_policy import SecurityPolicyEvaluator, create_default_security_policy


# 1. AuditEvent válido
def test_audit_event_valid() -> None:
    event = AuditEvent(
        event_type=AuditEventType.REQUEST_RECEIVED,
        user="test_user",
        tool_name="filesystem",
        operation="read",
    )
    assert event.event_type == AuditEventType.REQUEST_RECEIVED
    assert event.user == "test_user"
    assert event.tool_name == "filesystem"
    assert event.operation == "read"
    assert event.event_id != ""


# 2. event_id único
def test_event_id_unique() -> None:
    e1 = AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED)
    e2 = AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED)
    assert e1.event_id != e2.event_id


# 3. timestamp UTC
def test_timestamp_utc() -> None:
    e = AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED)
    assert isinstance(e.timestamp, datetime)
    assert e.timestamp.tzinfo == UTC or e.timestamp.tzinfo is not None


# 4. request_id
def test_request_id_correlation() -> None:
    e = AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED, request_id="req-12345")
    assert e.request_id == "req-12345"


# 5. correlation_id
def test_correlation_id_correlation() -> None:
    e = AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED, correlation_id="corr-999")
    assert e.correlation_id == "corr-999"


# 6. session_id
def test_session_id_correlation() -> None:
    e = AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED, session_id="sess-abc")
    assert e.session_id == "sess-abc"


# 7. event types
def test_audit_event_types() -> None:
    types = list(AuditEventType)
    assert AuditEventType.REQUEST_RECEIVED in types
    assert AuditEventType.RISK_EVALUATED in types
    assert AuditEventType.POLICY_EVALUATED in types
    assert AuditEventType.PERMISSION_EVALUATED in types
    assert AuditEventType.CONFIRMATION_REQUESTED in types
    assert AuditEventType.EXECUTION_STARTED in types
    assert AuditEventType.EXECUTION_SUCCEEDED in types
    assert AuditEventType.EXECUTION_FAILED in types
    assert AuditEventType.ERROR in types


# 8. FileAuditSink
def test_file_audit_sink() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        sink = FileAuditSink(audit_dir=tmp_dir, file_name="test_audit.jsonl")
        event = AuditEvent(
            event_type=AuditEventType.EXECUTION_SUCCEEDED,
            user="user1",
            tool_name="cmd_tool",
        )
        sink.emit(event)

        file_path = Path(tmp_dir) / "test_audit.jsonl"
        assert file_path.exists()
        content = file_path.read_text(encoding="utf-8")
        assert "user1" in content
        assert "EXECUTION_SUCCEEDED" in content


# 9. MemoryAuditSink
def test_memory_audit_sink() -> None:
    sink = MemoryAuditSink()
    e1 = AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED, request_id="r1", tool_name="tool_a")
    e2 = AuditEvent(event_type=AuditEventType.EXECUTION_SUCCEEDED, request_id="r1", tool_name="tool_a")
    sink.emit(e1)
    sink.emit(e2)

    events = sink.get_events(request_id="r1")
    assert len(events) == 2
    assert events[0].event_type == AuditEventType.REQUEST_RECEIVED
    assert events[1].event_type == AuditEventType.EXECUTION_SUCCEEDED


# 10. JSONL
def test_jsonl_formatting() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        sink = FileAuditSink(audit_dir=tmp_dir, file_name="test_format.jsonl")
        sink.emit(AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED, request_id="r1"))
        sink.emit(AuditEvent(event_type=AuditEventType.EXECUTION_SUCCEEDED, request_id="r1"))

        file_path = Path(tmp_dir) / "test_format.jsonl"
        lines = file_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        p1 = json.loads(lines[0])
        p2 = json.loads(lines[1])
        assert p1["request_id"] == "r1"
        assert p2["request_id"] == "r1"


# 11. Múltiples eventos
def test_multiple_events_logging() -> None:
    mem_sink = MemoryAuditSink()
    logger = AuditLogger(sinks=[mem_sink])

    for i in range(10):
        logger.log_audit_event(AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED, request_id=f"req-{i}"))

    events = mem_sink.get_events()
    assert len(events) == 10


# 12. Concurrencia
def test_audit_concurrency() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_sink = FileAuditSink(audit_dir=tmp_dir, file_name="concurrent.jsonl")
        mem_sink = MemoryAuditSink()
        logger = AuditLogger(sinks=[file_sink, mem_sink])

        def _log_worker(worker_id: int) -> None:
            for k in range(20):
                logger.log_audit_event(
                    AuditEvent(
                        event_type=AuditEventType.EXECUTION_SUCCEEDED,
                        user=f"worker_{worker_id}",
                        request_id=f"req_{worker_id}_{k}",
                    )
                )

        threads = [threading.Thread(target=_log_worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events = mem_sink.get_events()
        assert len(events) == 100

        file_path = Path(tmp_dir) / "concurrent.jsonl"
        lines = file_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 100
        for line in lines:
            parsed = json.loads(line)
            assert "event_id" in parsed


# 13. Sanitización password
def test_sanitization_password() -> None:
    params = {"username": "admin", "password": "SuperSecretPassword123"}
    sanitized = sanitize_audit_data(params)
    assert sanitized["username"] == "admin"
    assert sanitized["password"] == "[REDACTED]"


# 14. Sanitización token
def test_sanitization_token() -> None:
    params = {"access_token": "bearer_abc123xyz", "refresh_token": "ref_999"}
    sanitized = sanitize_audit_data(params)
    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["refresh_token"] == "[REDACTED]"


# 15. Sanitización api_key
def test_sanitization_api_key() -> None:
    params = {"api_key": "sk-proj-key12345"}
    sanitized = sanitize_audit_data(params)
    assert sanitized["api_key"] == "[REDACTED]"


# 16. Sanitización secret
def test_sanitization_secret() -> None:
    params = {"client_secret": "sec_key_xyz"}
    sanitized = sanitize_audit_data(params)
    assert sanitized["client_secret"] == "[REDACTED]"


# 17. Sanitización credential
def test_sanitization_credential() -> None:
    params = {"credential_data": "pass123"}
    sanitized = sanitize_audit_data(params)
    assert sanitized["credential_data"] == "[REDACTED]"


# 18. Sanitización nested
def test_sanitization_nested_dict() -> None:
    nested = {
        "user": "jessyca",
        "auth_details": {
            "token": "secret_token_123",
            "metadata": {"api_key": "key_abc"},
        },
    }
    sanitized = sanitize_audit_data(nested)
    assert sanitized["auth_details"]["token"] == "[REDACTED]"
    assert sanitized["auth_details"]["metadata"]["api_key"] == "[REDACTED]"


# 19. Listas
def test_sanitization_lists() -> None:
    data = [
        {"name": "u1", "password": "p1"},
        {"name": "u2", "token": "t2"},
    ]
    sanitized = sanitize_audit_data(data)
    assert sanitized[0]["password"] == "[REDACTED]"
    assert sanitized[1]["token"] == "[REDACTED]"


# 20. Metadata
def test_metadata_field_handling() -> None:
    meta = {"source_ip": "127.0.0.1", "auth_token": "secret_token"}
    event = AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED, metadata=meta)
    event_dict = event.to_dict()
    assert event_dict["metadata"]["source_ip"] == "127.0.0.1"
    assert event_dict["metadata"]["auth_token"] == "[REDACTED]"


# 21. Truncamiento
def test_string_truncation() -> None:
    long_str = "A" * 1500
    sanitized = sanitize_audit_data(long_str, max_str_len=100)
    assert len(sanitized) < 1500
    assert "[TRUNCATED]" in sanitized


# 22. Evento inmutable
def test_event_immutability() -> None:
    mem_sink = MemoryAuditSink()
    logger = AuditLogger(sinks=[mem_sink])
    params = {"key": "value"}

    event = AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED, parameters=params)
    logger.log_audit_event(event)

    # Modificar params del diccionario original no corrompe el evento registrado
    params["key"] = "modified_value"
    recorded = mem_sink.get_events()[0]
    assert recorded.parameters["key"] == "value"

    # Modificar atributos en un AuditEvent frozen debe lanzar un error de inmutabilidad
    with pytest.raises(Exception):  # FrozenInstanceError / AttributeError
        event.user = "hacked_user"  # type: ignore[misc]


# 23. Fallo del sink
class BrokenSink:
    def emit(self, event: AuditEvent) -> None:
        raise OSError("Disk write failed simulated")


def test_sink_failure_handling() -> None:
    mem_sink = MemoryAuditSink()
    broken_sink = BrokenSink()
    logger = AuditLogger(sinks=[broken_sink, mem_sink], failure_mode=AuditFailureMode.BEST_EFFORT)

    # El fallo de BrokenSink en modo BEST_EFFORT no debe lanzar excepción ni impedir la ejecución
    event = logger.log_audit_event(AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED))
    assert event.event_id != ""
    assert len(mem_sink.get_events()) == 1


# 24. AuditLogger desacoplado
def test_audit_logger_decoupled() -> None:
    logger = AuditLogger(sinks=[MemoryAuditSink()])
    res = logger.log_audit_event(AuditEvent(event_type=AuditEventType.SECURITY_ALERT, reason="Test alert"))
    assert res.reason == "Test alert"


# 25. No ejecución de herramientas
def test_no_tool_execution_in_audit_logger() -> None:
    logger = AuditLogger(sinks=[MemoryAuditSink()])
    # Verificar que AuditLogger no tenga métodos para ejecutar herramientas o manipular procesos del SO
    assert not hasattr(logger, "execute_tool")
    assert not hasattr(logger, "run_command")
    assert not hasattr(logger, "terminate_process")


# 26. No modificación de policy
def test_no_policy_modification_in_audit_logger() -> None:
    logger = AuditLogger(sinks=[MemoryAuditSink()])
    # Verificar que AuditLogger no modifique reglas ni estados de políticas de seguridad
    assert not hasattr(logger, "modify_policy")
    assert not hasattr(logger, "add_policy_rule")


# 27. No decisión de permisos
def test_no_permission_decision_in_audit_logger() -> None:
    logger = AuditLogger(sinks=[MemoryAuditSink()])
    # Verificar que AuditLogger no tome ni altere decisiones de permiso
    assert not hasattr(logger, "evaluate_permission")
    assert not hasattr(logger, "grant_permission")


# 28. Correlación de eventos
def test_event_lifecycle_correlation() -> None:
    mem_sink = MemoryAuditSink()
    logger = AuditLogger(sinks=[mem_sink])
    req_id = "request_abc_123"

    logger.log_audit_event(AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED, request_id=req_id))
    logger.log_audit_event(AuditEvent(event_type=AuditEventType.RISK_EVALUATED, request_id=req_id))
    logger.log_audit_event(AuditEvent(event_type=AuditEventType.POLICY_EVALUATED, request_id=req_id))
    logger.log_audit_event(AuditEvent(event_type=AuditEventType.EXECUTION_SUCCEEDED, request_id=req_id))

    lifecycle = mem_sink.get_events(request_id=req_id)
    assert len(lifecycle) == 4
    assert [e.event_type for e in lifecycle] == [
        AuditEventType.REQUEST_RECEIVED,
        AuditEventType.RISK_EVALUATED,
        AuditEventType.POLICY_EVALUATED,
        AuditEventType.EXECUTION_SUCCEEDED,
    ]


# 29. Event ordering
def test_event_ordering() -> None:
    mem_sink = MemoryAuditSink()
    logger = AuditLogger(sinks=[mem_sink])

    e1 = logger.log_audit_event(AuditEvent(event_type=AuditEventType.REQUEST_RECEIVED))
    e2 = logger.log_audit_event(AuditEvent(event_type=AuditEventType.EXECUTION_SUCCEEDED))

    events = mem_sink.get_events()
    assert events[0].timestamp <= events[1].timestamp
    assert events[0].event_id == e1.event_id
    assert events[1].event_id == e2.event_id


# 30. Regresión 04.1–04.5
def test_regression_04_1_to_04_5() -> None:
    # 04.2 Risk Engine
    risk_eng = RiskEngine()
    ctx = SecurityContext(user="test", tool_name="sys", parameters={"path": "C:\\Windows\\System32"})
    meta = ToolSecurityMetadata(tool_name="sys", category="sys", risk_level=SecurityLevel.SAFE)
    risk_ass = risk_eng.evaluate_risk(ctx, {"path": "C:\\Windows\\System32"})
    assert risk_ass.risk_level == SecurityLevel.CRITICAL

    # 04.3 Permission Manager
    perm_mgr = PermissionManager()
    from core.permission_manager import PermissionRequest
    perm_req = PermissionRequest(context=ctx, metadata=meta, risk_assessment=risk_ass, tool_name="sys", operation="read")
    perm_res = perm_mgr.evaluate_permission(perm_req)
    assert perm_res.is_allowed is False

    # 04.4 Confirmation Manager
    conf_mgr = ConfirmationManager()
    req = conf_mgr.create_request(tool_name="t1", message="msg", risk_level=SecurityLevel.DANGEROUS)
    assert req.status == "pending"

    # 04.5 Security Policy
    policy_eval = SecurityPolicyEvaluator()
    policy = create_default_security_policy()
    policy_dec = policy_eval.evaluate_policy(ctx, meta, risk_ass, policy)
    assert policy_dec.is_allowed is False
