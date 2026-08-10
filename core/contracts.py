"""Contratos base e interfaces abstractas (Protocols / ABCs) para Jessyca Windows MCP.

Aplica el Principio de Inversión de Dependencias (DIP) de SOLID para asegurar
que las capas superiores e inferiores dependan de abstracciones y no de concreciones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class ISecurityManager(Protocol):
    """Protocolo para la evaluación de seguridad, políticas y permisos."""

    def evaluate(self, profile: Any, user: str = "system") -> Any:
        """Evalúa el perfil de seguridad de una herramienta."""
        ...

    def grant_permission(self, permission: str) -> None:
        """Otorga un permiso al entorno."""
        ...

    def revoke_permission(self, permission: str) -> None:
        """Revoca un permiso del entorno."""
        ...

    def add_to_blacklist(self, tool_name: str) -> None:
        """Añade una herramienta a la lista negra."""
        ...

    def add_to_whitelist(self, tool_name: str) -> None:
        """Añade una herramienta a la lista blanca."""
        ...

    def get_audit_log(self) -> list[Any]:
        """Obtiene la lista inmutable de auditoría."""
        ...


@runtime_checkable
class ISecurityEvaluator(Protocol):
    """Protocolo/Interfaz abstracta para el evaluador central de seguridad (Subetapa 04.1)."""

    def evaluate(self, request: Any) -> Any:
        """Evalúa una solicitud de seguridad de herramienta."""
        ...


@runtime_checkable
class IRiskEvaluator(Protocol):
    """Protocolo/Interfaz abstracta para el motor de evaluación de riesgo (Subetapa 04.2)."""

    def evaluate_risk(self, request_or_profile: Any, arguments: dict[str, Any] | None = None) -> Any:
        """Calcula deterministamente el nivel de riesgo de una solicitud u operación."""
        ...


@runtime_checkable
class IPermissionManager(Protocol):
    """Protocolo/Interfaz abstracta para el gestor de autorización y permisos (Subetapa 04.3)."""

    def evaluate_permission(self, request: Any) -> Any:
        """Evalúa una solicitud de autorización y devuelve el resultado de permiso."""
        ...


@runtime_checkable
class IConfirmationProvider(Protocol):
    """Protocolo/Interfaz abstracta para el proveedor de confirmaciones (Subetapa 04.4)."""

    def request_confirmation(self, request: Any) -> Any:
        """Solicita la respuesta del proveedor de confirmación."""
        ...


@runtime_checkable
class IConfirmationManager(Protocol):
    """Protocolo/Interfaz abstracta para el gestor de confirmaciones (Subetapa 04.4)."""

    def submit_request(self, request: Any, provider: Any = None) -> Any:
        """Envía una solicitud de confirmación al proveedor."""
        ...

    def consume_confirmation(self, request_id: str, tool_name: str, operation: str, parameters: dict[str, Any]) -> bool:
        """Consume una confirmación verificando binding de fingerprint y expiración."""
        ...


@runtime_checkable
class IPolicyEvaluator(Protocol):
    """Protocolo/Interfaz abstracta para el evaluador de políticas de seguridad (Subetapa 04.5)."""

    def evaluate_policy(
        self,
        context: Any,
        metadata: Any,
        risk_assessment: Any,
        policy: Any = None,
    ) -> Any:
        """Evalúa una solicitud con respecto a una Security Policy y un RiskAssessment."""
        ...


@runtime_checkable
class IPolicyProvider(Protocol):
    """Protocolo/Interfaz abstracta para los proveedores de Security Policy (Subetapa 04.5)."""

    def get_policy(self) -> Any:
        """Obtiene la Security Policy declarada para la aplicación."""
        ...


@runtime_checkable
class IAuditSink(Protocol):
    """Protocolo/Interfaz abstracta para la persistencia desacoplada de auditoría (Subetapa 04.6)."""

    def emit(self, event: Any) -> None:
        """Persiste o emite un evento de auditoría sanitizado."""
        ...


@runtime_checkable
class IAuditLogger(Protocol):
    """Protocolo/Interfaz abstracta para el gestor central de auditoría (Subetapa 04.6)."""

    def log_event(self, event: Any) -> Any:
        """Recibe, sanitiza y emite un evento de auditoría a través de sus sinks."""
        ...


