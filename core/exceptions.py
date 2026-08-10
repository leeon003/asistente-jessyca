"""Jerarquía centralizada de excepciones personalizadas para Jessyca Windows MCP.

Proporciona excepciones bien tipadas para categorizar errores de configuración,
plataforma Windows, protocolo MCP y ejecución de herramientas.
"""

from __future__ import annotations

from typing import Any


class JessycaError(Exception):
    """Excepción base para todos los errores del ecosistema Jessyca Windows MCP."""

    def __init__(
        self,
        message: str,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convierte la excepción en una representación en diccionario."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "code": self.code,
            "details": self.details,
        }

    def __str__(self) -> str:
        if self.details:
            return f"[{self.code}] {self.message} | Details: {self.details}"
        return f"[{self.code}] {self.message}"


class ConfigurationError(JessycaError):
    """Excepción lanzada cuando ocurre un error en la carga o validación de la configuración."""

    pass


class WindowsPlatformError(JessycaError):
    """Excepción lanzada cuando falla una operación específica de la plataforma Windows o el sistema operativo no es compatible."""

    pass


class MCPError(JessycaError):
    """Excepción base para errores relacionados con el Model Context Protocol (MCP)."""

    pass


class ToolExecutionError(MCPError):
    """Excepción lanzada cuando la ejecución de una herramienta MCP falla o devuelve un estado no válido."""

    pass


class ToolNotFoundError(MCPError):
    """Excepción lanzada cuando se intenta resolver o invocar una herramienta MCP no registrada."""

    pass


class ValidationError(JessycaError):
    """Excepción lanzada cuando los datos de entrada o argumentos no cumplen con las especificaciones o esquemas."""

    pass


class SecurityValidationError(ValidationError):
    """Excepción lanzada cuando falla una validación de seguridad."""

    pass

