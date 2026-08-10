"""Modelos inmutables para la fase de verificación post-acción VERIFY (`windows.desktop` - Subetapa 08.4).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
Modelos inmutables congelados (`@dataclass(frozen=True)`).
No asume el éxito de una acción únicamente por el envío del evento. Representa estados esperados y observados.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class VerificationStatus(StrEnum):
    """Estados controlados de verificación post-acción visual."""

    PENDING = "PENDING"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFICATION_TIMEOUT = "VERIFICATION_TIMEOUT"
    CONFIDENCE_FAILED = "CONFIDENCE_FAILED"
    ABORTED_BY_EMERGENCY_STOP = "ABORTED_BY_EMERGENCY_STOP"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class ExpectedState:
    """Estado UI inmutable esperado tras la ejecución de una acción gráfica."""

    expected_window_title: str | None = None
    expected_control_type: str | None = None
    expected_text: str | None = None
    expected_state_hash: str | None = None
    expect_disappearance: bool = False
    expect_value_match: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convierte el estado esperado a diccionario estructurado."""
        return {
            "expected_window_title": self.expected_window_title,
            "expected_control_type": self.expected_control_type,
            "expected_text_length": len(self.expected_text) if self.expected_text else 0,
            "expected_state_hash": self.expected_state_hash,
            "expect_disappearance": self.expect_disappearance,
            "expect_value_match": self.expect_value_match,
        }


@dataclass(frozen=True)
class ObservedState:
    """Estado UI inmutable inspeccionado tras la ejecución de una acción gráfica."""

    observed_window_title: str | None
    observed_control_type: str | None
    observed_text: str | None
    observed_state_hash: str | None
    observed_confidence: float
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte el estado observado a diccionario estructurado con privacidad de texto."""
        return {
            "observed_window_title": self.observed_window_title,
            "observed_control_type": self.observed_control_type,
            "observed_text_length": len(self.observed_text) if self.observed_text else 0,
            "observed_state_hash": self.observed_state_hash,
            "observed_confidence": round(self.observed_confidence, 2),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class ActionVerificationRequest:
    """Parámetros inmutables de solicitud para la fase VERIFY post-acción."""

    action_id: str
    action_type: str
    expected_state: ExpectedState
    poll_interval_seconds: float = 0.1
    timeout_seconds: float = 5.0
    min_confidence: float = 0.70

    def to_dict(self) -> dict[str, Any]:
        """Convierte la solicitud de verificación a diccionario estructurado."""
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "expected_state": self.expected_state.to_dict(),
            "poll_interval_seconds": self.poll_interval_seconds,
            "timeout_seconds": self.timeout_seconds,
            "min_confidence": self.min_confidence,
        }


@dataclass(frozen=True)
class VerificationResult:
    """Resultado inmutable del proceso de verificación de estado post-acción."""

    status: VerificationStatus
    success: bool
    expected: ExpectedState
    observed: ObservedState | None
    confidence: float
    processing_time_ms: float
    reason: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado de verificación a diccionario estructurado seguro para auditoría."""
        return {
            "status": str(self.status),
            "success": self.success,
            "expected": self.expected.to_dict(),
            "observed": self.observed.to_dict() if self.observed else None,
            "confidence": round(self.confidence, 2),
            "processing_time_ms": round(self.processing_time_ms, 2),
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }
