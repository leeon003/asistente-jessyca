"""Servicio seguro de ejecución de operaciones en el sistema de archivos (Subetapa 06.2).

Implementa las 5 operaciones fundamentales (`list_directory`, `read_file`, `write_file`, `create_directory`, `delete_file`)
con aislamiento de sandbox, validación de ruta previa, escritura atómica y límites estrictos de tamaño.
"""

from __future__ import annotations

import datetime
import os
import tempfile

from config.settings import AppSettings
from core.logger import get_logger
from tools.filesystem.errors import (
    FileNotFoundToolError,
    FileOperationError,
    FileSizeLimitError,
    FilesystemError,
    FilesystemPermissionError,
)
from tools.filesystem.models import (
    DirectoryListing,
    FileDeleteResult,
    FileEntry,
    FileReadResult,
    FileWriteResult,
)
from tools.filesystem.path_security import PathSecurityManager

logger = get_logger("jessyca.tools.filesystem.service")


class FilesystemService:
    """Servicio seguro de operaciones del sistema de archivos dentro del sandbox."""

    def __init__(self, path_security_manager: PathSecurityManager | None = None) -> None:
        self.path_security = path_security_manager or PathSecurityManager()
        settings = AppSettings()
        self.max_read_size: int = settings.FILESYSTEM_MAX_READ_SIZE
        self.max_write_size: int = settings.FILESYSTEM_MAX_WRITE_SIZE
        self.max_list_entries: int = settings.FILESYSTEM_MAX_LIST_ENTRIES

    def list_directory(self, path: str = ".") -> DirectoryListing:
        """Lista las entradas contenidas en un directorio dentro del sandbox."""
        val = self.path_security.validate_and_canonicalize(path)
        canonical = val.canonical_path

        if not os.path.exists(canonical):
            raise FileNotFoundToolError(path)
        if not os.path.isdir(canonical):
            raise FileOperationError("list_directory", path, "La ruta especificada no es un directorio.")

        try:
            entries: list[FileEntry] = []
            dir_items = os.listdir(canonical)

            for name in dir_items[: self.max_list_entries]:
                item_path = os.path.join(canonical, name)
                try:
                    stat = os.stat(item_path)
                    is_dir = os.path.isdir(item_path)
                    is_file = os.path.isfile(item_path)
                    size_bytes = stat.st_size if is_file else 0
                    mod_time = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.UTC).isoformat()

                    entries.append(
                        FileEntry(
                            name=name,
                            path=item_path,
                            is_directory=is_dir,
                            is_file=is_file,
                            size_bytes=size_bytes,
                            modified_at=mod_time,
                        )
                    )
                except OSError as e:
                    logger.warning(f"No se pudo obtener información de la entrada '{name}': {e}")
                    continue

            return DirectoryListing(
                directory_path=canonical,
                total_entries=len(entries),
                entries=tuple(entries),
            )
        except PermissionError:
            raise FilesystemPermissionError(path)
        except Exception as e:
            raise FileOperationError("list_directory", path, str(e))

    def read_file(self, path: str, encoding: str = "utf-8") -> FileReadResult:
        """Lee el contenido textual de un archivo regular dentro del sandbox."""
        val = self.path_security.validate_and_canonicalize(path)
        canonical = val.canonical_path

        if not os.path.exists(canonical):
            raise FileNotFoundToolError(path)
        if not os.path.isfile(canonical):
            raise FileOperationError("read_file", path, "La ruta especificada no es un archivo regular.")

        try:
            size_bytes = os.path.getsize(canonical)
            if size_bytes > self.max_read_size:
                raise FileSizeLimitError(size_bytes, self.max_read_size)

            with open(canonical, encoding=encoding, errors="replace") as f:
                content = f.read()

            return FileReadResult(
                path=canonical,
                content=content,
                size_bytes=size_bytes,
                encoding=encoding,
            )
        except PermissionError:
            raise FilesystemPermissionError(path)
        except FilesystemError:
            raise
        except Exception as e:
            raise FileOperationError("read_file", path, str(e))

    def write_file(self, path: str, content: str, encoding: str = "utf-8") -> FileWriteResult:
        """Escribe contenido de forma atómica en un archivo regular dentro del sandbox."""
        val = self.path_security.validate_and_canonicalize(path)
        canonical = val.canonical_path

        encoded_bytes = content.encode(encoding)
        if len(encoded_bytes) > self.max_write_size:
            raise FileSizeLimitError(len(encoded_bytes), self.max_write_size)

        parent_dir = os.path.dirname(canonical)
        os.makedirs(parent_dir, exist_ok=True)

        is_new = not os.path.exists(canonical)

        # Escritura atómica vía archivo temporal en el mismo directorio padre (evita TOCTOU)
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=parent_dir, delete=False) as tmp_f:
                tmp_f.write(encoded_bytes)
                tmp_f.flush()
                os.fsync(tmp_f.fileno())
                tmp_path = tmp_f.name

            # Reemplazo atómico seguro del archivo destino
            os.replace(tmp_path, canonical)

            return FileWriteResult(
                path=canonical,
                bytes_written=len(encoded_bytes),
                is_new_file=is_new,
            )
        except PermissionError:
            raise FilesystemPermissionError(path)
        except Exception as e:
            if "tmp_path" in locals() and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise FileOperationError("write_file", path, str(e))

    def create_directory(self, path: str) -> str:
        """Crea un nuevo directorio (y padres necesarios) dentro del sandbox."""
        val = self.path_security.validate_and_canonicalize(path)
        canonical = val.canonical_path

        try:
            os.makedirs(canonical, exist_ok=True)
            return canonical
        except PermissionError:
            raise FilesystemPermissionError(path)
        except Exception as e:
            raise FileOperationError("create_directory", path, str(e))

    def delete_file(self, path: str) -> FileDeleteResult:
        """Elimina un archivo regular existente dentro del sandbox.

        REGLA DE SEGURIDAD: Únicamente se permite eliminar archivos regulares.
        No se permite la eliminación de directorios, symlinks ni junctions.
        """
        val = self.path_security.validate_and_canonicalize(path)
        canonical = val.canonical_path

        if not os.path.exists(canonical):
            raise FileNotFoundToolError(path)

        if os.path.isdir(canonical) or os.path.islink(canonical):
            raise FileOperationError(
                "delete_file",
                path,
                "Únicamente se permite eliminar archivos regulares. No se permite eliminar directorios o enlaces.",
            )

        try:
            os.remove(canonical)
            return FileDeleteResult(path=canonical, deleted=True)
        except PermissionError:
            raise FilesystemPermissionError(path)
        except Exception as e:
            raise FileOperationError("delete_file", path, str(e))
