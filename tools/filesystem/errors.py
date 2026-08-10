"""Excepciones estructuradas para las herramientas de sistema de archivos (Subetapa 06.2)."""

from __future__ import annotations

from core.exceptions import MCPError


class FilesystemError(MCPError):
    """Error base para operaciones en el sistema de archivos."""

    def __init__(self, message: str = "Error en la operación del sistema de archivos.") -> None:
        super().__init__(message)


class PathSecurityError(FilesystemError):
    """Error de seguridad en la validación o resolución de rutas."""

    def __init__(self, message: str = "Error de seguridad en la ruta solicitada.") -> None:
        super().__init__(message)


class SandboxViolationError(PathSecurityError):
    """Intento de acceder a una ruta fuera del directorio sandbox autorizado."""

    def __init__(self, path: str, sandbox_root: str) -> None:
        super().__init__(f"Violación de Sandbox: La ruta '{path}' está fuera del sandbox '{sandbox_root}'.")
        self.path = path
        self.sandbox_root = sandbox_root


class PathTraversalError(PathSecurityError):
    """Detección de intento de escalamiento o traversal de directorios (../)."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Intento de Path Traversal detectado y denegado en ruta: '{path}'")
        self.path = path


class UnsupportedPathError(PathSecurityError):
    """Ruta con formato no soportado (ej. UNC, dispositivos Windows, null bytes)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Formato de ruta no soportado: {reason}")


class FileSizeLimitError(FilesystemError):
    """La operación excede el tamaño máximo configurado para lectura o escritura."""

    def __init__(self, current_size: int, max_limit: int) -> None:
        super().__init__(f"Límite de tamaño excedido ({current_size} bytes). El máximo permitido es {max_limit} bytes.")
        self.current_size = current_size
        self.max_limit = max_limit


class UnsafePathError(PathSecurityError):
    """La ruta apunta a un enlace simbólico, junction o reparse point no seguro que escapa del sandbox."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Ruta no segura: Enlace simbólico/Junction en '{path}' apunta fuera del sandbox.")
        self.path = path


class FileOperationError(FilesystemError):
    """Error durante la lectura, escritura o eliminación de un archivo."""

    def __init__(self, operation: str, path: str, reason: str) -> None:
        super().__init__(f"Error en operación '{operation}' sobre '{path}': {reason}")
        self.operation = operation
        self.path = path
        self.reason = reason


class FileNotFoundToolError(FilesystemError):
    """El archivo o directorio solicitado no existe."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Archivo o directorio no encontrado: '{path}'")
        self.path = path


class FilesystemPermissionError(FilesystemError):
    """Permiso denegado por el sistema operativo al acceder al archivo o directorio."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Permiso denegado en el sistema de archivos para '{path}'")
        self.path = path
