"""Pruebas de fuzzing controlado para la frontera de seguridad de conexiones de red (Subetapa 09.2)."""

from __future__ import annotations

import pytest

from core.network_connection_models import NetworkConnectionRequest
from core.network_connection_security import (
    NetworkConnectionLimitExceededError,
    NetworkConnectionSecurityError,
    NetworkConnectionSecurityManager,
)


def test_controlled_connection_fuzzing() -> None:
    sec = NetworkConnectionSecurityManager()

    invalid_requests = [
        NetworkConnectionRequest(local_port=-10),
        NetworkConnectionRequest(local_port=70000),
        NetworkConnectionRequest(remote_port=-5),
        NetworkConnectionRequest(remote_port=99999),
        NetworkConnectionRequest(process_id=-100),
        NetworkConnectionRequest(protocol="INVALID_PROT"),
        NetworkConnectionRequest(max_results=-10),
        NetworkConnectionRequest(max_results=0),
        NetworkConnectionRequest(max_results=999999),
        NetworkConnectionRequest(local_address="256.256.256.256"),
    ]

    for req in invalid_requests:
        with pytest.raises((NetworkConnectionSecurityError, NetworkConnectionLimitExceededError)):
            sec.validate_request(req)
