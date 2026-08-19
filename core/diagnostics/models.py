"""Modelos de Datos para el Sistema de Autodiagnóstico (Etapa 17.2).

Define:
  - HealthStatus: Estados canónicos (HEALTHY, DEGRADED, FAILED, DISABLED).
  - HealthCheck: Resultado individual de un sondeo o chequeo de salud de un componente.
  - HealthReport: Informe integral del estado operativo del sistema y capacidades disponibles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class HealthStatus(StrEnum):
    """Estados canónicos de salud operativa del sistema y sus subsistemas."""

    HEALTHY = "HEALTHY"
    """El componente está 100% operativo y listo para atender solicitudes."""

    DEGRADED = "DEGRADED"
    """El componente opera parcialmente, con latencia elevada o capacidades reducidas."""

    FAILED = "FAILED"
    """El componente no está disponible o ha fallado críticamente."""

    DISABLED = "DISABLED"
    """El componente ha sido desactivado explícitamente por configuración o seguridad."""


class ComponentCategory(StrEnum):
    """Categorías de componentes sujetos a diagnóstico de salud."""

    SERVICE = "SERVICE"
    BROWSER = "BROWSER"
    OCR = "OCR"
    MICROPHONE = "MICROPHONE"
    OLLAMA = "OLLAMA"
    VECTOR_STORE = "VECTOR_STORE"
    SCHEDULER = "SCHEDULER"
    PLUGIN = "PLUGIN"
    SYSTEM = "SYSTEM"
    RESOURCES = "RESOURCES"


@dataclass(frozen=True)
class HealthCheck:
    """Resultado inmutable de un chequeo de salud individual para un componente o subsistema."""

    name: str
    component: str
    status: HealthStatus
    message: str
    category: ComponentCategory = ComponentCategory.SYSTEM
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = 0.0
    is_critical: bool = False
    remedy_suggestion: str = ""

    @property
    def is_available(self) -> bool:
        """Determina si el componente puede utilizarse operativamente."""
        return self.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el chequeo de salud a formato estructurado machine-readable."""
        return {
            "name": self.name,
            "component": self.component,
            "category": self.category.value,
            "status": self.status.value,
            "message": self.message,
            "is_available": self.is_available,
            "is_critical": self.is_critical,
            "duration_ms": round(self.duration_ms, 2),
            "checked_at": self.checked_at.isoformat(),
            "details": self.details,
            "remedy_suggestion": self.remedy_suggestion,
        }


@dataclass(frozen=True)
class HealthReport:
    """Informe integral de diagnóstico del sistema JESSYCA 3.0."""

    overall_status: HealthStatus
    checks: dict[str, HealthCheck]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    unavailable_components: list[str] = field(default_factory=list)
    user_friendly_messages: list[str] = field(default_factory=list)
    error_rate: float = 0.0
    repeated_failures_count: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_component_available(self, component_name: str) -> bool:
        """Verifica si un componente específico está disponible según los chequeos."""
        key = component_name.strip().lower()
        for check_name, check in self.checks.items():
            if check_name.lower() == key or check.component.lower() == key:
                return check.is_available
        # Si no está en el reporte, asumimos disponible por defecto o no diagnosticado
        return True

    def get_user_notice(self, component_name: str) -> str | None:
        """Retorna un mensaje legible para el usuario si el componente no está disponible."""
        key = component_name.strip().lower()
        for check_name, check in self.checks.items():
            if (check_name.lower() == key or check.component.lower() == key) and not check.is_available:
                return check.message
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialización estructurada completa del reporte de diagnóstico."""
        return {
            "overall_status": self.overall_status.value,
            "timestamp": self.timestamp.isoformat(),
            "checks": {k: v.to_dict() for k, v in self.checks.items()},
            "unavailable_components": self.unavailable_components,
            "user_friendly_messages": self.user_friendly_messages,
            "error_rate": round(self.error_rate, 4),
            "repeated_failures_count": self.repeated_failures_count,
            "metadata": self.metadata,
        }

    def to_summary(self) -> str:
        """Genera un resumen textual legible por humanos del estado de salud."""
        lines = [f"[HEALTH REPORT] Overall Status: {self.overall_status.value}"]
        if self.user_friendly_messages:
            lines.append("Warnings / Unavailable Services:")
            for msg in self.user_friendly_messages:
                lines.append(f"  - {msg}")
        else:
            lines.append("All probed subsystems are operational.")
        return "\n".join(lines)
