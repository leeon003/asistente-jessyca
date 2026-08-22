"""Jerarquía Formal y Unificada de Errores de JESSYCA 4.0 (system_errors.py - Fase 38).

PRINCIPIOS Y GARANTÍAS:
1. Jerarquía tipada y explícita por capa funcional sin ocultamiento de excepciones.
2. Los errores nunca se transforman silenciosamente en respuestas exitosas.
3. Preservación del contexto, código de error, capa de procedencia y criticidad.
"""

from __future__ import annotations

from typing import Any


class JessycaError(Exception):
    """Excepción base para todos los errores del ecosistema JESSYCA."""

    def __init__(
        self,
        message: str,
        layer: str = "core",
        error_code: str = "JESSYCA_ERROR",
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.layer = layer
        self.error_code = error_code
        self.details = details or {}
        self.cause = cause

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "layer": self.layer,
            "message": self.message,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
        }


class IntentError(JessycaError):
    """Errores en la interpretación, validación o resolución de intenciones."""

    def __init__(self, message: str, details: dict[str, Any] | None = None, cause: Exception | None = None) -> None:
        super().__init__(message=message, layer="intent", error_code="INTENT_ERROR", details=details, cause=cause)


class PlanningError(JessycaError):
    """Errores durante la generación, validación o estructuración de planes y grafos."""

    def __init__(self, message: str, details: dict[str, Any] | None = None, cause: Exception | None = None) -> None:
        super().__init__(message=message, layer="planning", error_code="PLANNING_ERROR", details=details, cause=cause)


class SkillError(JessycaError):
    """Errores en el ciclo de vida, ejecución, registro o composición de Skills."""

    def __init__(self, message: str, details: dict[str, Any] | None = None, cause: Exception | None = None) -> None:
        super().__init__(message=message, layer="skills", error_code="SKILL_ERROR", details=details, cause=cause)


class AgentError(JessycaError):
    """Errores en el bucle de control, coordinación o delegación de Agentes."""

    def __init__(self, message: str, details: dict[str, Any] | None = None, cause: Exception | None = None) -> None:
        super().__init__(message=message, layer="agents", error_code="AGENT_ERROR", details=details, cause=cause)


class ModelError(JessycaError):
    """Errores en la inferencia, enrutamiento, ciclo de vida o consenso de Modelos LLM/Vision."""

    def __init__(self, message: str, details: dict[str, Any] | None = None, cause: Exception | None = None) -> None:
        super().__init__(message=message, layer="models", error_code="MODEL_ERROR", details=details, cause=cause)


class ToolError(JessycaError):
    """Errores durante la ejecución de herramientas MCP o herramientas del sistema operativo."""

    def __init__(self, message: str, details: dict[str, Any] | None = None, cause: Exception | None = None) -> None:
        super().__init__(message=message, layer="tools", error_code="TOOL_ERROR", details=details, cause=cause)


class SecurityError(JessycaError):
    """Violaciones de seguridad, denegaciones de política, escalada de privilegios o parada de emergencia."""

    def __init__(self, message: str, details: dict[str, Any] | None = None, cause: Exception | None = None) -> None:
        super().__init__(message=message, layer="security", error_code="SECURITY_ERROR", details=details, cause=cause)


class MemoryError(JessycaError):
    """Errores en almacenamiento, recuperación, vector store o envenenamiento de memoria."""

    def __init__(self, message: str, details: dict[str, Any] | None = None, cause: Exception | None = None) -> None:
        super().__init__(message=message, layer="memory", error_code="MEMORY_ERROR", details=details, cause=cause)


class InfrastructureError(JessycaError):
    """Errores de red, procesos del sistema operativo, VRAM, I/O o hardware."""

    def __init__(self, message: str, details: dict[str, Any] | None = None, cause: Exception | None = None) -> None:
        super().__init__(message=message, layer="infrastructure", error_code="INFRASTRUCTURE_ERROR", details=details, cause=cause)


class AutonomyError(JessycaError):
    """Errores en el scheduler, tareas autónomas, presupuestos o eventos proactivos."""

    def __init__(self, message: str, details: dict[str, Any] | None = None, cause: Exception | None = None) -> None:
        super().__init__(message=message, layer="autonomy", error_code="AUTONOMY_ERROR", details=details, cause=cause)
