"""Pruebas unitarias de la jerarquía de excepciones y decoradores de error."""

from __future__ import annotations

from core.error_handler import handle_exceptions
from core.exceptions import ConfigurationError, ToolExecutionError
from core.types import Result


def test_jessyca_error_to_dict() -> None:
    err = ConfigurationError("Error de prueba", details={"key": "val"})
    assert err.code == "ConfigurationError"
    assert err.message == "Error de prueba"
    d = err.to_dict()
    assert d["error"] == "ConfigurationError"
    assert d["details"]["key"] == "val"


def test_handle_exceptions_decorator_default_return() -> None:
    @handle_exceptions(default_return="fallback")
    def faulty_func() -> str:
        raise ToolExecutionError("Fallo intencional")

    res = faulty_func()
    assert res == "fallback"


def test_handle_exceptions_decorator_return_result() -> None:
    @handle_exceptions(return_result=True)
    def faulty_func() -> int:
        raise ValueError("Error genérico")

    res = faulty_func()
    assert isinstance(res, Result)
    assert not res.is_success
