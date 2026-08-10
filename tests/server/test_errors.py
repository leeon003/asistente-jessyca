"""Pruebas de la jerarquía de excepciones del servidor MCP (Subetapa 05.1)."""

from __future__ import annotations

from core.exceptions import MCPError
from server.errors import (
    MCPInternalError,
    MCPServerNotInitializedError,
    MCPServerStateError,
    MCPToolNotFoundError,
    MCPValidationError,
)


def test_mcp_exception_hierarchy() -> None:
    err1 = MCPServerNotInitializedError()
    assert isinstance(err1, MCPError)
    assert "no se encuentra inicializado" in str(err1)

    err2 = MCPServerStateError("STOPPED", "start_job")
    assert isinstance(err2, MCPError)
    assert err2.current_state == "STOPPED"
    assert err2.action == "start_job"

    err3 = MCPToolNotFoundError("unknown_tool")
    assert isinstance(err3, MCPError)
    assert err3.tool_name == "unknown_tool"

    err4 = MCPValidationError("Bad param", details={"field": "path"})
    assert isinstance(err4, MCPError)
    assert err4.details["field"] == "path"

    err5 = MCPInternalError("Internal error")
    assert isinstance(err5, MCPError)
