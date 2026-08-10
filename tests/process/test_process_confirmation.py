"""Pruebas de la integración de ConfirmationManager con terminate_process (Subetapa 06.3)."""

from __future__ import annotations

from core.confirmation import ConfirmationStatus, MockConfirmationProvider
from server.app import JessycaMCPServer
from server.boundary import ExecutionStatus
from server.pipeline import SecureExecutionPipeline


def test_terminate_process_requires_confirmation_and_denies_on_rejection() -> None:
    pipeline = SecureExecutionPipeline()
    server = JessycaMCPServer(pipeline=pipeline)
    server.start()

    # Proveedor de confirmación que RECHAZA la solicitud
    provider_rejected = MockConfirmationProvider(ConfirmationStatus.REJECTED)

    res_rejected = server.handle_request(
        {
            "tool_name": "windows.process",
            "operation": "terminate_process",
            "parameters": {"pid": 9876},
        },
        confirmation_provider=provider_rejected,
    )

    assert res_rejected.status == ExecutionStatus.DENIED
    assert "Confirmación" in res_rejected.message or "Denegado" in res_rejected.message

    server.shutdown()
