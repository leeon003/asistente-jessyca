"""Fixtures globales para la suite de pruebas Pytest de Jessyca Windows MCP."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from config.settings import AppSettings
from core.types import EnvironmentMode, LogLevel


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Proporciona un directorio temporal limpio para pruebas."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        yield Path(tmp)
        # Cerrar handlers de logging abiertos para evitar bloqueo de archivos en Windows
        logging.shutdown()
        for handler in logging.root.handlers[:]:
            handler.close()
            logging.root.removeHandler(handler)


@pytest.fixture
def mock_settings(temp_dir: Path) -> AppSettings:
    """Proporciona una instancia de AppSettings aislada para testing."""
    return AppSettings(
        ENVIRONMENT=EnvironmentMode.TESTING,
        LOG_LEVEL=LogLevel.DEBUG,
        LOG_FILE_PATH=temp_dir / "test.log",
        MCP_SERVER_NAME="test-mcp-server",
        MCP_SERVER_HOST="127.0.0.1",
        MCP_SERVER_PORT=9999,
        ENABLE_WINDOWS_NOTIFICATIONS=False,
        STRICT_WINDOWS_ADMIN_CHECK=False,
    )


@pytest.fixture(autouse=True)
def reset_emergency_stop() -> Generator[None, None, None]:
    """Garantiza aislamiento estricto del estado de Parada de Emergencia entre tests."""
    from core.emergency_stop import EmergencyStopManager

    manager = EmergencyStopManager.get_instance()
    manager.reset("test_setup_cleanup")
    yield
    manager.reset("test_teardown_cleanup")
