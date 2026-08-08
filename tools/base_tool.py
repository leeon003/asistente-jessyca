"""Clase base abstracta para la construcción de herramientas MCP en Jessyca Windows MCP.

Proporciona infraestructura básica de validación, manejo de logs, metadatos de seguridad y capacidades.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.contracts import ITool
from core.exceptions import ToolExecutionError
from core.logger import get_logger
from core.types import JSONDict, Result
from tools.schemas import ToolSchema


class BaseMCPTool(ITool, ABC):
    """Clase base para la implementación de herramientas MCP puras."""

    def __init__(
        self,
        name: str,
        description: str,
        capability: str = "General",
        action: str = "execute",
        aliases: list[str] | None = None,
    ) -> None:
        self._name = name
        self._description = description
        self.capability = capability
        self.action = action
        self.aliases = aliases or []
        self._logger = get_logger(f"jessyca.tools.{name}")

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> JSONDict:
        return self._get_input_schema()

    def get_metadata(self) -> ToolSchema:
        """Devuelve el esquema completo de metadatos de la herramienta."""
        return ToolSchema(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )

    @abstractmethod
    def _get_input_schema(self) -> JSONDict:
        """Define el esquema JSON Schema de parámetros de la herramienta."""
        pass

    @abstractmethod
    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        """Lógica interna de ejecución asíncrona a implementar por herramientas concretas."""
        pass

    async def execute(self, arguments: JSONDict) -> Result[JSONDict]:
        """Ejecuta la herramienta capturando errores no controlados y devolviendo un Result."""
        self._logger.info(f"Ejecutando herramienta '{self.name}' con argumentos: {arguments}")
        try:
            res = await self._execute_internal(arguments)
            self._logger.info(f"Herramienta '{self.name}' ejecutada exitosamente.")
            return Result.ok(res)
        except Exception as e:
            msg = f"Error durante la ejecución de la herramienta '{self.name}': {e}"
            self._logger.error(msg)
            return Result.fail(ToolExecutionError(msg, details={"tool": self.name, "cause": str(e)}))
