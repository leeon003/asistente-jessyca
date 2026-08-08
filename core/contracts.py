"""Contratos base e interfaces abstractas (Protocols / ABCs) para Jessyca Windows MCP.

Aplica el Principio de Inversión de Dependencias (DIP) de SOLID para asegurar
que las capas superiores e inferiores dependan de abstracciones y no de concreciones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from core.types import JSONDict, Result


@runtime_checkable
class IService(Protocol):
    """Protocolo base para todos los servicios de la aplicación."""

    @property
    def service_name(self) -> str:
        """Nombre identificador del servicio."""
        ...

    @property
    def is_initialized(self) -> bool:
        """Indica si el servicio ha sido inicializado correctamente."""
        ...

    def initialize(self) -> None:
        """Inicializa los recursos del servicio."""
        ...

    def shutdown(self) -> None:
        """Libera de manera limpia los recursos del servicio."""
        ...


class ITool(ABC):
    """Clase base abstracta para la especificación de Herramientas MCP."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre único de la herramienta MCP."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Descripción funcional de la herramienta para el modelo de lenguaje."""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> JSONDict:
        """Esquema JSON Schema de los parámetros de entrada."""
        pass

    @abstractmethod
    async def execute(self, arguments: JSONDict) -> Result[JSONDict]:
        """Ejecuta la herramienta con los argumentos proporcionados de forma asíncrona."""
        pass


@runtime_checkable
class IToolRegistry(Protocol):
    """Protocolo para el registro y resolución dinámica de herramientas MCP."""

    def register(self, tool: ITool) -> bool:
        """Registra una nueva herramienta MCP."""
        ...

    def unregister(self, name: str) -> bool:
        """Elimina una herramienta del registro."""
        ...

    def get_tool(self, name: str) -> ITool | None:
        """Obtiene una herramienta registrada por su nombre."""
        ...

    def list_tools(self) -> list[ITool]:
        """Lista todas las herramientas registradas."""
        ...
