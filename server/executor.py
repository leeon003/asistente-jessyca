"""Contrato IToolExecutor e implementación DisabledToolExecutor (Subetapa 05.2).

Establece la frontera de abstracción del ejecutor de herramientas.
GARANTÍA DE SEGURIDAD ABSOLUTA SUBETAPA 05.2:
DisabledToolExecutor NUNCA ejecuta herramientas reales de Windows, ni scripts de PowerShell,
ni comandos de subprocess o consola. Devuelve un resultado determinista indicando que la ejecución
real está deshabilitada en la Subetapa 05.2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from core.logger import get_logger
from server.boundary import ExecutionResult, ExecutionStatus
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest

logger = get_logger("jessyca.server.executor")


class IToolExecutor(Protocol):
    """Protocolo abstracto para ejecutores de herramientas en la frontera de seguridad."""

    def execute(
        self,
        request: ExecutionRequest,
        evidence: AuthorizationEvidence,
    ) -> ExecutionResult:
        """Ejecuta una herramienta validada por la frontera de seguridad."""
        ...


class DisabledToolExecutor:
    """Ejecutor deshabilitado seguro para la Subetapa 05.2.

    GARANTÍA ABSOLUTA DE SEGURIDAD:
    NO invoca subprocess, NO invoca PowerShell, NO invoca CMD, NO invoca ctypes ni APIs mutables de Windows.
     Devuelve un resultado EXECUTION_DISABLED_IN_05_2 controlado.
    """

    def execute(
        self,
        request: ExecutionRequest,
        evidence: AuthorizationEvidence,
    ) -> ExecutionResult:
        """Retorna un resultado determinista indicando que la ejecución real está deshabilitada."""
        logger.info(
            f"[DISABLED TOOL EXECUTOR] Recibida solicitud autorizada '{request.tool_name}.{request.operation}' "
            f"con evidencia [{evidence.evidence_id[:8]}]. Ejecución real deshabilitada en 05.2."
        )

        return ExecutionResult(
            status=ExecutionStatus.EXECUTION_DISABLED,
            request_id=request.request_id,
            tool_name=request.tool_name,
            operation=request.operation,
            output=None,
            message=f"EXECUTION_DISABLED_IN_05_2: La herramienta '{request.tool_name}' no se ejecuta en 05.2.",
            duration_ms=0.0,
            timestamp=datetime.now(UTC),
        )
