"""Registro dinámico centralizado, desacoplado y tolerante a fallos para Herramientas MCP.

Proporciona capacidades de autodescubrimiento dinámico en el sistema de archivos,
validación de contrato de herramientas, aislamiento de errores de importación y
búsqueda en tiempo constante O(1).
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any

from core.contracts import ITool, IToolRegistry
from core.exceptions import ToolNotFoundError
from core.logger import get_logger
from core.types import JSONDict, Result
from tools.schemas import ToolSchema

logger = get_logger("jessyca.tools.registry")


class ToolRegistry(IToolRegistry):
    """Registro desacoplado y gestor de catálogo para herramientas MCP."""

    def __init__(self) -> None:
        self._tools: dict[str, ITool] = {}
        self._schemas: dict[str, ToolSchema] = {}

    def discover(self, tools_dir: Path | str | None = None) -> int:
        """Escanea dinámicamente la carpeta de herramientas e importa/registra automáticamente los módulos válidos."""
        if tools_dir is None:
            target_dir = Path(__file__).resolve().parent
        else:
            target_dir = Path(tools_dir)

        if not target_dir.exists():
            logger.warning(f"El directorio de herramientas especificado no existe: {target_dir}")
            return 0

        logger.info(f"Iniciando escaneo dinámico de herramientas MCP en: {target_dir}")
        initial_count = len(self._tools)

        py_files = sorted(target_dir.rglob("*.py"))

        for file_path in py_files:
            file_name = file_path.name

            if (
                file_name.startswith("__")
                or file_name.startswith("test_")
                or file_name in ("registry.py", "discovery.py", "tool_registry.py")
            ):
                continue

            module_name = f"dynamic_mcp_tools.{file_path.stem}_{hash(str(file_path)) & 0xffffff}"

            try:
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            except Exception as e:
                logger.error(
                    f"Módulo de herramienta ignorado por error durante la importación [{file_path.name}]: {e}"
                )
                continue

            try:
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if self._is_mcp_tool_class(obj):
                        try:
                            tool_instance = obj()
                            if isinstance(tool_instance, ITool):
                                self.register(tool_instance)
                        except Exception as e:
                            logger.error(
                                f"Error al instanciar clase de herramienta '{obj.__name__}' en [{file_name}]: {e}"
                            )
            except Exception as e:
                logger.error(f"Error al inspeccionar miembros del módulo [{file_name}]: {e}")

        new_count = len(self._tools) - initial_count
        logger.info(f"Escaneo de herramientas finalizado. Se registraron {new_count} nuevas herramientas.")
        return new_count

    def _is_mcp_tool_class(self, obj: Any) -> bool:
        if not inspect.isclass(obj) or inspect.isabstract(obj):
            return False
        if obj.__name__ in ("BaseMCPTool", "ITool"):
            return False
        try:
            mro_names = {base.__name__ for base in inspect.getmro(obj)}
            return "BaseMCPTool" in mro_names or "ITool" in mro_names
        except Exception:
            return False

    def validate_tool(self, tool: Any) -> bool:
        if not hasattr(tool, "name") or not tool.name or not isinstance(tool.name, str):
            logger.warning(f"Herramienta rechazada: Atributo 'name' inválido o vacío en {tool}")
            return False

        if not hasattr(tool, "description") or not isinstance(tool.description, str):
            logger.warning(f"Herramienta '{tool.name}' rechazada: Descripción inválida en {tool}")
            return False

        if not hasattr(tool, "input_schema") or not isinstance(tool.input_schema, dict):
            logger.warning(f"Herramienta '{tool.name}' rechazada: 'input_schema' debe ser un diccionario.")
            return False

        return True

    def register(self, tool: ITool) -> bool:
        if not self.validate_tool(tool):
            return False

        if tool.name in self._tools:
            logger.warning(
                f"Herramienta MCP '{tool.name}' ya estaba registrada. Sobrescribiendo registro previo."
            )

        self._tools[tool.name] = tool
        self._schemas[tool.name] = ToolSchema(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
        )
        logger.info(f"Herramienta MCP '{tool.name}' registrada exitosamente en el catálogo.")
        return True

    def unregister(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            self._schemas.pop(name, None)
            logger.info(f"Herramienta MCP '{name}' desregistrada correctamente.")
            return True

        logger.warning(f"No se pudo desregistrar la herramienta '{name}': No existe en el registro.")
        return False

    def get_tool(self, name: str) -> ITool | None:
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """Indica si una herramienta con ese nombre está registrada."""
        return name in self._tools

    def __len__(self) -> int:
        """Número de herramientas registradas."""
        return len(self._tools)

    def list_tools(self) -> list[ITool]:
        return list(self._tools.values())

    def get_schemas(self) -> list[ToolSchema]:
        return list(self._schemas.values())

    async def execute_tool(self, name: str, arguments: JSONDict) -> Result[JSONDict]:
        tool = self.get_tool(name)
        if not tool:
            err = ToolNotFoundError(
                f"Herramienta MCP '{name}' no encontrada en el registro.",
                details={"tool_name": name},
            )
            logger.error(str(err))
            return Result.fail(err)

        try:
            return await tool.execute(arguments)
        except Exception as e:
            msg = f"Excepción imprevista durante la ejecución de la herramienta '{name}': {e}"
            logger.error(msg)
            return Result.fail(msg)


_global_tool_registry_instance: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Obtiene la instancia global singleton de ToolRegistry."""
    global _global_tool_registry_instance
    if _global_tool_registry_instance is None:
        _global_tool_registry_instance = ToolRegistry()
    return _global_tool_registry_instance
