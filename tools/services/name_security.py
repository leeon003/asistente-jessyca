"""Gestor de seguridad y saneamiento para nombres de Servicios de Windows (Subetapa 06.5).

Trata todos los nombres de servicio recibidos como UNTRUSTED INPUT.
Filtra patrones de inyección de comandos (&, |, ;, comillas, $(), sc.exe, powershell),
revisa caracteres nulos (\x00), caracteres de control y límites de longitud (`SERVICES_MAX_NAME_LENGTH`).
"""

from __future__ import annotations

import re

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.logger import get_logger
from tools.services.errors import ServiceNameError

logger = get_logger("jessyca.tools.services.name_security")

# Caracteres de inyección prohibidos expresamente
FORBIDDEN_INJECTION_CHARS = set("&|;\"'`$<>(){}[]\n\r\t")
FORBIDDEN_KEYWORDS_REGEX = re.compile(
    r"(sc\.exe|powershell|cmd\.exe|subprocess|os\.system|Invoke-Expression|Start-Process)",
    re.IGNORECASE,
)


class ServiceNameSecurityManager:
    """Gestor de seguridad de nombres de servicios de Windows."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.max_name_length: int = settings.SERVICES_MAX_NAME_LENGTH
        self.audit_logger = get_audit_logger()

    def validate_and_sanitize_name(self, raw_service_name: object) -> str:
        """Valida, limpia y enforza las reglas de seguridad sobre el nombre de un servicio."""
        if raw_service_name is None or not isinstance(raw_service_name, str):
            raise ServiceNameError("El nombre del servicio debe ser una cadena de texto no vacía.")

        clean_name = raw_service_name.strip()
        if not clean_name:
            raise ServiceNameError("El nombre del servicio no puede estar vacío.")

        # 1. Detección de caracteres nulos
        if "\x00" in clean_name:
            raise ServiceNameError("El nombre del servicio contiene caracteres nulos (null bytes).")

        # 2. Detección de límite de longitud
        if len(clean_name) > self.max_name_length:
            raise ServiceNameError(
                f"Longitud del nombre del servicio excedida ({len(clean_name)}). Máximo permitido: {self.max_name_length}."
            )

        # 3. Detección de caracteres prohibidos de inyección de comandos
        if any(char in clean_name for char in FORBIDDEN_INJECTION_CHARS):
            logger.warning(f"[SERVICE SECURITY DENY] Intento de inyección de caracteres en nombre de servicio: '{clean_name}'")
            raise ServiceNameError("El nombre del servicio contiene caracteres especiales no permitidos.")

        # 4. Detección de palabras clave prohibidas
        if FORBIDDEN_KEYWORDS_REGEX.search(clean_name):
            logger.warning(f"[SERVICE SECURITY DENY] Intento de inyección de comando en nombre de servicio: '{clean_name}'")
            raise ServiceNameError("Patrón de comando no permitido detectado en el nombre del servicio.")

        # 5. Registrar evento de auditoría
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.SERVICE_NAME_VALIDATED,
                tool_name="windows.services",
                operation="validate_name",
                reason="Nombre del servicio validado exitosamente.",
                metadata={"service_name": clean_name},
            )
        )

        return clean_name
