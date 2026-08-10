"""Pruebas de seguridad adversariales: Protección de Procesos del Sistema (Subetapa 06.3)."""

from __future__ import annotations

import pytest

from tools.process.errors import ProtectedProcessError
from tools.process.process_service import ProcessService


def test_protected_process_rejection_system_and_critical_services() -> None:
    service = ProcessService()

    protected_targets = [
        "System",
        "csrss.exe",
        "lsass.exe",
        "services.exe",
        "winlogon.exe",
        "svchost.exe",
        "explorer.exe",
    ]

    for target_name in protected_targets:

        assert service.is_protected_process(target_name) is True

    # Intentar terminar un nombre protegido debe lanzar ProtectedProcessError incluso con PID ficticio
    with pytest.raises(ProtectedProcessError):
        # Si un PID 4 corresponde a System en Windows
        service.terminate_process(4)
