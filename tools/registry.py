"""Shim de compatibilidad para tools.registry hacia tools.tool_registry.

NOTA DE ARQUITECTURA (Fase 10 - Consolidación Gradual):
- El registro canónico de herramientas MCP reside en 'tools.tool_registry' (ToolRegistry).
- Las herramientas de inspección del Registro de Windows residen en el paquete 'tools.registry.*'.
- Este archivo reexporta ToolRegistry y get_tool_registry desde tools.tool_registry para
  garantizar compatibilidad hacia atrás en cualquier importación directa o referencia de ruta,
  evitando divergencias y código duplicado.
"""

from __future__ import annotations

from core.contracts import ITool, IToolRegistry
from core.exceptions import ToolNotFoundError
from tools.schemas import ToolSchema
from tools.tool_registry import (
    ToolRegistry,
    _global_tool_registry_instance,
    get_tool_registry,
)

__all__ = [
    "ToolRegistry",
    "get_tool_registry",
    "ITool",
    "IToolRegistry",
    "ToolNotFoundError",
    "ToolSchema",
]
