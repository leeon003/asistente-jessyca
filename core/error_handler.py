"""Manejo global de excepciones y captura decorada para Jessyca Windows MCP.

Proporciona decoradores y funciones utilitarias para interceptar, registrar y procesar
excepciones no controladas de forma limpia sin colapsar la aplicación.
"""

from __future__ import annotations

import functools
import sys
import traceback
from collections.abc import Callable
from typing import Any, TypeVar

from core.exceptions import JessycaError
from core.logger import get_logger
from core.types import Result

logger = get_logger("jessyca.error_handler")

F = TypeVar("F", bound=Callable[..., Any])


def handle_exceptions(
    default_return: Any = None,
    reraise: bool = False,
    return_result: bool = False,
) -> Callable[[F], F]:
    """Decorador síncrono para captura global y segura de excepciones en métodos/funciones.

    Args:
        default_return: Valor a retornar en caso de excepción no controlada si return_result es False.
        reraise: Si es True, relanza la excepción después de registrarla.
        return_result: Si es True, retorna un objeto Result.fail(...) en lugar de default_return.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except JessycaError as e:
                logger.error(f"Excepción de dominio capturada en '{func.__name__}': {e}")
                if reraise:
                    raise
                if return_result:
                    return Result.fail(e)
                return default_return
            except Exception as e:
                logger.critical(
                    f"Excepción no controlada capturada en '{func.__name__}': {e}\n"
                    f"{traceback.format_exc()}"
                )
                if reraise:
                    raise
                if return_result:
                    return Result.fail(e)
                return default_return

        return wrapper  # type: ignore[return-value]

    return decorator


def setup_global_exception_hook() -> None:
    """Configura el hook global sys.excepthook para capturar excepciones no atrapadas a nivel de hilo principal."""

    def handle_uncaught_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: Any,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.critical(
            f"Excepción fatal no capturada a nivel de sistema: {exc_value}",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = handle_uncaught_exception
