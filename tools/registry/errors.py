"""Excepciones estructuradas para herramientas de inspección del Registro de Windows (Subetapa 06.4)."""

from __future__ import annotations

from core.exceptions import MCPError


class RegistryError(MCPError):
    """Error base para operaciones sobre el Registro de Windows."""

    def __init__(self, message: str = "Error en la consulta del Registro de Windows.") -> None:
        super().__init__(message)


class RegistryPathError(RegistryError):
    """Error de formato, sintaxis o seguridad en la ruta de clave del Registro."""

    def __init__(self, message: str = "Ruta de clave del Registro inválida o no permitida.") -> None:
        super().__init__(message)


class InvalidHiveError(RegistryPathError):
    """El hive del Registro especificado no está autorizado o es desconocido."""

    def __init__(self, hive: str) -> None:
        super().__init__(f"Hive del Registro no autorizado o inválido: '{hive}'.")
        self.hive = hive


class RegistryNotFoundError(RegistryError):
    """La clave o valor especificado no existe en el Registro."""

    def __init__(self, hive: str, key_path: str, value_name: str | None = None) -> None:
        msg = (
            f"Valor de Registro '{value_name}' no encontrado en '{hive}\\{key_path}'."
            if value_name
            else f"Clave de Registro no encontrada: '{hive}\\{key_path}'."
        )
        super().__init__(msg)
        self.hive = hive
        self.key_path = key_path
        self.value_name = value_name


class RegistryAccessDeniedError(RegistryError):
    """El sistema operativo denegó el acceso de lectura a la clave del Registro."""

    def __init__(self, hive: str, key_path: str) -> None:
        super().__init__(f"Acceso Denegado por el sistema operativo al leer la clave: '{hive}\\{key_path}'.")
        self.hive = hive
        self.key_path = key_path


class RegistryDepthLimitError(RegistryPathError):
    """La profundidad de la ruta de clave excede el límite máximo configurado."""

    def __init__(self, depth: int, max_depth: int) -> None:
        super().__init__(f"Profundidad de ruta del Registro excedida ({depth}). Máximo permitido: {max_depth}.")
        self.depth = depth
        self.max_depth = max_depth


class RegistrySizeLimitError(RegistryError):
    """El tamaño del valor binario o cantidad de subclaves/valores excede el límite máximo."""

    def __init__(self, current_size: int, max_limit: int) -> None:
        super().__init__(f"Límite de tamaño del Registro excedido ({current_size}). Máximo permitido: {max_limit}.")
        self.current_size = current_size
        self.max_limit = max_limit
