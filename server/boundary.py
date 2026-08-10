"""Frontera de ejecución y contrato de abstracción (Subetapa 05.1 & 05.2).

Define el protocolo IExecutionBoundary, la clase SecureExecutionBoundary y StubExecutionBoundary.
GARANTÍA DE SEGURIDAD SUBETAPA 05.2:
SecureExecutionBoundary exige y valida obligatoriamente la evidencia interna de autorización (AuthorizationEvidence)
y su binding criptográfico (action_fingerprint SHA-256) antes de delegar en el ejecutor (DisabledToolExecutor).
NUNCA ejecuta subprocess, PowerShell ni comandos de consola.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from core.logger import get_logger
from server.context import RequestContext
from server.errors import InvalidAuthorizationEvidenceError
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest
from server.executor import DisabledToolExecutor, IToolExecutor

logger = get_logger("jessyca.server.boundary")


class ExecutionStatus(StrEnum):
    """Estados del resultado de la frontera de ejecución."""

    STUB_DISABLED = "STUB_DISABLED"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"
    SUCCESS = "SUCCESS"
    DENIED = "DENIED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ExecutionResult:
    """Resultado estructurado del intento de ejecución en la frontera."""

    status: ExecutionStatus
    request_id: str
    tool_name: str
    operation: str
    output: Any = None
    message: str = ""
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario explícito del resultado."""
        return {
            "status": self.status.value,
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "output": self.output,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }


class IExecutionBoundary(Protocol):
    """Protocolo del contrato de la frontera de ejecución de herramientas MCP."""

    def execute(self, context: RequestContext, parameters: dict[str, Any]) -> ExecutionResult:
        """Ejecuta una herramienta dentro de la frontera de seguridad."""
        ...


class StubExecutionBoundary:
    """Implementación Stub segura de la frontera de ejecución (Subetapa 05.1).

    GARANTÍA ABSOLUTA DE SEGURIDAD:
    Esta clase es un Stub puro. NO invoca subprocess, NO invoca PowerShell, NO invoca
    herramientas de archivos/procesos/registro de Windows y NO ejecuta ningún comando.
    """

    def execute(self, context: RequestContext, parameters: dict[str, Any]) -> ExecutionResult:
        """Devuelve un resultado Stub indicando que la ejecución real no está habilitada."""
        logger.info(
            f"[STUB EXECUTION BOUNDARY] Solicitud recibida para '{context.tool_name}.{context.operation}'. "
            "Ejecución real no habilitada en Subetapa 05.1."
        )

        return ExecutionResult(
            status=ExecutionStatus.STUB_DISABLED,
            request_id=context.request_id,
            tool_name=context.tool_name,
            operation=context.operation,
            output=None,
            message=f"Ejecución Stub: La herramienta '{context.tool_name}' no se ejecuta en la Subetapa 05.1.",
            duration_ms=0.0,
            timestamp=datetime.now(UTC),
        )


class SecureExecutionBoundary:
    """Frontera de ejecución segura que exige y valida AuthorizationEvidence (Subetapa 05.2 & 06.2)."""

    def __init__(self, executor: IToolExecutor | None = None) -> None:
        self.default_executor: IToolExecutor = executor or DisabledToolExecutor()
        self.domain_executors: dict[str, IToolExecutor] = {}

    def register_executor(self, tool_domain: str, executor: IToolExecutor) -> None:
        """Registra un ejecutor de herramientas específico para un dominio."""
        self.domain_executors[tool_domain.strip().lower()] = executor

    def get_executor_for_request(self, request: ExecutionRequest) -> IToolExecutor:
        """Obtiene el ejecutor registrado para la herramienta o retorna el ejecutor por defecto."""
        tool_clean = request.tool_name.strip().lower()
        if tool_clean in self.domain_executors:
            return self.domain_executors[tool_clean]

        for domain, exec_inst in self.domain_executors.items():
            if tool_clean.startswith(domain):
                return exec_inst

        return self.default_executor

    def execute_with_evidence(
        self,
        request: ExecutionRequest,
        evidence: AuthorizationEvidence,
    ) -> ExecutionResult:
        """Valida obligatoriamente la evidencia interna de autorización antes de delegar al ejecutor."""
        if evidence is None or not isinstance(evidence, AuthorizationEvidence):
            logger.error(f"[SECURITY BOUNDARY] Evidencia de autorización nula o inválida para request [{request.request_id}]")
            raise InvalidAuthorizationEvidenceError("Evidencia de autorización ausente o inválida.")

        # Verificar integridad criptográfica por action_fingerprint
        is_valid = evidence.validate_integrity(
            tool_name=request.tool_name,
            operation=request.operation,
            parameters=request.parameters,
            request_id=request.request_id,
        )

        if not is_valid:
            logger.error(
                f"[SECURITY BOUNDARY] Mismatch o tampering detectado en evidencia [{evidence.evidence_id}] "
                f"para herramienta '{request.tool_name}.{request.operation}'"
            )
            raise InvalidAuthorizationEvidenceError(
                f"La evidencia de autorización para '{request.tool_name}' fue modificada o no coincide con los parámetros canónicos."
            )

        target_executor = self.get_executor_for_request(request)

        logger.info(
            f"[SECURITY BOUNDARY] Evidencia [{evidence.evidence_id[:8]}] validada exitosamente. "
            f"Delegando a IToolExecutor ({type(target_executor).__name__})..."
        )
        return target_executor.execute(request, evidence)

    def execute(self, context: RequestContext, parameters: dict[str, Any]) -> ExecutionResult:
        """Método compatible con IExecutionBoundary. Recomienda el flujo seguro con evidencia."""
        logger.warning("[SECURITY BOUNDARY] Invocación sin evidencia directa. Redirigiendo a respuesta de seguridad.")
        return ExecutionResult(
            status=ExecutionStatus.DENIED,
            request_id=context.request_id,
            tool_name=context.tool_name,
            operation=context.operation,
            message="Ejecución Rechazada: Se requiere AuthorizationEvidence generada por SecureExecutionPipeline.",
        )
