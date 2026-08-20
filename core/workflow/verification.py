"""Motor de Verificación Post-Acción para Workflows (Etapa 18.3).

Garantiza:
  Action -> Observe -> Compare -> VerificationResult

Reglas de Seguridad:
1. No asumir éxito únicamente porque la herramienta o el ejecutor devolvió código OK.
2. Cada paso puede declarar un ExpectedState formal.
3. El verificador observa el estado del sistema o del entorno, compara y emite un VerificationResult.
4. Si la verificación falla:
   - Aplica la política declarada: STOP (detención inmediata) o RECOVER (compensación/rollback).
5. Detecta estados obsoletos (Stale State), discrepancias (Mismatch), timeouts de observación y cancelaciones.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.workflow.verification")


class VerificationStatus(StrEnum):
    """Estados del resultado de verificación post-acción."""

    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    MISMATCH = "MISMATCH"
    TIMEOUT = "TIMEOUT"
    STALE_STATE = "STALE_STATE"
    CANCELLED = "CANCELLED"
    RECOVERED = "RECOVERED"


class VerificationFailurePolicy(StrEnum):
    """Políticas de actuación ante fallo de verificación."""

    STOP = "STOP"
    RECOVER = "RECOVER"


@dataclass(frozen=True)
class ExpectedState:
    """Definición inmutable del estado esperado post-ejecución."""

    expected_values: dict[str, Any] = field(default_factory=dict)
    predicate: Callable[[dict[str, Any]], bool] | None = None
    max_stale_seconds: float = 10.0
    timeout_sec: float = 3.0
    poll_interval_sec: float = 0.05
    failure_policy: VerificationFailurePolicy = VerificationFailurePolicy.STOP
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_values": self.expected_values,
            "has_predicate": self.predicate is not None,
            "max_stale_seconds": self.max_stale_seconds,
            "timeout_sec": self.timeout_sec,
            "poll_interval_sec": self.poll_interval_sec,
            "failure_policy": self.failure_policy.value,
            "description": self.description,
        }


@dataclass(frozen=True)
class ObservedState:
    """Estado observado tras la ejecución de la acción."""

    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "is_stale": self.is_stale,
        }


@dataclass(frozen=True)
class WorkflowVerificationResult:
    """Resultado determinista del proceso de verificación."""

    status: VerificationStatus
    passed: bool
    expected: ExpectedState | None
    observed: ObservedState | None
    mismatches: tuple[str, ...] = field(default_factory=tuple)
    duration_ms: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "passed": self.passed,
            "expected": self.expected.to_dict() if self.expected else None,
            "observed": self.observed.to_dict() if self.observed else None,
            "mismatches": list(self.mismatches),
            "duration_ms": round(self.duration_ms, 2),
            "reason": self.reason,
        }


class WorkflowStepVerifier:
    """Verificador de pasos de workflow implementando el ciclo Action -> Observe -> Compare."""

    @classmethod
    def verify(
        cls,
        expected: ExpectedState,
        action_output: Any,
        observer_fn: Callable[[], dict[str, Any] | ObservedState] | None = None,
        is_cancelled_fn: Callable[[], bool] | None = None,
        action_start_time: datetime | None = None,
    ) -> WorkflowVerificationResult:
        """Ejecuta el ciclo formal: Observe -> Compare -> Result."""
        start_perf = time.perf_counter()
        deadline = start_perf + max(0.01, expected.timeout_sec)
        ref_start = action_start_time or datetime.now(UTC)

        mismatches: list[str] = []
        last_observed: ObservedState | None = None

        logger.debug(f"[VERIFIER] Iniciando verificación contra ExpectedState (timeout: {expected.timeout_sec}s)")

        while True:
            # 1. Comprobar cancelación
            if is_cancelled_fn and is_cancelled_fn():
                duration_ms = (time.perf_counter() - start_perf) * 1000
                logger.warning("[VERIFIER] Verificación cancelada por señal de interrupción.")
                return WorkflowVerificationResult(
                    status=VerificationStatus.CANCELLED,
                    passed=False,
                    expected=expected,
                    observed=last_observed,
                    mismatches=("Verificación cancelada por el usuario o Emergency Stop",),
                    duration_ms=duration_ms,
                    reason="Verificación cancelada.",
                )

            # 2. FASE OBSERVE
            if observer_fn is not None:
                try:
                    obs_raw = observer_fn()
                    if isinstance(obs_raw, ObservedState):
                        observed_state = obs_raw
                    elif isinstance(obs_raw, dict):
                        observed_state = ObservedState(data=obs_raw, timestamp=datetime.now(UTC))
                    else:
                        observed_state = ObservedState(data={"value": obs_raw}, timestamp=datetime.now(UTC))
                except Exception as exc:
                    observed_state = ObservedState(data={"error": str(exc)}, timestamp=datetime.now(UTC))
            else:
                # Observar directamente a partir del output retornado por la acción
                obs_dict = action_output if isinstance(action_output, dict) else {"output": action_output}
                observed_state = ObservedState(data=obs_dict, timestamp=datetime.now(UTC))

            last_observed = observed_state

            # 3. Comprobar Stale State (Estado obsoleto)
            now_utc = datetime.now(UTC)
            age_seconds = (now_utc - observed_state.timestamp).total_seconds()
            if age_seconds > expected.max_stale_seconds or observed_state.is_stale:
                duration_ms = (time.perf_counter() - start_perf) * 1000
                reason = f"Estado observado es obsoleto (edad: {age_seconds:.2f}s > max_stale: {expected.max_stale_seconds}s)."
                logger.warning(f"[VERIFIER] {reason}")
                return WorkflowVerificationResult(
                    status=VerificationStatus.STALE_STATE,
                    passed=False,
                    expected=expected,
                    observed=observed_state,
                    mismatches=(reason,),
                    duration_ms=duration_ms,
                    reason=reason,
                )

            # 4. FASE COMPARE
            mismatches = []
            # Comparar valores clave
            for k, exp_val in expected.expected_values.items():
                actual_val = observed_state.data.get(k)
                if actual_val != exp_val:
                    mismatches.append(f"Clave '{k}': esperado={exp_val!r}, observado={actual_val!r}")

            # Comparar predicado si existe
            if expected.predicate is not None:
                try:
                    if not expected.predicate(observed_state.data):
                        mismatches.append(f"Predicado personalizado devolvió False (descripción: '{expected.description}')")
                except Exception as exc:
                    mismatches.append(f"Error al evaluar predicado de verificación: {exc}")

            # Si no hay discrepancias, la verificación es EXITOSA
            if not mismatches:
                duration_ms = (time.perf_counter() - start_perf) * 1000
                logger.info(f"[VERIFIER] Verificación EXITOSA ({duration_ms:.2f}ms).")
                return WorkflowVerificationResult(
                    status=VerificationStatus.VERIFIED_SUCCESS,
                    passed=True,
                    expected=expected,
                    observed=observed_state,
                    mismatches=(),
                    duration_ms=duration_ms,
                    reason="Estado observado coincide satisfactoriamente con el estado esperado.",
                )

            # Si hay discrepancias pero aún queda tiempo de sondeo (polling), esperar y re-observar
            if time.perf_counter() < deadline and observer_fn is not None:
                time.sleep(expected.poll_interval_sec)
                continue
            else:
                break

        # Si agotó el tiempo de sondeo con observer_fn
        duration_ms = (time.perf_counter() - start_perf) * 1000
        if time.perf_counter() >= deadline and observer_fn is not None:
            reason = f"Timeout de verificación superado ({expected.timeout_sec}s). Discrepancias: {'; '.join(mismatches)}"
            logger.error(f"[VERIFIER] {reason}")
            return WorkflowVerificationResult(
                status=VerificationStatus.TIMEOUT,
                passed=False,
                expected=expected,
                observed=last_observed,
                mismatches=tuple(mismatches),
                duration_ms=duration_ms,
                reason=reason,
            )

        # Mismatch directo
        reason = f"Discrepancia de estado detectada: {'; '.join(mismatches)}"
        logger.error(f"[VERIFIER] {reason}")
        return WorkflowVerificationResult(
            status=VerificationStatus.MISMATCH,
            passed=False,
            expected=expected,
            observed=last_observed,
            mismatches=tuple(mismatches),
            duration_ms=duration_ms,
            reason=reason,
        )
