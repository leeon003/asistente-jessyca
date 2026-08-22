"""Política de Seguridad y Circuit Breaker del Ciclo Diario (daily_policy.py - Fase 63).

Gobierna:
1. Límites estrictos de ejecución (tiempo máximo, propuestas máximas, fallos tolerados).
2. Mecanismo de Circuit Breaker para interrupción automática del ciclo ante anomalías.
3. Requisito estricto de aprobación previa al despliegue.
4. Auto-despliegue DESACTIVADO por defecto.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.learning.sandbox import SECURITY_IMMUTABLE_ZONE


class DailyLearningPolicy(BaseModel):
    """Política determinista de control, límites y circuit breaker para el ciclo diario."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    max_proposals: int = 10
    max_runtime_sec: float = 300.0
    max_test_failures: int = 3
    require_approval: bool = True
    auto_deploy: bool = False
    circuit_breaker_enabled: bool = True
    prohibited_security_zones: frozenset[str] = Field(default=SECURITY_IMMUTABLE_ZONE)

    def check_circuit_breaker(
        self,
        security_events: int = 0,
        test_failures: int = 0,
        runtime_sec: float = 0.0,
        sandbox_violations: int = 0,
    ) -> tuple[bool, str | None]:
        """Evalúa si deben activarse los interruptores de emergencia (Circuit Breaker).

        Retorna (should_trip, reason).
        """
        if not self.circuit_breaker_enabled:
            return (False, None)

        if security_events > 0:
            return (True, f"Circuit Breaker activado: se detectaron {security_events} eventos de seguridad críticos.")

        if sandbox_violations > 0:
            return (True, f"Circuit Breaker activado: se detectaron {sandbox_violations} intentos de violación de Sandbox.")

        if test_failures > self.max_test_failures:
            return (
                True,
                f"Circuit Breaker activado: fallos de pruebas ({test_failures}) superan el umbral tolerado ({self.max_test_failures}).",
            )

        if runtime_sec > self.max_runtime_sec:
            return (
                True,
                f"Circuit Breaker activado: tiempo de ejecución ({runtime_sec:.1f}s) superó el límite ({self.max_runtime_sec}s).",
            )

        return (False, None)

    def can_deploy(self, is_approved: bool) -> bool:
        """Determina si un candidato califica para despliegue según la política."""
        if not self.auto_deploy and not is_approved:
            return False
        if self.require_approval and not is_approved:
            return False
        return True
