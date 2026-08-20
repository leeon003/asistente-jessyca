"""Pruebas adversariales de seguridad en ConfirmationManager (Subetapa 04.7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.confirmation import (
    ConfirmationManager,
    ConfirmationStatus,
    MockConfirmationProvider,
)
from core.security_architecture import SecurityLevel


def test_replay_attack_prevention() -> None:
    mgr = ConfirmationManager()
    req = mgr.create_request(
        tool_name="process_killer",
        operation="terminate",
        parameters={"pid": 1234},
        risk_level=SecurityLevel.DANGEROUS,
    )

    mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

    # Primer intento de consumo -> Exitoso
    first = mgr.consume_confirmation(req.request_id, "process_killer", "terminate", {"pid": 1234})
    assert first is True

    # Replay attack (segundo intento) -> Bloqueado
    second = mgr.consume_confirmation(req.request_id, "process_killer", "terminate", {"pid": 1234})
    assert second is False


def test_fingerprint_mismatch_parameter_injection() -> None:
    mgr = ConfirmationManager()
    req = mgr.create_request(
        tool_name="fs_delete",
        operation="delete",
        parameters={"path": "C:\\temp\\file1.txt"},
        risk_level=SecurityLevel.DANGEROUS,
    )
    mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

    # Intentar consumir alterando el parámetro objetivo
    consumed = mgr.consume_confirmation(req.request_id, "fs_delete", "delete", {"path": "C:\\Windows\\System32\\cmd.exe"})
    assert consumed is False


def test_fingerprint_mismatch_tool_substitution() -> None:
    mgr = ConfirmationManager()
    req = mgr.create_request(
        tool_name="safe_tool",
        operation="execute",
        parameters={"cmd": "dir"},
    )
    mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

    # Sustitución de herramienta objetivo
    consumed = mgr.consume_confirmation(req.request_id, "dangerous_tool", "execute", {"cmd": "dir"})
    assert consumed is False


def test_confirmation_expiration_ttl() -> None:
    mgr = ConfirmationManager()
    req = mgr.create_request(
        tool_name="fs_delete",
        operation="delete",
        parameters={"file": "test.txt"},
        ttl_seconds=0.01,  # TTL de 10ms
    )
    mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

    # Simular paso del tiempo manipulando expires_at a una fecha pasada
    req.expires_at = datetime.now(UTC) - timedelta(seconds=10)

    # Intentar consumir confirmación expirada -> Bloqueado
    consumed = mgr.consume_confirmation(req.request_id, "fs_delete", "delete", {"file": "test.txt"})
    assert consumed is False


def test_session_mismatch_rejection() -> None:
    mgr = ConfirmationManager()
    req = mgr.create_request(
        tool_name="fs_delete",
        operation="delete",
        parameters={"file": "test.txt"},
        session_id="session_A",
    )
    mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

    # Intentar consumir la confirmación desde una sesión distinta
    consumed = mgr.consume_confirmation(
        req.request_id,
        "fs_delete",
        "delete",
        {"file": "test.txt"},
        session_id="session_B",
    )
    assert consumed is False
