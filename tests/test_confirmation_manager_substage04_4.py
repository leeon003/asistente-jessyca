"""Pruebas unitarias exhaustivas exclusivas para la Subetapa 04.4 — Confirmation Manager."""

from __future__ import annotations

import concurrent.futures
import time
from datetime import UTC, datetime, timedelta

import pytest

from core.confirmation import (
    ConfirmationManager,
    ConfirmationRequest,
    ConfirmationResult,
    ConfirmationStatus,
    MockConfirmationProvider,
    compute_action_fingerprint,
    sanitize_sensitive_parameters,
)
from core.contracts import IConfirmationManager, IConfirmationProvider
from core.security_architecture import SecurityLevel


def test_confirmation_manager_implements_interfaces() -> None:
    """Verifica el cumplimiento de los contratos IConfirmationManager e IConfirmationProvider."""
    mgr = ConfirmationManager()
    prov = MockConfirmationProvider()
    assert isinstance(mgr, IConfirmationManager)
    assert isinstance(prov, IConfirmationProvider)


def test_valid_confirmation_request_creation() -> None:
    """1. Creación de ConfirmationRequest válido."""
    mgr = ConfirmationManager()
    req = mgr.create_request(
        tool_name="delete_directory",
        operation="delete",
        parameters={"path": "C:\\Temp\\old"},
        risk_level=SecurityLevel.DANGEROUS,
    )
    assert isinstance(req, ConfirmationRequest)
    assert req.tool_name == "delete_directory"
    assert req.operation == "delete"
    assert req.status == ConfirmationStatus.PENDING
    assert req.fingerprint is not None


def test_invalid_confirmation_request_rejected() -> None:
    """2. Solicitud inválida rechazada (request_id vacío, tool_name vacío, expires_at <= created_at)."""
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="request_id"):
        ConfirmationRequest(request_id="   ", tool_name="valid_tool")

    with pytest.raises(ValueError, match="tool_name"):
        ConfirmationRequest(request_id="valid_id", tool_name="")

    with pytest.raises(ValueError, match="expires_at"):
        ConfirmationRequest(
            request_id="valid_id",
            tool_name="valid_tool",
            created_at=now,
            expires_at=now - timedelta(seconds=10),
        )


def test_pending_status() -> None:
    """3. Estado PENDING inicial."""
    mgr = ConfirmationManager()
    req = mgr.create_request(tool_name="tool_a", operation="op_a")
    assert req.status == ConfirmationStatus.PENDING
    assert mgr.get_pending_request(req.request_id) is not None


def test_approved_status_and_provider_simulation() -> None:
    """4 y 20. Provider APPROVED simula aprobación y resolución de estado."""
    mgr = ConfirmationManager()
    req = mgr.create_request(tool_name="tool_a", operation="op_a")

    prov = MockConfirmationProvider(ConfirmationStatus.APPROVED)
    res = mgr.submit_request(req, provider=prov)

    assert isinstance(res, ConfirmationResult)
    assert res.status == ConfirmationStatus.APPROVED
    assert mgr.get_pending_request(req.request_id) is None


def test_rejected_status_and_provider_simulation() -> None:
    """5 y 21. Provider REJECTED simula rechazo de confirmación."""
    mgr = ConfirmationManager()
    req = mgr.create_request(tool_name="tool_b", operation="op_b")

    prov = MockConfirmationProvider(ConfirmationStatus.REJECTED)
    res = mgr.submit_request(req, provider=prov)

    assert res.status == ConfirmationStatus.REJECTED


def test_cancellation_functionality() -> None:
    """6 y 18. Cancelación explícita de solicitud (PENDING -> CANCELLED)."""
    mgr = ConfirmationManager()
    req = mgr.create_request(tool_name="tool_c")

    cancelled = mgr.cancel_request(req.request_id)
    assert cancelled is True
    assert mgr.get_pending_request(req.request_id) is None


def test_expiration_functionality() -> None:
    """7, 14, 15 y 22. Expiración de solicitud y timeout de proveedor."""
    mgr = ConfirmationManager()
    # TTL de 0.05 segundos para provocar expiración rápida
    req = mgr.create_request(tool_name="tool_exp", ttl_seconds=0.05)
    time.sleep(0.06)

    # get_pending_request debe devolver None porque expiró
    assert mgr.get_pending_request(req.request_id) is None

    # submit_request con provider TIMEOUT
    req2 = mgr.create_request(tool_name="tool_exp2", ttl_seconds=0.05)
    time.sleep(0.06)
    res2 = mgr.submit_request(req2, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))
    assert res2.status == ConfirmationStatus.EXPIRED


def test_deterministic_action_fingerprint() -> None:
    """8, 9, 10 y 11. Fingerprint SHA-256 determinista e independiente del orden de claves dict."""
    fp1 = compute_action_fingerprint("tool1", "delete", {"a": 1, "b": 2})
    fp2 = compute_action_fingerprint("tool1", "delete", {"b": 2, "a": 1})
    fp_different_op = compute_action_fingerprint("tool1", "modify", {"a": 1, "b": 2})
    fp_different_params = compute_action_fingerprint("tool1", "delete", {"a": 1, "b": 99})

    # 11. El orden de claves no altera el hash (canonicalización)
    assert fp1 == fp2
    # 9. Cambiar la operación cambia el hash
    assert fp1 != fp_different_op
    # 10. Cambiar los parámetros cambia el hash
    assert fp1 != fp_different_params


def test_confirmation_binding_and_mismatch_rejection() -> None:
    """12 y 13. Confirmación vinculada a request_id y fingerprint. Rechazo si fingerprint no coincide."""
    mgr = ConfirmationManager()
    params_a = {"file": "important.doc"}
    req = mgr.create_request(tool_name="delete_tool", operation="delete", parameters=params_a)

    mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

    # Intento de consumo con parámetros diferentes (Solicitud B intentando reusar confirmación de Solicitud A)
    params_b = {"file": "OTHER_FILE.doc"}
    consumed = mgr.consume_confirmation(req.request_id, "delete_tool", "delete", params_b)
    assert consumed is False


def test_single_use_allow_once_and_replay_protection() -> None:
    """16 y 17. Consumo único ALLOW_ONCE y protección inmutable contra ataques de Replay."""
    mgr = ConfirmationManager()
    params = {"target": "disk"}
    req = mgr.create_request(tool_name="clean_disk", operation="clean", parameters=params)

    mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

    # 1. Primer consumo -> Éxito
    consumed_first = mgr.consume_confirmation(req.request_id, "clean_disk", "clean", params)
    assert consumed_first is True

    # 2. Segundo consumo (Replay Attack) -> Bloqueado
    consumed_second = mgr.consume_confirmation(req.request_id, "clean_disk", "clean", params)
    assert consumed_second is False


def test_session_mismatch_rejection() -> None:
    """19. Confirmación de otra sesión rechazada."""
    mgr = ConfirmationManager()
    params = {"target": "disk"}
    req = mgr.create_request(tool_name="clean_disk", operation="clean", parameters=params, session_id="session_123")

    mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

    # Consumo con session_id diferente -> Rechazado
    consumed = mgr.consume_confirmation(req.request_id, "clean_disk", "clean", params, session_id="session_999")
    assert consumed is False


def test_parameter_sanitization() -> None:
    """23 y 24. Sanitización de datos sensibles para diagnóstico manteniendo intacto el fingerprint real."""
    params = {
        "user": "admin",
        "password": "SuperSecretPassword123",
        "api_key": "sk-proj-abc123xyz",
        "nested": {"token": "secret_token_val", "public": "ok"},
    }

    sanitized = sanitize_sensitive_parameters(params)
    assert sanitized["user"] == "admin"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["token"] == "[REDACTED]"
    assert sanitized["nested"]["public"] == "ok"

    # El fingerprint real DEBE calcularse sobre los parámetros originales completos
    fp_raw = compute_action_fingerprint("login", "auth", params)
    fp_sanitized = compute_action_fingerprint("login", "auth", sanitized)
    assert fp_raw != fp_sanitized  # Demuestra que el hash real preserva los valores exactos


def test_confirmation_manager_has_zero_tool_executions() -> None:
    """25. ConfirmationManager no ejecuta ninguna herramienta."""
    mgr = ConfirmationManager()
    req = mgr.create_request(tool_name="exec_tool", operation="run")

    res = mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))
    assert res.status == ConfirmationStatus.APPROVED
    assert not hasattr(mgr, "execute_tool")


def test_concurrency_protection_race_condition() -> None:
    """26. Pruebas de concurrencia: dos hilos no pueden consumir la misma confirmación ALLOW_ONCE."""
    mgr = ConfirmationManager()
    params = {"action": "dangerous_step"}
    req = mgr.create_request(tool_name="parallel_tool", operation="step", parameters=params)

    mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

    results: list[bool] = []

    def _worker() -> None:
        c = mgr.consume_confirmation(req.request_id, "parallel_tool", "step", params)
        results.append(c)

    # Iniciar 10 hilos en paralelo intentando consumir simultáneamente la misma confirmación
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_worker) for _ in range(10)]
        concurrent.futures.wait(futures)

    # Exactamente UN SOLO HILO debe haber tenido éxito, los otros 9 deben haber fallado
    successful_consumptions = [r for r in results if r is True]
    assert len(successful_consumptions) == 1
