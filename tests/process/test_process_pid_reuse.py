"""Pruebas de la Protección contra Reutilización de PID (PID Reuse Protection - Subetapa 06.3)."""

from __future__ import annotations

import os

import pytest

from tools.process.errors import PIDReuseError
from tools.process.process_service import ProcessService


def test_pid_reuse_name_mismatch_raises_error() -> None:
    service = ProcessService()
    current_pid = os.getpid()

    # Pasar un expected_name intencionadamente falso para forzar PID reuse mismatch
    fake_expected_name = "malicious_fake_app.exe"

    with pytest.raises(PIDReuseError):
        service.terminate_process(
            pid=current_pid,
            expected_name=fake_expected_name,
        )


def test_pid_reuse_creation_time_mismatch_raises_error() -> None:
    service = ProcessService()
    current_pid = os.getpid()
    info = service.get_process(current_pid)

    # Modificar el creation_time esperado por uno antiguo para forzar la detección
    fake_creation_time = info.creation_time - 5000.0

    with pytest.raises(PIDReuseError):
        service.terminate_process(
            pid=current_pid,
            expected_name=info.name,
            expected_creation_time=fake_creation_time,
        )
