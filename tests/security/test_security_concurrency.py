"""Pruebas de estrés y concurrencia multi-hilo para el subsistema de seguridad (Subetapa 04.7)."""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from core.audit_logger import AuditEvent, AuditEventType, AuditLogger, FileAuditSink, MemoryAuditSink
from core.confirmation import ConfirmationManager, ConfirmationStatus, MockConfirmationProvider
from core.permission_manager import PermissionManager, PermissionRequest
from core.risk_engine import RiskEngine
from core.security_architecture import SecurityContext, SecurityLevel, ToolSecurityMetadata


def test_concurrent_confirmation_consumption_single_winner() -> None:
    conf_mgr = ConfirmationManager()
    req = conf_mgr.create_request(
        tool_name="race_tool",
        operation="delete",
        parameters={"id": "resource_123"},
        risk_level=SecurityLevel.DANGEROUS,
    )
    conf_mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

    successes: list[bool] = []
    lock = threading.Lock()

    def _worker() -> None:
        res = conf_mgr.consume_confirmation(req.request_id, "race_tool", "delete", {"id": "resource_123"})
        with lock:
            successes.append(res)

    threads = [threading.Thread(target=_worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactamente 1 hilo debe haber ganado el consumo (True) y los otros 19 deben ser rechazados (False)
    assert successes.count(True) == 1
    assert successes.count(False) == 19


def test_concurrent_audit_logging_integrity() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_sink = FileAuditSink(audit_dir=tmp_dir, file_name="stress.jsonl")
        mem_sink = MemoryAuditSink()
        logger = AuditLogger(sinks=[file_sink, mem_sink])

        def _audit_worker(worker_id: int) -> None:
            for i in range(15):
                logger.log_audit_event(
                    AuditEvent(
                        event_type=AuditEventType.EXECUTION_SUCCEEDED,
                        user=f"user_{worker_id}",
                        request_id=f"req_{worker_id}_{i}",
                    )
                )

        threads = [threading.Thread(target=_audit_worker, args=(w,)) for w in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events = mem_sink.get_events()
        assert len(events) == 150  # 10 * 15

        file_path = Path(tmp_dir) / "stress.jsonl"
        lines = file_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 150


def test_concurrent_permission_evaluations() -> None:
    perm_mgr = PermissionManager()
    risk_eng = RiskEngine()
    results: list[bool] = []
    lock = threading.Lock()

    def _eval_worker(i: int) -> None:
        ctx = SecurityContext(user=f"user_{i}", tool_name="safe_tool")
        meta = ToolSecurityMetadata(tool_name="safe_tool", risk_level=SecurityLevel.SAFE)
        risk = risk_eng.evaluate_risk(ctx, {})
        req = PermissionRequest(context=ctx, metadata=meta, risk_assessment=risk, tool_name="safe_tool", operation="read")

        res = perm_mgr.evaluate_permission(req)
        with lock:
            results.append(res.is_allowed)

    threads = [threading.Thread(target=_eval_worker, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 25
    assert all(r is True for r in results)
