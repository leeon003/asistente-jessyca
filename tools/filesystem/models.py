"""Modelos de datos fuertemente tipados e inmutables para herramientas de archivos (Subetapa 06.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PathValidationResult:
    """Resultado estructurado de la validación y canonicalización de ruta."""

    is_valid: bool
    raw_path: str
    canonical_path: str
    sandbox_root: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario con los datos del resultado."""
        return {
            "is_valid": self.is_valid,
            "raw_path": self.raw_path,
            "canonical_path": self.canonical_path,
            "sandbox_root": self.sandbox_root,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FileEntry:
    """Representa una entrada (archivo o subdirectorio) dentro de una lista de directorio."""

    name: str
    path: str
    is_directory: bool
    is_file: bool
    size_bytes: int
    modified_at: str

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado de la entrada."""
        return {
            "name": self.name,
            "path": self.path,
            "is_directory": self.is_directory,
            "is_file": self.is_file,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
        }


@dataclass(frozen=True)
class DirectoryListing:
    """Resultado inmutable del listado de un directorio."""

    directory_path: str
    total_entries: int
    entries: tuple[FileEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado del listado."""
        return {
            "directory_path": self.directory_path,
            "total_entries": self.total_entries,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass(frozen=True)
class FileReadResult:
    """Resultado inmutable del contenido leído de un archivo."""

    path: str
    content: str
    size_bytes: int
    encoding: str = "utf-8"

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado de la lectura."""
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "encoding": self.encoding,
            "content": self.content,
        }


@dataclass(frozen=True)
class FileWriteResult:
    """Resultado inmutable de la escritura de un archivo."""

    path: str
    bytes_written: int
    is_new_file: bool

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado de la escritura."""
        return {
            "path": self.path,
            "bytes_written": self.bytes_written,
            "is_new_file": self.is_new_file,
        }


@dataclass(frozen=True)
class FileDeleteResult:
    """Resultado inmutable de la eliminación de un archivo."""

    path: str
    deleted: bool

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado de la eliminación."""
        return {
            "path": self.path,
            "deleted": self.deleted,
        }
