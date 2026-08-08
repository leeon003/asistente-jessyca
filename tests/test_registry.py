"""Pruebas unitarias completas del ToolRegistry desacoplado y tolerante a fallos."""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.types import JSONDict
from tools.base_tool import BaseMCPTool
from tools.registry import ToolRegistry


class ValidDummyTool(BaseMCPTool):
    """Herramienta válida para pruebas de registro."""

    def __init__(self, name: str = "valid_dummy") -> None:
        super().__init__(name=name, description="Herramienta de prueba válida.")

    def _get_input_schema(self) -> JSONDict:
        return {"type": "object", "properties": {"val": {"type": "string"}}}

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        return {"result": f"processed_{arguments.get('val', '')}"}


class InvalidDummyTool:
    """Objeto inválido que no hereda de BaseMCPTool ni cumple el contrato."""

    pass


def test_registry_registration_and_lookup() -> None:
    registry = ToolRegistry()
    tool = ValidDummyTool("test_tool_1")

    # Registro exitoso
    assert registry.register(tool) is True
    assert len(registry.list_tools()) == 1

    # Búsqueda O(1)
    retrieved = registry.get_tool("test_tool_1")
    assert retrieved is tool

    # Obtención de esquemas
    schemas = registry.get_schemas()
    assert len(schemas) == 1
    assert schemas[0].name == "test_tool_1"

    # Desregistro
    assert registry.unregister("test_tool_1") is True
    assert len(registry.list_tools()) == 0
    assert registry.get_tool("test_tool_1") is None


def test_registry_validation_rejection() -> None:
    registry = ToolRegistry()

    # Objeto no válido
    invalid = InvalidDummyTool()
    assert registry.register(invalid) is False  # type: ignore[arg-type]

    # Herramienta con nombre vacío
    class EmptyNameTool(ValidDummyTool):
        def __init__(self) -> None:
            super().__init__(name="")

    assert registry.register(EmptyNameTool()) is False


def test_registry_execution() -> None:
    async def _run() -> None:
        registry = ToolRegistry()
        tool = ValidDummyTool("exec_tool")
        registry.register(tool)

        res = await registry.execute_tool("exec_tool", {"val": "hello"})
        assert res.is_success
        assert res.value == {"result": "processed_hello"}

        # Invocación de herramienta inexistente
        fail_res = await registry.execute_tool("non_existent", {})
        assert not fail_res.is_success

    asyncio.run(_run())


def test_registry_discover_valid_tools() -> None:
    registry = ToolRegistry()
    count = registry.discover()
    assert count >= 1
    names = [t.name for t in registry.list_tools()]
    assert "system_health" in names or "calculadora_basica" in names


def test_registry_fault_tolerance_with_broken_module(temp_dir: Path) -> None:
    """Verifica que el registro ignore módulos con errores de sintaxis o importación sin detener el servidor."""
    # Crear carpeta temporary para herramientas
    test_tools_dir = temp_dir / "temp_tools"
    test_tools_dir.mkdir(parents=True, exist_ok=True)

    # 1. Crear un módulo completamente roto con error de sintaxis
    broken_file = test_tools_dir / "broken_tool.py"
    broken_file.write_text("def broken_syntax_func((((:\n    pass\n", encoding="utf-8")

    # 2. Crear un módulo que lanza ImportError
    missing_dep_file = test_tools_dir / "missing_dep_tool.py"
    missing_dep_file.write_text("import non_existent_package_xyz_12345\n", encoding="utf-8")

    # 3. Crear una herramienta válida en el mismo directorio
    valid_file = test_tools_dir / "valid_tool.py"
    valid_file.write_text(
        """from tools.base_tool import BaseMCPTool

class ValidTempTool(BaseMCPTool):
    def __init__(self):
        super().__init__(name="valid_temp_tool", description="Herramienta válida temporal")
    def _get_input_schema(self):
        return {"type": "object", "properties": {}}
    async def _execute_internal(self, arguments):
        return {"status": "ok"}
""",
        encoding="utf-8",
    )

    registry = ToolRegistry()
    # El método discover NO debe lanzar excepción a pesar de los archivos corruptos
    count = registry.discover(tools_dir=test_tools_dir)

    # Debe haber ignorado los 2 archivos con errores y registrado 1 herramienta válida
    assert count == 1
    assert registry.get_tool("valid_temp_tool") is not None
