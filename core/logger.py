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


def _write_emergency_log_diagnostic(handler_name: str, record: logging.LogRecord, exc_info: Any) -> None:
    """Diagnóstico alternativo estructurado cuando falla la emisión de logs en un handler."""
    try:
        import traceback
        from datetime import UTC, datetime

        err_msg = str(exc_info[1]) if exc_info and len(exc_info) > 1 and exc_info[1] else "Error desconocido"
        tb_lines = "".join(traceback.format_exception(*exc_info)) if exc_info and exc_info[0] else ""
        diag_line = (
            f"[{datetime.now(UTC).isoformat()}] [LOGGING_DIAGNOSTIC_FALLBACK] "
            f"Fallo en {handler_name}: {err_msg} | Record: '{getattr(record, 'msg', '')}'\n{tb_lines}\n"
        )

        emergency_file = Path(__file__).resolve().parent.parent / "logs" / "emergency_logging_errors.log"
        emergency_file.parent.mkdir(parents=True, exist_ok=True)
        with open(emergency_file, "a", encoding="utf-8", errors="replace") as f:
            f.write(diag_line)

        if sys.__stderr__:
            if hasattr(sys.__stderr__, "buffer") and sys.__stderr__.buffer:
                sys.__stderr__.buffer.write(diag_line.encode("utf-8", errors="replace"))
                sys.__stderr__.buffer.flush()
            else:
                sys.__stderr__.write(diag_line)
                sys.__stderr__.flush()
    except Exception:
        pass


class SafeRotatingFileHandler(RotatingFileHandler):
    """Manejador de archivos rotativos seguro para Windows (ignora PermissionError durante rollover si otro proceso tiene el lock)."""

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            # En Windows, si otro proceso concurrente tiene el archivo abierto, continuar escribiendo
            pass

    def handleError(self, record: logging.LogRecord) -> None:
        _write_emergency_log_diagnostic(self.__class__.__name__, record, sys.exc_info())


import sys
from typing import Any

# Asegurar codificación UTF-8 en streams de Windows para prevenir UnicodeEncodeError en consola
for _s in (sys.stdout, sys.stderr):
    if _s and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


class SafeStreamHandler(logging.StreamHandler):
    """Manejador de stream de consola seguro contra fallos de codificación Unicode en Windows."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            stream = self.stream
            # 1. Si el stream posee buffer binario (stdout/stderr en Python), escribir bytes directamente
            if hasattr(stream, "buffer") and stream.buffer:
                enc = getattr(stream, "encoding", "utf-8") or "utf-8"
                b = (msg + self.terminator).encode(enc, errors="replace")
                stream.buffer.write(b)
                stream.buffer.flush()
                return
            # 2. Si no tiene buffer, escribir de forma segura en texto
            stream.write(msg + self.terminator)
            self.flush()
        except RecursionError:
            raise
        except Exception:
            try:
                msg = self.format(record)
                enc = getattr(self.stream, "encoding", "ascii") or "ascii"
                safe_msg = msg.encode("ascii", errors="replace").decode("ascii")
                self.stream.write(safe_msg + self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:
        _write_emergency_log_diagnostic(self.__class__.__name__, record, sys.exc_info())


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
        console_handler = SafeStreamHandler()
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
