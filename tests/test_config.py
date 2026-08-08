"""Pruebas unitarias del sistema de configuración y lectura de .env."""

from __future__ import annotations

from config.manager import ConfigManager, get_settings
from config.settings import AppSettings
from core.types import EnvironmentMode, LogLevel


def test_app_settings_default_values() -> None:
    settings = AppSettings()
    assert settings.MCP_SERVER_NAME == "jessyca-windows-mcp"
    assert isinstance(settings.ENVIRONMENT, EnvironmentMode)
    assert isinstance(settings.LOG_LEVEL, LogLevel)


def test_config_manager_singleton() -> None:
    manager1 = ConfigManager()
    manager2 = ConfigManager()
    assert manager1 is manager2


def test_get_settings_helper() -> None:
    settings = get_settings()
    assert settings is not None
    assert settings.MCP_SERVER_PORT > 0
