"""Pruebas de la frontera de ejecución Stub Execution Boundary (Subetapa 05.1)."""

from __future__ import annotations

from server.app import JessycaMCPServer
from server.boundary import ExecutionStatus, StubExecutionBoundary
from server.context import create_request_context
from tools.base import BaseTool
from tools.tool_registry import ToolRegistry


from typing import Any


class DummyExecutionTool(BaseTool):
    """Herramienta de prueba."""

    def __init__(self, name: str = "stub_tool") -> None:
        super().__init__(
            name=name,
            description="Herramienta stub",
            category="stub",
        )

    def _get_input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def _execute_internal(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("CRÍTICO: La ejecución real de herramientas NO debe ocurrir en la Subetapa 05.1.")


def test_stub_execution_boundary_returns_disabled_status() -> None:
    boundary = StubExecutionBoundary()
    ctx = create_request_context(tool_name="stub_tool", operation="delete")

    res = boundary.execute(ctx, {"path": "C:\\temp\\file.txt"})

    assert res.status == ExecutionStatus.STUB_DISABLED
    assert res.tool_name == "stub_tool"
    assert res.operation == "delete"
    assert res.output is None
    assert "Subetapa 05.1" in res.message


def test_mcp_server_no_real_tool_execution_guarantee() -> None:
    registry = ToolRegistry()
    registry.register(DummyExecutionTool("stub_tool"))

    server = JessycaMCPServer(tool_registry=registry)
    server.start()

    # handle_request debe retornar el resultado del Stub sin invocar el método execute real de la herramienta
    res = server.handle_request({"tool_name": "stub_tool", "operation": "run"})

    assert res.status in (ExecutionStatus.STUB_DISABLED, ExecutionStatus.EXECUTION_DISABLED)
    assert res.tool_name == "stub_tool"

    server.shutdown()


def test_no_powershell_or_cmd_execution_in_server() -> None:
    server = JessycaMCPServer()
    server.start()

    # Verificar que el servidor MCP no tenga métodos para invocar subprocess, PowerShell o CMD
    assert not hasattr(server, "execute_powershell")
    assert not hasattr(server, "execute_cmd")
    assert not hasattr(server, "run_shell_command")

    server.shutdown()


def test_server_does_not_mutate_security_policy() -> None:
    server = JessycaMCPServer()
    assert not hasattr(server, "modify_policy")
    assert not hasattr(server, "disable_security")


def test_internal_errors_do_not_expose_secrets() -> None:
    boundary = StubExecutionBoundary()
    ctx = create_request_context(
        tool_name="stub_tool",
        parameters={"password": "MySuperSecretPassword123!", "path": "C:\\temp"},
    )
    res = boundary.execute(ctx, ctx.parameters)
    res_dict = res.to_dict()

    # Verificar que las cadenas de mensaje o salida no expongan contraseñas
    assert "MySuperSecretPassword123!" not in str(res_dict)
    assert "MySuperSecretPassword123!" not in res.message
