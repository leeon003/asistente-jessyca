"""Servidor MCP principal FastMCP para Jessyca Windows MCP (Subetapa 05.1).

Proporciona la infraestructura central del servidor FastMCP, integración con ToolRegistry,
administración del ciclo de vida, diagnósticos de salud y frontera de ejecución (StubExecutionBoundary).
"""

from __future__ import annotations

from typing import Any

from config.settings import AppSettings
from core.logger import get_logger
from core.types import JSONDict
from server.boundary import ExecutionResult, IExecutionBoundary, StubExecutionBoundary
from server.context import RequestContext, create_request_context
from server.errors import MCPServerNotInitializedError, MCPToolNotFoundError, MCPValidationError
from server.health import HealthChecker, HealthCheckResult
from server.lifecycle import LifecycleState, ServerLifecycleManager
from tools.registry import ToolRegistry, get_tool_registry

from server.execution_request import ExecutionRequest, create_execution_request
from server.pipeline import SecureExecutionPipeline

logger = get_logger("jessyca.server.app")

# Intento opcional de importar FastMCP si está disponible en el entorno
try:
    from fastmcp import FastMCP  # type: ignore[import-not-found,import-untyped]
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False
    FastMCP = None


class JessycaMCPServer:
    """Servidor MCP principal FastMCP para Jessyca Windows MCP."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        tool_registry: ToolRegistry | None = None,
        lifecycle_manager: ServerLifecycleManager | None = None,
        execution_boundary: IExecutionBoundary | None = None,
        pipeline: SecureExecutionPipeline | None = None,
    ) -> None:
        self.settings = settings or AppSettings()
        self.tool_registry = tool_registry or get_tool_registry()
        self.lifecycle_manager = lifecycle_manager or ServerLifecycleManager()
        self.execution_boundary = execution_boundary or StubExecutionBoundary()

        sec_boundary = self.execution_boundary if hasattr(self.execution_boundary, "execute_with_evidence") else None
        self.pipeline = pipeline or SecureExecutionPipeline(execution_boundary=sec_boundary)  # type: ignore[arg-type]

        self.server_name = self.settings.MCP_SERVER_NAME
        self.version = self.settings.MCP_SERVER_VERSION
        self.host = self.settings.MCP_SERVER_HOST
        self.port = self.settings.MCP_SERVER_PORT
        self.transport = self.settings.MCP_TRANSPORT

        self.health_checker = HealthChecker(
            server_name=self.server_name,
            version=self.version,
            lifecycle_manager=self.lifecycle_manager,
            tool_registry=self.tool_registry,
        )

        self._fastmcp_instance: Any = None
        if HAS_FASTMCP and FastMCP is not None:
            try:
                self._fastmcp_instance = FastMCP(name=self.server_name, version=self.version)
            except Exception as e:
                logger.warning(f"No se pudo instanciar FastMCP SDK: {e}")

    @property
    def state(self) -> LifecycleState:
        """Devuelve el estado actual del ciclo de vida del servidor."""
        return self.lifecycle_manager.state

    @property
    def is_running(self) -> bool:
        """Indica si el servidor está en ejecución."""
        return self.lifecycle_manager.is_running

    def initialize(self) -> None:
        """Inicializa los componentes del servidor MCP."""
        logger.info(f"Inicializando servidor MCP '{self.server_name}' v{self.version}...")
        self.lifecycle_manager.initialize()

    def start(self) -> None:
        """Inicia el servidor MCP."""
        if self.lifecycle_manager.state == LifecycleState.STOPPED:
            self.initialize()
        self.lifecycle_manager.start()
        logger.info(f"Servidor MCP corriendo en {self.host}:{self.port} (transporte: {self.transport})")

    def shutdown(self) -> None:
        """Detiene el servidor MCP limpiamente."""
        logger.info("Solicitud de apagado del servidor MCP...")
        self.lifecycle_manager.shutdown()

    def check_health(self) -> HealthCheckResult:
        """Devuelve el estado estructurado de salud del servidor."""
        return self.health_checker.check_health()

    def list_tools(self) -> list[JSONDict]:
        """Devuelve la lista de metadatos de herramientas registradas en el ToolRegistry."""
        tools_info: list[JSONDict] = []
        for tool_name in self.tool_registry.list_tools():
            tool_obj = self.tool_registry.get_tool(tool_name)
            if tool_obj:
                info = getattr(tool_obj, "metadata", None)
                if info and hasattr(info, "to_dict"):
                    tools_info.append(info.to_dict())
                else:
                    tools_info.append({"name": tool_name, "description": "Herramienta registrada"})
        return tools_info

    def get_tool_info(self, tool_name: str) -> JSONDict:
        """Obtiene la información y metadatos de una herramienta específica."""
        if not tool_name or not tool_name.strip():
            raise MCPValidationError("El nombre de la herramienta no puede estar vacío.")

        tool = self.tool_registry.get_tool(tool_name.strip())
        if not tool:
            raise MCPToolNotFoundError(tool_name)

        meta = getattr(tool, "metadata", None)
        if meta and hasattr(meta, "to_dict"):
            return meta.to_dict()  # type: ignore[no-any-return]
        return {"name": tool_name, "description": "Herramienta registrada"}

    def handle_request(
        self,
        payload: dict[str, Any],
        confirmation_provider: Any = None,
    ) -> ExecutionResult:
        """Procesa una solicitud MCP recibida a través del SecureExecutionPipeline.

        GARANTÍA DE SEGURIDAD SUBETAPA 05.2:
        1. Las decisiones de seguridad enviadas en payload son ignoradas/sanitizadas.
        2. La solicitud atraviesa las 6 capas de seguridad en orden determinista.
        3. La ejecución es delegada a self.pipeline (SecureExecutionPipeline -> DisabledToolExecutor), que NO ejecuta comandos.
        """
        if not self.is_running:
            raise MCPServerNotInitializedError(
                f"El servidor MCP se encuentra en estado '{self.state.value}'. Inicie el servidor antes de enviar solicitudes."
            )

        if not isinstance(payload, dict):
            raise MCPValidationError("El payload de la solicitud debe ser un diccionario JSON válido.")

        tool_name = str(payload.get("tool_name") or payload.get("name") or "").strip()
        if not tool_name:
            raise MCPValidationError("La solicitud MCP debe especificar 'tool_name'.")

        if not self.tool_registry.has_tool(tool_name):
            raise MCPToolNotFoundError(tool_name)

        operation = str(payload.get("operation") or "execute").strip()
        parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

        # 1. Crear ExecutionRequest e isolar parámetros no confiables
        exec_request = create_execution_request(
            tool_name=tool_name,
            operation=operation,
            parameters=parameters,
            metadata=metadata,
        )

        # 2. Delegar la ejecución al SecureExecutionPipeline
        return self.pipeline.execute_request(exec_request, confirmation_provider=confirmation_provider)


# Instancia Singleton Global
_global_mcp_server: JessycaMCPServer | None = None


def get_mcp_server() -> JessycaMCPServer:
    """Obtiene la instancia global del servidor MCP."""
    global _global_mcp_server
    if _global_mcp_server is None:
        _global_mcp_server = JessycaMCPServer()
    return _global_mcp_server
