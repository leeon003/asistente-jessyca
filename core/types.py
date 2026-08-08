"""Tipos compartidos, Enums, TypeAliases y estructuras genéricas para Jessyca Windows MCP."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Generic, TypeVar

# Generic TypeVars
T = TypeVar("T")
E = TypeVar("E", bound=Exception)


class EnvironmentMode(StrEnum):
    """Entornos de ejecución de la aplicación."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class LogLevel(StrEnum):
    """Niveles de registro para el sistema de logging centralizado."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class WindowsVersion(StrEnum):
    """Ediciones y versiones compatibles del sistema operativo Windows."""

    WINDOWS_10 = "Windows 10"
    WINDOWS_11 = "Windows 11"
    UNSUPPORTED = "Unsupported OS"
    UNKNOWN = "Unknown Windows Version"


# Type Aliases útiles
JSONValue = str | int | float | bool | None | dict[str, Any] | list[Any]
JSONDict = dict[str, Any]


class Result(Generic[T]):
    """Contenedor monolítico genérico para resultados de operaciones en Jessyca (Pattern Result).

    Facilita el manejo de errores sin necesidad de lanzar excepciones en flujos no críticos.
    """

    def __init__(
        self,
        is_success: bool,
        value: T | None = None,
        error: Exception | str | None = None,
    ) -> None:
        self.is_success = is_success
        self._value = value
        self._error = error

    @classmethod
    def ok(cls, value: T) -> Result[T]:
        """Crea un resultado exitoso."""
        return cls(is_success=True, value=value)

    @classmethod
    def fail(cls, error: Exception | str) -> Result[T]:
        """Crea un resultado con fallo."""
        return cls(is_success=False, error=error)

    @property
    def value(self) -> T:
        """Obtiene el valor del resultado si fue exitoso."""
        if not self.is_success or self._value is None:
            raise ValueError("No se puede obtener el valor de un Result fallido o nulo.")
        return self._value

    @property
    def error(self) -> Exception | str:
        """Obtiene el error asociado si la operación falló."""
        if self.is_success or self._error is None:
            raise ValueError("No se puede obtener el error de un Result exitoso.")
        return self._error

    def unwrap_or(self, default: T) -> T:
        """Devuelve el valor contenido o un valor predeterminado en caso de fallo."""
        return self._value if self.is_success and self._value is not None else default

    def __repr__(self) -> str:
        if self.is_success:
            return f"Result.Ok({self._value!r})"
        return f"Result.Fail({self._error!r})"
