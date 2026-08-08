"""Audit Logger para Jessyca Windows MCP.

Proporciona registro estructurado, inmutable y auditable de operaciones del sistema,
almacenando exactamente los 8 campos clave: usuario, acción, herramienta, riesgo,
resultado, fecha, duración (milisegundos) y tipo de autorización.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.event_bus import EventBus, get_event_bus
from core.logger import get_logger
from core.security import PermissionAction, RiskLevel

logger = get_logger("jessyca.audit_logger")


@dataclass
class AuditLogEntry:
    """Entrada estructurada inmutable para el historial de auditoría de seguridad y ejecución."""

    usuario: str
    accion: str
    herramienta: str
    riesgo: RiskLevel
    resultado: str
    fecha: datetime
    duracion_ms: float
    autorizacion: PermissionAction
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convierte la entrada a un diccionario serializable."""
        return {
            "entry_id": self.entry_id,
            "usuario": self.usuario,
            "accion": self.accion,
            "herramienta": self.herramienta,
            "riesgo": self.riesgo.value if isinstance(self.riesgo, RiskLevel) else str(self.riesgo),
            "resultado": self.resultado,
            "fecha": self.fecha.isoformat(),
            "duracion_ms": self.duracion_ms,
            "autorizacion": (
                self.autorizacion.value if isinstance(self.autorizacion, PermissionAction) else str(self.autorizacion)
            ),
            "details": self.details,
        }


class AuditLogger:
    """Gestor principal de logs de auditoría estructurados."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or get_event_bus()
        self._entries: list[AuditLogEntry] = []

    def log_event(
        self,
        usuario: str,
        accion: str,
        herramienta: str,
        riesgo: RiskLevel,
        resultado: str,
        duracion_ms: float,
        autorizacion: PermissionAction,
        details: dict[str, Any] | None = None,
    ) -> AuditLogEntry:
        """Registra un nuevo evento de auditoría con los 8 campos obligatorios.

        Args:
            usuario: Identificador del usuario o servicio.
            accion: Acción ejecutada (ej. 'read', 'delete', 'write', 'execute').
            herramienta: Nombre de la herramienta MCP.
            riesgo: Nivel de riesgo asignado.
            resultado: Resultado de la llamada ('SUCCESS', 'FAILURE', 'DENIED', 'BLOCKED', 'ERROR').
            duracion_ms: Duración en milisegundos.
            autorizacion: Acción de autorización ('ALLOW', 'DENY', 'ASK', 'ALLOW_ONCE', 'ALWAYS_ALLOW').
            details: Detalles adicionales opcionales.

        Returns:
            AuditLogEntry creada y almacenada.
        """
        entry = AuditLogEntry(
            usuario=usuario.strip(),
            accion=accion.strip(),
            herramienta=herramienta.strip(),
            riesgo=riesgo,
            resultado=resultado.strip(),
            fecha=datetime.now(UTC),
            duracion_ms=round(duracion_ms, 2),
            autorizacion=autorizacion,
            details=details or {},
        )

        self._entries.append(entry)
        logger.info(
            f"Auditoría registrada: User='{entry.usuario}' Tool='{entry.herramienta}' Action='{entry.accion}' Risk='{entry.riesgo.value}' Result='{entry.resultado}' Duration={entry.duracion_ms}ms Auth='{entry.autorizacion.value}'"
        )

        # Publicar evento en el EventBus
        self.event_bus.publish("audit:logged", entry.to_dict())
        return entry

    def get_logs(
        self,
        user_filter: str | None = None,
        tool_filter: str | None = None,
        result_filter: str | None = None,
        limit: int | None = None,
    ) -> list[AuditLogEntry]:
        """Obtiene la lista de entradas de auditoría aplicando filtros opcionales."""
        filtered = self._entries

        if user_filter:
            uf = user_filter.strip().lower()
            filtered = [e for e in filtered if e.usuario.lower() == uf]

        if tool_filter:
            tf = tool_filter.strip().lower()
            filtered = [e for e in filtered if e.herramienta.lower() == tf]

        if result_filter:
            rf = result_filter.strip().lower()
            filtered = [e for e in filtered if e.resultado.lower() == rf]

        if limit is not None:
            filtered = filtered[-limit:]

        return list(filtered)

    def export_logs_json(self) -> str:
        """Exporta el historial completo de auditoría en formato JSON estructurado."""
        data = [entry.to_dict() for entry in self._entries]
        return json.dumps(data, indent=2, ensure_ascii=False)

    def export_logs_csv(self) -> str:
        """Exporta el historial completo de auditoría en formato CSV estandarizado."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Encabezados de los 8 campos obligatorios + entry_id
        writer.writerow(
            ["entry_id", "usuario", "accion", "herramienta", "riesgo", "resultado", "fecha", "duracion_ms", "autorizacion"]
        )

        for entry in self._entries:
            writer.writerow(
                [
                    entry.entry_id,
                    entry.usuario,
                    entry.accion,
                    entry.herramienta,
                    entry.riesgo.value,
                    entry.resultado,
                    entry.fecha.isoformat(),
                    entry.duracion_ms,
                    entry.autorizacion.value,
                ]
            )

        return output.getvalue()

    def clear_logs(self) -> None:
        """Limpia el historial de auditoría en memoria."""
        self._entries.clear()
        logger.info("Historial de auditoría en memoria limpiado.")


# Instancia Singleton Global de AuditLogger
_global_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Obtiene la instancia global del AuditLogger."""
    global _global_audit_logger
    if _global_audit_logger is None:
        _global_audit_logger = AuditLogger()
    return _global_audit_logger
