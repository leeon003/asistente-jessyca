"""Gestor de seguridad de rutas del Registro de Windows (Subetapa 06.4).

Trata todas las rutas de hive y subclave como UNTRUSTED INPUT.
Canonicaliza el hive (HKCU -> HKEY_CURRENT_USER, HKLM -> HKEY_LOCAL_MACHINE), normaliza separadores,
verifica el catálogo de hives autorizados (`REGISTRY_ALLOWED_HIVES`), bloquea caracteres nulos (\x00)
y aplica límites estrictos de profundidad (`REGISTRY_MAX_DEPTH`).
"""

from __future__ import annotations

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.logger import get_logger
from tools.registry.errors import InvalidHiveError, RegistryDepthLimitError, RegistryPathError
from tools.registry.models import RegistryKeyPath

logger = get_logger("jessyca.tools.registry.path_security")

# Mapa canónico de equivalencias de hives
HIVE_MAP = {
    "HKCU": "HKEY_CURRENT_USER",
    "HKEY_CURRENT_USER": "HKEY_CURRENT_USER",
    "HKLM": "HKEY_LOCAL_MACHINE",
    "HKEY_LOCAL_MACHINE": "HKEY_LOCAL_MACHINE",
}


class RegistryPathSecurityManager:
    """Gestor de seguridad de rutas y validación de hives para el Registro de Windows."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.allowed_hives: set[str] = {h.strip().upper() for h in settings.REGISTRY_ALLOWED_HIVES}
        self.max_depth: int = settings.REGISTRY_MAX_DEPTH
        self.audit_logger = get_audit_logger()

    def validate_and_canonicalize(self, hive: object, key_path: object) -> RegistryKeyPath:
        """Valida, canonicaliza y verifica una solicitud de ruta del Registro.

        Lanza excepciones específicas de RegistryPathError ante cualquier violación.
        """
        if not hive or not isinstance(hive, str) or not hive.strip():
            raise InvalidHiveError(str(hive))

        raw_hive_clean = str(hive).strip().upper()

        # 1. Validación y Normalización de Hive
        if raw_hive_clean not in HIVE_MAP:
            raise InvalidHiveError(raw_hive_clean)

        canonical_hive = HIVE_MAP[raw_hive_clean]
        if canonical_hive not in self.allowed_hives and raw_hive_clean not in self.allowed_hives:
            raise InvalidHiveError(raw_hive_clean)

        # 2. Validación de Tipo y Caracteres Nulos en key_path
        if key_path is None:
            clean_sub_key = ""
        elif isinstance(key_path, str):
            clean_sub_key = key_path.strip()
        else:
            raise RegistryPathError("La ruta de subclave debe ser una cadena de texto válida.")

        if "\x00" in clean_sub_key or "\x00" in raw_hive_clean:
            raise RegistryPathError("La ruta del Registro contiene caracteres nulos de terminación (null bytes).")

        # 3. Normalización de Separadores y Barras Intermedias
        clean_sub_key = clean_sub_key.replace("/", "\\")
        parts = [p.strip() for p in clean_sub_key.split("\\") if p.strip()]

        # 4. Verificación de Límite de Profundidad
        if len(parts) > self.max_depth:
            raise RegistryDepthLimitError(len(parts), self.max_depth)

        canonical_sub_key = "\\".join(parts)

        # 5. Registro del Evento de Auditoría
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.REGISTRY_PATH_VALIDATED,
                tool_name="windows.registry",
                operation="validate_path",
                reason="Ruta de clave del Registro validada exitosamente.",
                metadata={
                    "hive": canonical_hive,
                    "sub_key_path": canonical_sub_key,
                },
            )
        )

        return RegistryKeyPath(hive=canonical_hive, sub_key_path=canonical_sub_key)
