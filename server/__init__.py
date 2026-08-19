"""Módulo de infraestructura del servidor FastMCP y pipeline de ejecución segura para Jessyca Windows MCP (Subetapa 05.2)."""

from server.aggregator import AggregatedSecurityDecision, SecurityDecisionAggregator
from server.app import JessycaMCPServer, get_mcp_server
from server.boundary import (
    ExecutionResult,
    ExecutionStatus,
    IExecutionBoundary,
    SecureExecutionBoundary,
    StubExecutionBoundary,
)
from server.context import RequestContext, create_request_context
from server.errors import (
    ExecutionDisabledError,
    ExecutionNotAuthorizedError,
    ExecutionPipelineError,
    InvalidAuthorizationEvidenceError,
    MCPError,
    MCPInternalError,
    MCPServerNotInitializedError,
    MCPServerStateError,
    MCPToolNotFoundError,
    MCPValidationError,
    SecurityAuthorizationError,
)
from server.evidence import (
    AuthorizationEvidence,
    compute_evidence_fingerprint,
    create_authorization_evidence,
)
from server.execution_request import ExecutionRequest, create_execution_request
from server.executor import DisabledToolExecutor, IToolExecutor
from server.health import HealthChecker, HealthCheckResult, HealthStatus
from server.lifecycle import LifecycleState, ServerLifecycleManager

ServerLifecycleState = LifecycleState
from server.pipeline import SecureExecutionPipeline


def create_mcp_server(
    server_name: str | None = None,
    tools_dir: str | None = None,
) -> JessycaMCPServer:
    """Factory function que crea e inicializa un JessycaMCPServer."""
    from config.settings import AppSettings

    settings = AppSettings()
    if server_name:
        settings.MCP_SERVER_NAME = server_name

    server = JessycaMCPServer(settings=settings)
    server.initialize()
    return server

__all__ = [
    "JessycaMCPServer",
    "create_mcp_server",
    "get_mcp_server",
    "LifecycleState",
    "ServerLifecycleState",
    "ServerLifecycleManager",
    "RequestContext",
    "create_request_context",
    "ExecutionRequest",
    "create_execution_request",
    "AuthorizationEvidence",
    "create_authorization_evidence",
    "compute_evidence_fingerprint",
    "AggregatedSecurityDecision",
    "SecurityDecisionAggregator",
    "HealthStatus",
    "HealthCheckResult",
    "HealthChecker",
    "ExecutionStatus",
    "ExecutionResult",
    "IExecutionBoundary",
    "StubExecutionBoundary",
    "SecureExecutionBoundary",
    "IToolExecutor",
    "DisabledToolExecutor",
    "SecureExecutionPipeline",
    "MCPError",
    "MCPServerNotInitializedError",
    "MCPServerStateError",
    "MCPToolNotFoundError",
    "MCPValidationError",
    "MCPInternalError",
    "ExecutionPipelineError",
    "SecurityAuthorizationError",
    "InvalidAuthorizationEvidenceError",
    "ExecutionNotAuthorizedError",
    "ExecutionDisabledError",
]
