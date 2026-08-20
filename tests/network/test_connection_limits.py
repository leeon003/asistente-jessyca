"""Pruebas de enforzamiento de límites de resultados de conexiones (Subetapa 09.2)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.network_connection_models import (
    ActiveNetworkConnection,
    NetworkConnectionMetadata,
    NetworkConnectionsResult,
    NetworkEndpoint,
)
from core.network_connection_security import NetworkConnectionSecurityManager


def test_connection_security_truncates_excessive_results() -> None:
    sec = NetworkConnectionSecurityManager()
    sec.max_connections = 2

    conns = tuple(
        ActiveNetworkConnection(
            protocol="TCP",
            local_endpoint=NetworkEndpoint(address="10.0.0.1", port=1000 + i),
            remote_endpoint=None,
            status="ESTABLISHED",
            process_id=100,
            process_name="app.exe",
            family="IPv4",
        )
        for i in range(10)
    )

    res = NetworkConnectionsResult(
        success=True,
        connections=conns,
        listening_ports=(),
        metadata=NetworkConnectionMetadata(10, 10, False, 1.0, "Mock", datetime.now(UTC)),
        message="OK",
    )

    sanitized = sec.validate_result(res)

    assert len(sanitized.connections) == 2
