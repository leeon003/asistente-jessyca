"""Modelos de datos y definiciones tipadas para la Capa de Integraciones (Integration Hub / Adapter Layer).

Soporta el principio fundamental de JESSYCA 4.0:
    EXECUTE → VERIFY → REPORT
Garantizando que ninguna integración declare éxito sin evidencia verificada.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.execution.execution_verifier import ExecutionStatus
from core.security import RiskLevel


class IntegrationStatus(StrEnum):
    """Estados del ciclo de vida y disponibilidad de un Adapter de integración."""

    AVAILABLE = "AVAILABLE"          # Presente en el registro y listo para inicializar
    INITIALIZING = "INITIALIZING"    # Proceso de inicialización en curso
    READY = "READY"                  # Inicializado correctamente y operativo
    DEGRADED = "DEGRADED"            # Funciona parcialmente o con advertencias
    DISABLED = "DISABLED"            # Deshabilitado explícitamente por configuración o usuario
    ERROR = "ERROR"                  # Falló durante inicialización o ejecución crítica
    UNAVAILABLE = "UNAVAILABLE"      # Dependencias o recursos no disponibles en el entorno


@dataclass(frozen=True)
class IntegrationCapability:
    """Capacidad específica expuesta por un Integration Adapter.

    Una integración no debe exponer directamente toda su API cruda, sino capacidades
    acotadas con metadatos de riesgo y permisos.
    """

    name: str
    description: str
    required_risk_level: RiskLevel = RiskLevel.SAFE
    required_permissions: list[str] = field(default_factory=list)
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IntegrationHealth:
    """Estado de salud y diagnóstico de un Adapter."""

    status: IntegrationStatus
    is_healthy: bool
    latency_ms: float = 0.0
    message: str = "OK"
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: float = field(default_factory=time.time)


@dataclass
class IntegrationContext:
    """Contexto de ejecución transferido hacia el Integration Adapter."""

    session_id: str
    user_id: str = "user"
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0


@dataclass
class IntegrationExecutionResult:
    """Resultado formal inmutable o estructurado de una ejecución de capacidad.

    Separa taxativamente la ejecución de la verificación:
    - executed: si la invocación técnica se completó
    - verified: si existe evidencia comprobada externa de éxito
    - verification_required: si la operación requiere comprobación posterior
    """

    executed: bool
    status: ExecutionStatus
    verified: bool = False
    verification_required: bool = True
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    evidence: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def claims_success(self) -> bool:
        """Determina si la acción afirma éxito genuino con evidencia comprobable.

        Bajo ninguna circunstancia claims_success será True si verified es False.
        """
        return self.executed and self.verified and self.status == ExecutionStatus.SUCCEEDED

    def to_dict(self) -> dict[str, Any]:
        return {
            "executed": self.executed,
            "status": self.status.value if isinstance(self.status, ExecutionStatus) else str(self.status),
            "verified": self.verified,
            "verification_required": self.verification_required,
            "claims_success": self.claims_success,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "evidence": self.evidence,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class IntegrationInfo:
    """Resumen para inspección, observabilidad y listados del registro."""

    name: str
    version: str
    status: IntegrationStatus
    capabilities: list[str]
    dependencies: list[str]
    enabled: bool
    health: IntegrationHealth | None = None
