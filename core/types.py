"""Tipos compartidos, Enums, TypeAliases y estructuras genéricas para Jessyca Windows MCP."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Generic, TypeVar

from config.settings import EnvironmentMode, LogLevel

# Generic TypeVars
T = TypeVar("T")
E = TypeVar("E", bound=Exception)


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

    @property
    def value(self) -> T:
        if not self.is_success:
            raise ValueError(f"No se puede obtener el valor de un Result fallido: {self._error}")
        return self._value  # type: ignore[return-value]

    @property
    def error(self) -> Exception | str | None:
        return self._error

    @classmethod
    def ok(cls, value: T) -> Result[T]:
        return cls(is_success=True, value=value)

    @classmethod
    def fail(cls, error: Exception | str) -> Result[T]:
        return cls(is_success=False, error=error)

    def __repr__(self) -> str:
        if self.is_success:
            return f"Result.ok({self._value!r})"
        return f"Result.fail({self._error!r})"


__all__ = [
    "EnvironmentMode",
    "JSONDict",
    "JSONValue",
    "LogLevel",
    "Result",
    "WindowsVersion",
]
