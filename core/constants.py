"""Constantes globales del proyecto Jessyca Windows MCP.

Este módulo centraliza todas las constantes utilizadas en el sistema para evitar
hardcoding y garantizar coherencia en toda la aplicación.
"""

from __future__ import annotations

from typing import Final

# Información general de la aplicación
APP_NAME: Final[str] = "Jessyca Windows MCP"
APP_VERSION: Final[str] = "0.1.0"
APP_DESCRIPTION: Final[str] = (
    "Asistente con arquitectura MCP (Model Context Protocol) optimizado para Windows 10 y 11."
)
ORGANIZATION_NAME: Final[str] = "Jessyca Open Source"

# Requisitos del sistema operativo
WINDOWS_MIN_MAJOR_VERSION: Final[int] = 10
WINDOWS_MIN_BUILD_WIN10: Final[int] = 19041  # Windows 10 Version 2004 (May 2020 Update)
WINDOWS_MIN_BUILD_WIN11: Final[int] = 22000  # Windows 11 21H2

# Configuraciones predeterminadas de Logging
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
DEFAULT_LOG_FORMAT: Final[str] = (
    "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
)
DEFAULT_LOG_FILE_NAME: Final[str] = "jessyca_mcp.log"
MAX_LOG_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT: Final[int] = 5

# Configuraciones predeterminadas de Servidor y MCP
DEFAULT_ENVIRONMENT: Final[str] = "development"
DEFAULT_MCP_SERVER_NAME: Final[str] = "jessyca-windows-mcp"
DEFAULT_MCP_SERVER_VERSION: Final[str] = APP_VERSION
DEFAULT_CONFIG_FILE_NAME: Final[str] = ".env"
