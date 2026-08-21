"""Validador estructural de eventos proactivos (event_validator.py - Fase 27).

Garantiza la integridad sintáctica, desinfección de caracteres nulos y validación de origen
de los eventos proactivos antes de cualquier evaluación de política.

INVARIANTE:
EVENT OUTPUT = UNTRUSTED DATA (Todo evento es hostil hasta validar su estructura y origen).
"""

from __future__ import annotations

import re

from core.command_output import SecretRedactor
from core.exceptions import MCPError
from core.logger import get_logger
from core.proactive.proactive_models import ProactiveEvent, ProactiveEventType

logger = get_logger("jessyca.proactive.validator")

TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+)*$")


class ProactiveEventValidationError(MCPError):
    """Error emitido cuando un evento proactivo no cumple los requisitos estructurales."""

    pass


class ProactiveEventValidator:
    """Validador estricto de eventos entrantes para el Asistente Proactivo."""

    @staticmethod
    def validate(event: ProactiveEvent) -> tuple[bool, str | None]:
        """Valida la estructura e integridad de un ProactiveEvent."""
        # 1. Validar ID
        if not event.event_id or not isinstance(event.event_id, str) or not event.event_id.strip():
            return False, "Identificador de evento 'event_id' inválido o vacío."

        # 2. Validar Tipo de Evento
        if not isinstance(event.event_type, ProactiveEventType):
            return False, f"Tipo de evento desconocido: {event.event_type}"

        # 3. Validar Origen (source)
        if not event.source or "\x00" in event.source:
            return False, "Origen 'source' de evento inválido o contiene caracteres nulos."

        # 4. Validar Summary
        if "\x00" in event.summary:
            return False, "El resumen del evento contiene caracteres nulos prohibidos."

        # 5. Validar Herramienta Propuesta si existe
        if event.proposed_tool is not None:
            tool_str = event.proposed_tool.strip()
            if not tool_str or not TOOL_NAME_PATTERN.match(tool_str):
                return False, f"Nombre de herramienta propuesta inválido: '{event.proposed_tool}'."

        return True, None

    @staticmethod
    def sanitize_summary(summary: str) -> str:
        """Sanitiza el resumen del evento eliminando secretos."""
        clean, _ = SecretRedactor.redact(summary.strip())
        return clean
