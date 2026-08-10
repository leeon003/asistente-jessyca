"""Frontera de seguridad y validador de estado de sesión (SessionSecurityManager - Subetapa 10.1).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Aplica el principio FAIL-SAFE DENY sobre el estado de sesión, mensajes, hechos y preferencias.
Invocación de SecretRedactor, validación de transiciones de estado, sanitización contra null bytes y caracteres de control.
"""

from __future__ import annotations

import re

from core.command_output import SecretRedactor
from core.exceptions import MCPError
from core.logger import get_logger
from core.session_models import (
    SessionId,
    SessionState,
    SessionStatus,
)

logger = get_logger("jessyca.core.session_security")


class SessionSecurityError(MCPError):
    """Error base de la frontera de seguridad de sesión."""

    pass


class SessionLimitExceededError(SessionSecurityError):
    """Error emitido cuando una sesión excede los límites máximos configurados."""

    pass


class SessionSecurityManager:
    """Validador estricto de seguridad para la gestión de estado de sesión y memoria de usuario."""

    def __init__(self) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.max_sessions: int = settings.SESSION_MAX_ACTIVE_SESSIONS
        self.max_messages: int = settings.SESSION_MAX_MESSAGES
        self.max_msg_len: int = settings.SESSION_MAX_MESSAGE_LENGTH
        self.max_facts: int = settings.SESSION_MAX_FACTS
        self.max_prefs: int = settings.SESSION_MAX_PREFERENCES
        self.max_entry_len: int = settings.SESSION_MAX_MEMORY_ENTRY_LENGTH
        self.redactor = SecretRedactor()

    def validate_session_id(self, session_id: str | SessionId) -> SessionId:
        """Valida y convierte la representación de SessionId. FAIL-SAFE DENY."""
        val = str(session_id).strip()
        if not val:
            raise SessionSecurityError("El identificador de sesión no puede estar vacío.")

        if "\x00" in val or re.search(r"[\x00-\x1f]", val):
            raise SessionSecurityError("El SessionId contiene null bytes o caracteres de control prohibidos.")

        if len(val) > 128:
            raise SessionSecurityError(f"Longitud de SessionId excede el máximo permitido ({len(val)} > 128).")

        return SessionId(value=val)

    def validate_status_transition(self, current_status: SessionStatus, new_status: SessionStatus) -> None:
        """Valida las transiciones de estado permitidas.

        FAIL-SAFE DENY: Sesiones en EMERGENCY_STOPPED, CANCELLED o EXPIRED no pueden ser reactivadas.
        """
        if current_status in (SessionStatus.EMERGENCY_STOPPED, SessionStatus.CANCELLED, SessionStatus.EXPIRED):
            if new_status != current_status:
                raise SessionSecurityError(f"Transición de estado denegada: La sesión está en estado terminal '{current_status}'.")

    def sanitize_text(self, text: str) -> str:
        """Remueve null bytes, caracteres de control no imprimibles y redacta secretos sensibles."""
        if not text or not isinstance(text, str):
            return ""

        # 1. Limpieza de null bytes y caracteres de control
        clean = re.sub(r"[\x00-\x1f]", "", text).strip()

        # 2. Redacción de credenciales y secretos vía SecretRedactor
        redacted, _ = self.redactor.redact(clean)
        return redacted


    def validate_message(self, content: str) -> str:
        """Valida y sanitiza un nuevo mensaje de sesión."""
        if not content or not isinstance(content, str):
            raise SessionSecurityError("El contenido del mensaje debe ser una cadena no vacía.")

        if len(content) > self.max_msg_len:
            raise SessionLimitExceededError(f"Longitud de mensaje excede el límite máximo ({len(content)} > {self.max_msg_len}).")

        return self.sanitize_text(content)

    def validate_fact(self, key: str, value: str, confidence: float) -> tuple[str, str, float]:
        """Valida y sanitiza una entrada de hecho (fact) de memoria."""
        if not key or not isinstance(key, str) or not value or not isinstance(value, str):
            raise SessionSecurityError("La clave y el valor del fact deben ser cadenas no vacías.")

        if len(key) > self.max_entry_len or len(value) > self.max_entry_len:
            raise SessionLimitExceededError(f"Longitud de fact excede el límite máximo permitido ({self.max_entry_len}).")

        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise SessionSecurityError("La confianza debe ser un número en el rango [0.0, 1.0].")

        if not (0.0 <= confidence <= 1.0):
            raise SessionSecurityError(f"Confianza fuera del rango válido [0.0, 1.0]: {confidence}")

        clean_key = self.sanitize_text(key)
        clean_val = self.sanitize_text(value)
        return clean_key, clean_val, float(confidence)

    def validate_preference(self, key: str, value: str) -> tuple[str, str]:
        """Valida y sanitiza una preferencia de usuario."""
        if not key or not isinstance(key, str) or not value or not isinstance(value, str):
            raise SessionSecurityError("La clave y el valor de la preferencia deben ser cadenas no vacías.")

        if len(key) > self.max_entry_len or len(value) > self.max_entry_len:
            raise SessionLimitExceededError(f"Longitud de preferencia excede el límite máximo ({self.max_entry_len}).")

        clean_key = self.sanitize_text(key)
        clean_val = self.sanitize_text(value)
        return clean_key, clean_val

    def validate_state_limits(self, state: SessionState) -> None:
        """Valida los límites globales del objeto SessionState."""
        if len(state.messages) > self.max_messages:
            raise SessionLimitExceededError(f"Cantidad de mensajes excede el límite máximo ({len(state.messages)} > {self.max_messages}).")

        if len(state.facts) > self.max_facts:
            raise SessionLimitExceededError(f"Cantidad de hechos (facts) excede el límite máximo ({len(state.facts)} > {self.max_facts}).")

        if len(state.preferences) > self.max_prefs:
            raise SessionLimitExceededError(f"Cantidad de preferencias excede el límite máximo ({len(state.preferences)} > {self.max_prefs}).")
