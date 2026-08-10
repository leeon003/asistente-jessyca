"""Modelos de datos fuertemente tipados e inmutables para herramientas de Registro de Windows (Subetapa 06.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RegistryKeyPath:
    """Ruta inmutable canónica de una clave del Registro (hive + subkey)."""

    hive: str
    sub_key_path: str

    def full_path(self) -> str:
        """Devuelve la representación de texto completa de la ruta."""
        if not self.sub_key_path:
            return self.hive
        return f"{self.hive}\\{self.sub_key_path}"


@dataclass(frozen=True)
class RegistryValue:
    """Representa un valor individual contenido dentro de una clave del Registro."""

    name: str
    value_type: str
    value_data: Any

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado del valor."""
        return {
            "name": self.name,
            "value_type": self.value_type,
            "value_data": self.value_data,
        }


@dataclass(frozen=True)
class RegistrySubKey:
    """Representa el nombre y la ruta relativa de una subclave del Registro."""

    name: str
    sub_key_path: str

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado de la subclave."""
        return {
            "name": self.name,
            "sub_key_path": self.sub_key_path,
        }


@dataclass(frozen=True)
class RegistryKeyInfo:
    """Información inmutable de metadatos de una clave del Registro."""

    hive: str
    key_path: str
    subkeys_count: int
    values_count: int
    last_modified: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado de los metadatos de la clave."""
        return {
            "hive": self.hive,
            "key_path": self.key_path,
            "subkeys_count": self.subkeys_count,
            "values_count": self.values_count,
            "last_modified": self.last_modified,
        }


@dataclass(frozen=True)
class RegistryValueInfo:
    """Información inmutable del detalle de un valor específico del Registro."""

    hive: str
    key_path: str
    value_name: str
    value_type: str
    value_data: Any

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado del detalle del valor."""
        return {
            "hive": self.hive,
            "key_path": self.key_path,
            "value_name": self.value_name,
            "value_type": self.value_type,
            "value_data": self.value_data,
        }


@dataclass(frozen=True)
class RegistryQueryResult:
    """Resultado inmutable de la consulta completa de una clave y sus subclaves/valores."""

    hive: str
    key_path: str
    subkeys: tuple[RegistrySubKey, ...] = field(default_factory=tuple)
    values: tuple[RegistryValue, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado del resultado de la consulta."""
        return {
            "hive": self.hive,
            "key_path": self.key_path,
            "subkeys": [s.to_dict() for s in self.subkeys],
            "values": [v.to_dict() for v in self.values],
        }
