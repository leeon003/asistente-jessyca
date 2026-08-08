"""Clase base abstracta para la construcción de herramientas MCP en Jessyca Windows MCP.

Proporciona infraestructura básica de validación, manejo de logs, metadatos de seguridad y capacidades.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.contracts import ITool
from core.exceptions import ToolExecutionError, ValidationError
from core.logger import get_logger
from core.security import RiskLevel
from core.types import JSONDict, Result
from tools.schemas import ToolSchema


class BaseMCPTool(ITool, ABC):
    """Clase base estandarizada para la implementación de herramientas MCP puras."""

    def __init__(
        self,
        name: str,
        description: str,
        version: str = "1.0.0",
        author: str = "Jessyca Core Team",
        category: str = "general",
        capability: str = "general",
        action: str = "execute",
        aliases: list[str] | None = None,
        risk_level: RiskLevel = RiskLevel.SAFE,
        required_permissions: list[str] | None = None,
        timeout_seconds: float = 30.0,
        supports_rollback: bool = False,
    ) -> None:
        self._name = name
        self._description = description
        self.version = version
        self.author = author
        self.category = category
        self.capability = capability
        self.action = action
        self.aliases = aliases or []
        self.risk_level = risk_level
        self.required_permissions = required_permissions or []
        self.timeout_seconds = timeout_seconds
        self.supports_rollback = supports_rollback
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

    @property
    def output_schema(self) -> JSONDict:
        return self._get_output_schema()

    def get_metadata(self) -> ToolSchema:
        """Devuelve la especificación formal completa de metadatos de la herramienta."""
        return ToolSchema(
            name=self.name,
            description=self.description,
            version=self.version,
            author=self.author,
            category=self.category,
            capability=self.capability,
            action=self.action,
            aliases=self.aliases,
            risk_level=self.risk_level,
            required_permissions=self.required_permissions,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            timeout_seconds=self.timeout_seconds,
            supports_rollback=self.supports_rollback,
        )

    def validate_arguments(self, arguments: JSONDict) -> bool:
        """Valida que los argumentos cumplan las restricciones básicas definidas en el input_schema.

        Args:
            arguments: Diccionario de parámetros pasados a la herramienta.

        Returns:
            bool: True si los argumentos son válidos.

        Raises:
            ValidationError: Si falta un parámetro obligatorio o el tipo es inválido.
        """
        schema = self.input_schema
        required_fields = schema.get("required", [])

        for req in required_fields:
            if req not in arguments:
                raise ValidationError(
                    f"Argumento obligatorio '{req}' no proporcionado para la herramienta '{self.name}'."
                )

        return True

    @abstractmethod
    def _get_input_schema(self) -> JSONDict:
        """Define el esquema JSON Schema de parámetros de entrada de la herramienta."""
        pass

    def _get_output_schema(self) -> JSONDict:
        """Define el esquema JSON Schema de salida de la herramienta (por defecto objeto genérico)."""
        return {"type": "object", "properties": {}}

    @abstractmethod
    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        """Lógica interna de ejecución asíncrona a implementar por herramientas concretas."""
        pass

    async def execute(self, arguments: JSONDict) -> Result[JSONDict]:
        """Ejecuta la herramienta capturando errores no controlados y devolviendo un Result."""
        self._logger.info(f"Ejecutando herramienta '{self.name}' con argumentos: {arguments}")
        try:
            self.validate_arguments(arguments)
            res = await self._execute_internal(arguments)
            self._logger.info(f"Herramienta '{self.name}' ejecutada exitosamente.")
            return Result.ok(res)
        except ValidationError as ve:
            self._logger.warning(f"Error de validación en herramienta '{self.name}': {ve}")
            return Result.fail(ve)
        except Exception as e:
            msg = f"Error durante la ejecución de la herramienta '{self.name}': {e}"
            self._logger.error(msg)
            return Result.fail(ToolExecutionError(msg, details={"tool": self.name, "cause": str(e)}))
