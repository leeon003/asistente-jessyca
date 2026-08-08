"""Session Manager para Jessyca Windows MCP.

Administra el ciclo de vida de cada sesión de ejecución (ID único, inicio/fin, usuario,
herramientas utilizadas, registro de errores, duración) y exportación a JSON o Markdown.
Totalmente independiente de cualquier Tool o LLM específico.
"""

from __future__ import annotations

import getpass
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.session")


@dataclass
class ToolExecutionLog:
    """Registro inmutable de la ejecución de una herramienta dentro de una sesión."""

    tool_name: str
    arguments: dict[str, Any]
    is_success: bool
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "is_success": self.is_success,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Session:
    """Registro completo del ciclo de vida y métricas de una sesión de ejecución."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime | None = None
    user: str = field(default_factory=getpass.getuser)
    tools_used: list[ToolExecutionLog] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def end(self) -> Session:
        """Finaliza la sesión activa calculando la hora de fin y la duración total."""
        if not self.is_active:
            return self

        self.end_time = datetime.now(UTC)
        self.duration_seconds = round((self.end_time - self.start_time).total_seconds(), 2)
        self.is_active = False
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convierte la sesión en un diccionario serializable."""
        return {
            "session_id": self.session_id,
            "user": self.user,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "is_active": self.is_active,
            "tools_used_count": len(self.tools_used),
            "errors_count": len(self.errors),
            "tools_used": [t.to_dict() for t in self.tools_used],
            "errors": self.errors,
            "metadata": self.metadata,
        }

    def export_json(self, file_path: Path | str | None = None) -> str:
        """Exporta la sesión en formato JSON estandarizado.

        Args:
            file_path: Ruta opcional para guardar el archivo JSON. Si es None, solo devuelve el string JSON.

        Returns:
            String JSON generado.
        """
        content = json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        if file_path:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return content

    def export_markdown(self, file_path: Path | str | None = None) -> str:
        """Exporta un informe legible de la sesión en formato Markdown.

        Args:
            file_path: Ruta opcional donde guardar el informe Markdown.

        Returns:
            String Markdown generado.
        """
        end_str = self.end_time.isoformat() if self.end_time else "En ejecución"
        lines = [
            f"# Reporte de Sesión MCP - ID: `{self.session_id}`",
            "",
            f"- **Usuario**: {self.user}",
            f"- **Hora de Inicio**: {self.start_time.isoformat()}",
            f"- **Hora de Fin**: {end_str}",
            f"- **Duración Total**: {self.duration_seconds} segundos",
            f"- **Estado**: {'Activa' if self.is_active else 'Finalizada'}",
            f"- **Herramientas Ejecutadas**: {len(self.tools_used)}",
            f"- **Errores Registrados**: {len(self.errors)}",
            "",
            "## Herramientas Utilizadas",
        ]

        if not self.tools_used:
            lines.append("_No se ejecutó ninguna herramienta durante esta sesión._")
        else:
            for idx, log in enumerate(self.tools_used, 1):
                status = "✅ Éxito" if log.is_success else "❌ Fallo"
                lines.append(f"### {idx}. `{log.tool_name}` ({status})")
                lines.append(f"- **Hora**: {log.timestamp.isoformat()}")
                lines.append(f"- **Argumentos**: `{log.arguments}`")
                if log.error:
                    lines.append(f"- **Error**: `{log.error}`")
                lines.append("")

        if self.errors:
            lines.append("## Registro de Errores")
            for idx, err in enumerate(self.errors, 1):
                lines.append(f"- **{idx}**. `{err.get('message')}` ({err.get('timestamp')})")

        content = "\n".join(lines)
        if file_path:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return content


class SessionManager:
    """Gestor del ciclo de vida y auditoría de sesiones para Jessyca Windows MCP."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._active_session: Session | None = None

    def start_session(self, user: str | None = None, metadata: dict[str, Any] | None = None) -> Session:
        """Inicia una nueva sesión de ejecución finalizando cualquier sesión previa en curso.

        Args:
            user: Nombre del usuario opcional. Si es None, utiliza el usuario del sistema operativo.
            metadata: Metadatos adicionales asociados a la sesión.

        Returns:
            Instancia de la nueva Session activa.
        """
        if self._active_session and self._active_session.is_active:
            logger.info(f"Finalizando sesión activa previa '{self._active_session.session_id}'...")
            self.end_session()

        session = Session(
            user=user or getpass.getuser(),
            metadata=metadata or {},
        )
        self._sessions[session.session_id] = session
        self._active_session = session
        logger.info(f"Nueva sesión iniciada ID: '{session.session_id}' por usuario: '{session.user}'")
        return session

    def get_active_session(self) -> Session | None:
        """Obtiene la sesión actualmente en curso."""
        return self._active_session

    def record_tool_usage(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        is_success: bool,
        error: str | None = None,
    ) -> None:
        """Registra el uso de una herramienta MCP dentro de la sesión activa."""
        session = self.get_active_session()
        if not session or not session.is_active:
            # Si no hay sesión activa, inicia una sesión por defecto
            session = self.start_session(metadata={"auto_started": True})

        log_entry = ToolExecutionLog(
            tool_name=tool_name,
            arguments=arguments,
            is_success=is_success,
            error=error,
        )
        session.tools_used.append(log_entry)
        logger.info(f"Sesión [{session.session_id}]: Herramienta registrada '{tool_name}' (Éxito: {is_success})")

    def record_error(self, error_message: str, details: dict[str, Any] | None = None) -> None:
        """Registra un error o excepción dentro de la sesión activa."""
        session = self.get_active_session()
        if not session or not session.is_active:
            session = self.start_session(metadata={"auto_started": True})

        err_entry = {
            "message": error_message,
            "details": details or {},
            "timestamp": datetime.now(UTC).isoformat(),
        }
        session.errors.append(err_entry)
        logger.warning(f"Sesión [{session.session_id}]: Error registrado - {error_message}")

    def end_session(self) -> Session | None:
        """Finaliza la sesión activa calculando la hora de fin y duración."""
        if not self._active_session or not self._active_session.is_active:
            logger.warning("No hay ninguna sesión activa para finalizar.")
            return self._active_session

        session = self._active_session.end()
        logger.info(
            f"Sesión finalizada ID: '{session.session_id}' [Duración: {session.duration_seconds}s, Herramientas: {len(session.tools_used)}]"
        )
        self._active_session = None
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Obtiene una sesión registrada por su ID."""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        """Devuelve la lista completa de sesiones registradas."""
        return list(self._sessions.values())

    def export_session(
        self,
        session_id: str,
        format: str = "json",
        file_path: Path | str | None = None,
    ) -> str:
        """Exporta los datos de una sesión por ID en formato JSON o Markdown.

        Args:
            session_id: ID único de la sesión.
            format: 'json' o 'markdown'.
            file_path: Ruta opcional donde guardar el archivo.

        Returns:
            Contenido exportado.
        """
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Sesión con ID '{session_id}' no encontrada.")

        fmt = format.lower().strip()
        if fmt == "json":
            return session.export_json(file_path=file_path)
        elif fmt in ("markdown", "md"):
            return session.export_markdown(file_path=file_path)
        else:
            raise ValueError(f"Formato de exportación '{format}' no soportado. Usar 'json' o 'markdown'.")
