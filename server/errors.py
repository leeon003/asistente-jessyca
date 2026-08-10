"""Excepciones específicas del servidor MCP de Jessyca (Subetapa 05.1)."""

from __future__ import annotations

from core.exceptions import MCPError


class MCPServerNotInitializedError(MCPError):
    """El servidor MCP no se ha inicializado previamente."""

    def __init__(self, message: str = "El servidor MCP no se encuentra inicializado.") -> None:
        super().__init__(message)


class MCPServerStateError(MCPError):
    """Estado inválido o transición no permitida en el ciclo de vida del servidor MCP."""

    def __init__(self, current_state: str, action: str) -> None:
        super().__init__(f"No se puede ejecutar '{action}' en el estado actual '{current_state}'.")
        self.current_state = current_state
        self.action = action


class MCPToolNotFoundError(MCPError):
    """La herramienta solicitada no existe o no está registrada en el servidor MCP."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Herramienta MCP no encontrada: '{tool_name}'")
        self.tool_name = tool_name


class MCPValidationError(MCPError):
    """Error de validación en la solicitud o parámetros del cliente MCP."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class MCPInternalError(MCPError):
    """Error interno no controlado durante la ejecución del servidor MCP."""

    def __init__(self, message: str = "Error interno en el servidor MCP.") -> None:
        super().__init__(message)


class ExecutionPipelineError(MCPError):
    """Error general en la orquestación del pipeline de ejecución segura."""

    def __init__(self, message: str = "Error en el pipeline de ejecución segura.") -> None:
        super().__init__(message)


class SecurityAuthorizationError(ExecutionPipelineError):
    """Error durante la evaluación de autorización de seguridad en el pipeline."""

    def __init__(self, message: str = "Error de autorización de seguridad.") -> None:
        super().__init__(message)


class InvalidAuthorizationEvidenceError(ExecutionPipelineError):
    """Falla la validación de la evidencia de autorización de seguridad (evidencia corrupta o falsificada)."""

    def __init__(self, message: str = "Evidencia de autorización no válida o tampered.") -> None:
        super().__init__(message)


class ExecutionNotAuthorizedError(ExecutionPipelineError):
    """La solicitud de ejecución fue rechazada/denegada por las capas de seguridad."""

    def __init__(self, reason: str = "Ejecución no autorizada por políticas de seguridad.") -> None:
        super().__init__(f"Ejecución Denegada: {reason}")
        self.reason = reason


class ExecutionDisabledError(ExecutionPipelineError):
    """La ejecución real de herramientas se encuentra deshabilitada en la subetapa actual."""

    def __init__(self, message: str = "La ejecución real de herramientas está deshabilitada en la Subetapa 05.2.") -> None:
        super().__init__(message)
