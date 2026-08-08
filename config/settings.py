"""Sistema de configuración tipado basado en Pydantic BaseSettings para Jessyca Windows MCP.

Soporta lectura automática de variables de entorno desde archivos .env y del sistema operativo.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.constants import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MCP_SERVER_NAME,
)
from core.types import EnvironmentMode, LogLevel


class AppSettings(BaseSettings):
    """Modelo de configuración principal de la aplicación."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Entorno y Logging
    ENVIRONMENT: EnvironmentMode = Field(
        default=EnvironmentMode.DEVELOPMENT,
        description="Entorno de ejecución (development, staging, production, testing).",
    )
    LOG_LEVEL: LogLevel = Field(
        default=LogLevel.INFO,
        description="Nivel de logging del sistema centralizado.",
    )
    LOG_FILE_PATH: Path | None = Field(
        default=None,
        description="Ruta personalizada para guardar los archivos de registro.",
    )

    # Configuración MCP Server
    MCP_SERVER_NAME: str = Field(
        default=DEFAULT_MCP_SERVER_NAME,
        description="Nombre identificador del servidor MCP.",
    )
    MCP_SERVER_HOST: str = Field(
        default="127.0.0.1",
        description="Host local donde se expone o comunica el servidor MCP.",
    )
    MCP_SERVER_PORT: int = Field(
        default=8000,
        description="Puerto para la comunicación del servidor MCP.",
    )

    # Opciones Específicas de Windows
    ENABLE_WINDOWS_NOTIFICATIONS: bool = Field(
        default=True,
        description="Habilita la integración de notificaciones nativas de Windows 10/11.",
    )
    STRICT_WINDOWS_ADMIN_CHECK: bool = Field(
        default=False,
        description="Si es True, exige permisos de administrador al iniciar servicios del sistema.",
    )

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def validate_environment(cls, value: str | EnvironmentMode) -> EnvironmentMode:
        if isinstance(value, EnvironmentMode):
            return value
        if isinstance(value, str):
            try:
                return EnvironmentMode(value.lower())
            except ValueError:
                return EnvironmentMode(DEFAULT_ENVIRONMENT)
        return EnvironmentMode(DEFAULT_ENVIRONMENT)

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def validate_log_level(cls, value: str | LogLevel) -> LogLevel:
        if isinstance(value, LogLevel):
            return value
        if isinstance(value, str):
            try:
                return LogLevel(value.upper())
            except ValueError:
                return LogLevel(DEFAULT_LOG_LEVEL)
        return LogLevel(DEFAULT_LOG_LEVEL)
