"""Módulo base de herramientas para retrocompatibilidad.

Exporta BaseMCPTool, BaseTool, ToolSchema y ToolMetadata.
"""

from __future__ import annotations

from tools.base_tool import BaseMCPTool
from tools.schemas import ToolSchema

BaseTool = BaseMCPTool
ToolMetadata = ToolSchema

__all__ = ["BaseMCPTool", "BaseTool", "ToolSchema", "ToolMetadata"]
