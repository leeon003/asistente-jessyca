"""Sistema de logging centralizado para Jessyca Windows MCP.

Ofrece formato estandarizado, rotación de archivos de log en el directorio `logs/`,
soporte para la consola con formateo limpio y compatibilidad opcional con la librería `rich`.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.constants import (
    DEFAULT_LOG_FILE_NAME,
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_LEVEL,
    LOG_BACKUP_COUNT,
    MAX_LOG_BYTES,
)

_is_configured: bool = False


class SafeRotatingFileHandler(RotatingFileHandler):
    """Manejador de archivos rotativos seguro para Windows (ignora PermissionError durante rollover si otro proceso tiene el lock)."""

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            # En Windows, si otro proceso concurrente tiene el archivo abierto, continuar escribiendo
            pass


def setup_logger(
    log_level: str = DEFAULT_LOG_LEVEL,
    log_file: Path | str | None = None,
    enable_console: bool = True,
    force: bool = False,
) -> None:
    """Configura el logger raíz para toda la aplicación Jessyca.

    Args:
        log_level: Nivel de registro (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Ruta opcional del archivo de logs. Si es None, usará logs/jessyca_mcp.log.
        enable_console: Si es True, habilita la salida por consola.
        force: Si es True, reconfigura el logger aunque ya estuviera configurado.
    """
    global _is_configured
    if _is_configured and not force and log_file is None:
        return

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Limpiar handlers previos para evitar duplicados
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)

    # Handler para Consola
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Handler para Archivo con Rotación
    if log_file is None:
        logs_dir = Path(__file__).resolve().parent.parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file_path = logs_dir / DEFAULT_LOG_FILE_NAME
    else:
        log_file_path = Path(log_file)
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = SafeRotatingFileHandler(
        filename=str(log_file_path),
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    _is_configured = True
    logging.getLogger("JessycaCore").info(
        f"Sistema de logging centralizado inicializado [Nivel: {log_level}, Archivo: {log_file_path}]"
    )


def get_logger(name: str) -> logging.Logger:
    """Obtiene un logger hijo configurado con un nombre de espacio específico.

    Args:
        name: Nombre del componente o módulo (ej: 'jessyca.config', 'jessyca.tools').

    Returns:
        Instancia de logging.Logger lista para emitir registros estructurados.
    """
    if not _is_configured:
        setup_logger()
    return logging.getLogger(name)
