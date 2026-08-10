"""Servicio seguro de lectura e inspección del Registro de Windows (Subetapa 06.4 - READ ONLY).

GARANTÍA DE CERO ESCRITURA Y CERO SHELL EXECUTION:
Únicamente expone operaciones de consulta e inspección (`list_subkeys`, `get_key_info`, `list_values`, `get_value`).
Integra validación previa de seguridad de rutas (`RegistryPathSecurityManager`) y abstracción de backend (`IRegistryBackend`).
"""

from __future__ import annotations

from config.settings import AppSettings
from core.logger import get_logger
from tools.registry.backend import IRegistryBackend, get_default_registry_backend
from tools.registry.errors import RegistrySizeLimitError
from tools.registry.models import (
    RegistryKeyInfo,
    RegistrySubKey,
    RegistryValue,
    RegistryValueInfo,
)
from tools.registry.path_security import RegistryPathSecurityManager

logger = get_logger("jessyca.tools.registry.service")


class RegistryService:
    """Servicio de lectura e inspección segura del Registro de Windows."""

    def __init__(
        self,
        path_security_manager: RegistryPathSecurityManager | None = None,
        backend: IRegistryBackend | None = None,
    ) -> None:
        self.path_security = path_security_manager or RegistryPathSecurityManager()
        self.backend = backend or get_default_registry_backend()

        settings = AppSettings()
        self.max_subkeys: int = settings.REGISTRY_MAX_SUBKEYS
        self.max_values: int = settings.REGISTRY_MAX_VALUES
        self.max_value_size: int = settings.REGISTRY_MAX_VALUE_SIZE

    def list_subkeys(self, hive: str, key_path: str = "", limit: int | None = None) -> tuple[RegistrySubKey, ...]:
        """Lista las subclaves contenidas en una clave del Registro autorizada."""
        validated = self.path_security.validate_and_canonicalize(hive, key_path)
        max_sub = min(limit or self.max_subkeys, self.max_subkeys)

        subkeys = self.backend.list_subkeys(validated.hive, validated.sub_key_path, max_subkeys=max_sub)
        if len(subkeys) > self.max_subkeys:
            raise RegistrySizeLimitError(len(subkeys), self.max_subkeys)

        return subkeys

    def get_key_info(self, hive: str, key_path: str = "") -> RegistryKeyInfo:
        """Obtiene información estructurada de metadatos de una clave del Registro."""
        validated = self.path_security.validate_and_canonicalize(hive, key_path)
        return self.backend.get_key_info(validated.hive, validated.sub_key_path)

    def list_values(self, hive: str, key_path: str = "", limit: int | None = None) -> tuple[RegistryValue, ...]:
        """Lista todos los valores contenidos en una clave del Registro autorizada."""
        validated = self.path_security.validate_and_canonicalize(hive, key_path)
        max_val = min(limit or self.max_values, self.max_values)

        values = self.backend.list_values(
            validated.hive,
            validated.sub_key_path,
            max_values=max_val,
            max_value_size=self.max_value_size,
        )
        if len(values) > self.max_values:
            raise RegistrySizeLimitError(len(values), self.max_values)

        return values

    def get_value(self, hive: str, key_path: str, value_name: str) -> RegistryValueInfo:
        """Consulta el detalle de un valor específico contenido en una clave del Registro."""
        validated = self.path_security.validate_and_canonicalize(hive, key_path)
        val_name_clean = str(value_name).strip() if value_name is not None else ""

        return self.backend.get_value(
            validated.hive,
            validated.sub_key_path,
            value_name=val_name_clean,
            max_value_size=self.max_value_size,
        )
