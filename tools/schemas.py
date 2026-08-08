"""Esquemas y modelos de datos Pydantic para el protocolo MCP (Model Context Protocol)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.security import RiskLevel
from core.types import JSONDict


class ToolInputProperty(BaseModel):
    """Definición de una propiedad dentro del esquema JSON de argumentos de una herramienta."""

    type: str = Field(..., description="Tipo de dato JSON (string, integer, boolean, object, array).")
    description: str = Field(..., description="Explicación del parámetro para el modelo de lenguaje.")
    default: Any | None = Field(default=None, description="Valor por defecto si es opcional.")


class ToolSchema(BaseModel):
    """Esquema de especificación MCP completo para registrar e inspeccionar una herramienta."""

    name: str = Field(..., description="Nombre único identificador de la herramienta MCP.")
    description: str = Field(..., description="Descripción funcional de la herramienta.")
    category: str = Field(default="General", description="Categoría de la herramienta.")
    capability: str = Field(default="General", description="Dominio de capacidad.")
    action: str = Field(default="execute", description="Nombre de la acción realizada.")
    version: str = Field(default="0.1.0", description="Versión de la herramienta.")
    risk_level: RiskLevel = Field(default=RiskLevel.SAFE, description="Nivel de riesgo asignado.")
    required_permissions: list[str] = Field(default_factory=list, description="Permisos requeridos.")
    input_schema: JSONDict = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema formal de los parámetros de entrada.",
    )
    output_schema: JSONDict = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema formal de los datos de salida.",
    )
    timeout_seconds: float = Field(default=30.0, description="Tiempo máximo de ejecución en segundos.")


class ToolCallRequest(BaseModel):
    """Solicitud de invocación de una herramienta MCP."""

    tool_name: str = Field(..., description="Nombre de la herramienta a invocar.")
    arguments: JSONDict = Field(default_factory=dict, description="Argumentos pasados a la herramienta.")


class ToolExecutionResponse(BaseModel):
    """Respuesta estandarizada tras la ejecución de una herramienta MCP."""

    tool_name: str = Field(..., description="Nombre de la herramienta ejecutada.")
    is_success: bool = Field(..., description="Indica si la ejecución finalizó correctamente.")
    result: JSONDict | None = Field(default=None, description="Datos de salida producidos.")
    error_message: str | None = Field(default=None, description="Mensaje de error si falló.")
