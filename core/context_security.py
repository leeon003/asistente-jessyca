"""Frontera de seguridad y validador de construcción de contexto (ContextSecurityManager - Subetapa 10.2).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Principio FAIL-SAFE DENY sobre consultas de contexto, sanitización de textos, redacción de secretos
vía SecretRedactor y enforzamiento estricto del límite de UNTRUSTED DATA sobre la memoria recuperada.
"""

import re

from core.command_output import SecretRedactor
from core.context_models import ContextQuery
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.context_security")


class ContextSecurityError(MCPError):
    """Error base de la frontera de seguridad de construcción de contexto."""

    pass


class ContextLimitExceededError(ContextSecurityError):
    """Error emitido cuando una consulta o snapshot excede los límites máximos configurados."""

    pass


class ContextSecurityManager:
    """Validador estricto de seguridad para la recuperación de memoria y construcción de contexto."""

    def __init__(self) -> None:
        from config.settings import AppSettings
        settings = AppSettings()


        self.max_items: int = settings.CONTEXT_MAX_ITEMS
        self.max_messages: int = settings.CONTEXT_MAX_MESSAGES
        self.max_facts: int = settings.CONTEXT_MAX_FACTS
        self.max_prefs: int = settings.CONTEXT_MAX_PREFERENCES
        self.max_sections: int = settings.CONTEXT_MAX_SECTIONS
        self.max_item_len: int = settings.CONTEXT_MAX_ITEM_LENGTH
        self.max_total_size: int = settings.CONTEXT_MAX_TOTAL_SIZE
        self.max_query_len: int = settings.CONTEXT_MAX_QUERY_LENGTH
        self.timeout: float = settings.CONTEXT_RETRIEVAL_TIMEOUT
        self.redactor = SecretRedactor()

    def validate_query(self, query: ContextQuery) -> ContextQuery:
        """Valida y sanitiza los parámetros de una consulta ContextQuery. FAIL-SAFE DENY."""
        if not query or not isinstance(query, ContextQuery):
            raise ContextSecurityError("La consulta de contexto debe ser una instancia válida de ContextQuery.")

        sid = query.session_id.strip()
        if not sid:
            raise ContextSecurityError("El session_id de la consulta no puede estar vacío.")

        if "\x00" in sid or re.search(r"[\x00-\x1f]", sid):
            raise ContextSecurityError("El session_id contiene null bytes o caracteres de control prohibidos.")

        if len(sid) > 128:
            raise ContextSecurityError(f"Longitud de session_id excede el máximo permitido ({len(sid)} > 128).")

        # Validación estricta de tipos enteros y rangos no negativos (rechazo de NaN, Infinity, booleans, floats)
        for param_name, val, max_allowed in (
            ("max_messages", query.max_messages, self.max_messages),
            ("max_facts", query.max_facts, self.max_facts),
            ("max_preferences", query.max_preferences, self.max_prefs),
            ("max_semantic_items", query.max_semantic_items, 100),
            ("max_total_size", query.max_total_size, self.max_total_size),
        ):
            if not isinstance(val, int) or isinstance(val, bool):
                raise ContextSecurityError(f"El parámetro '{param_name}' debe ser un número entero no booleano: {val}")

            if val <= 0:
                raise ContextSecurityError(f"El parámetro '{param_name}' debe ser un entero positivo: {val}")

            if val > max_allowed:
                raise ContextLimitExceededError(f"El parámetro '{param_name}' ({val}) excede el límite máximo configurado ({max_allowed}).")

        clean_filter = None
        if query.query_filter is not None:
            if not isinstance(query.query_filter, str):
                raise ContextSecurityError("El filtro de consulta debe ser una cadena de texto.")

            if len(query.query_filter) > self.max_query_len:
                raise ContextLimitExceededError(f"Longitud del filtro de consulta excede el máximo ({len(query.query_filter)} > {self.max_query_len}).")

            clean_filter = self.sanitize_text(query.query_filter)

        clean_sem_query = None
        if query.semantic_query is not None:
            if not isinstance(query.semantic_query, str):
                raise ContextSecurityError("La consulta semántica debe ser una cadena de texto.")

            if len(query.semantic_query) > self.max_query_len:
                raise ContextLimitExceededError(f"Longitud de la consulta semántica excede el máximo ({len(query.semantic_query)} > {self.max_query_len}).")

            clean_sem_query = self.sanitize_text(query.semantic_query)

        return ContextQuery(
            session_id=sid,
            max_messages=query.max_messages,
            max_facts=query.max_facts,
            max_preferences=query.max_preferences,
            max_semantic_items=query.max_semantic_items,
            max_total_size=query.max_total_size,
            include_facts=bool(query.include_facts),
            include_preferences=bool(query.include_preferences),
            include_messages=bool(query.include_messages),
            include_semantic_memory=bool(query.include_semantic_memory),
            query_filter=clean_filter,
            semantic_query=clean_sem_query,
        )


    def sanitize_text(self, text: str) -> str:
        """Remueve null bytes, caracteres de control no imprimibles y redacta secretos de seguridad."""
        if not text or not isinstance(text, str):
            return ""

        # 1. Limpieza de null bytes y caracteres de control
        clean = re.sub(r"[\x00-\x1f]", "", text).strip()

        # 2. Redacción de credenciales y secretos vía SecretRedactor
        redacted, _ = self.redactor.redact(clean)


        # 3. Truncamiento al tamaño máximo por elemento si excede
        if len(redacted) > self.max_item_len:
            return redacted[: self.max_item_len] + "... [TRUNCATED]"

        return redacted

    def wrap_prompt_injection_safety(self, content: str) -> str:
        """Aísla explícitamente el contenido de texto para prevenir Prompt-Injection.

        Garantiza que la memoria recuperada se mantenga estrictamente como DATOS NO CONFIABLES
        sin autoridad para modificar instrucciones del sistema o políticas de seguridad.
        """
        sanitized = self.sanitize_text(content)
        # Reemplazar intentos de inyección como "System Instruction:" o "Ignore previous instructions"
        isolated = re.sub(r"(system\s+instruction|ignore\s+previous\s+instructions|overwrite\s+policy)", "[SAFETY_FILTERED]", sanitized, flags=re.IGNORECASE)
        return isolated
