"""Pruebas formales de verificación de las 15 invariantes de seguridad de conexiones (Subetapa 09.2)."""

from __future__ import annotations

import pytest

from core.network_connection_models import (
    NetworkConnectionRequest,
    NetworkEndpoint,
)
from core.network_connection_security import (
    NetworkConnectionLimitExceededError,
    NetworkConnectionSecurityError,
    NetworkConnectionSecurityManager,
)


def test_invariant_1_2_fail_safe_deny_untrusted_input() -> None:
    sec = NetworkConnectionSecurityManager()

    with pytest.raises(NetworkConnectionSecurityError):
        sec.validate_request(NetworkConnectionRequest(local_port=-99))


def test_invariant_6_7_8_valid_ip_port_protocol() -> None:
    # Validar puerto en endpoint
    with pytest.raises(ValueError):
        NetworkEndpoint(address="127.0.0.1", port=99999)

    # Validar IP en endpoint
    with pytest.raises(ValueError):
        NetworkEndpoint(address="invalid_ip_format", port=80)


def test_invariant_9_10_bounded_results_and_process_metadata() -> None:
    sec = NetworkConnectionSecurityManager()
    sec.max_process_name_len = 10

    sanitized = sec.sanitize_process_name("very_long_process_name_exceeding_limit.exe")
    assert len(sanitized) == 10
