"""Coordinador de Recuperación Controlada ante Fallos (Etapa 17.3).

Orquesta:
  - Bounded Retries con Backoff Exponencial.
  - Aislamiento mediante Circuit Breaker por herramienta/subsistema.
  - Regla Inmutable de Seguridad: CERO RETRIES para operaciones DANGEROUS o CRITICAL.
  - Escalado estructurado al usuario tras agotamiento de reintentos o fallo permanente.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

from core.autonomy.autonomy_level import TaskActionRisk
from core.logger import get_logger
from core.recovery.circuit_breaker import CircuitBreaker
from core.recovery.classifier import FailureClassifier
from core.recovery.models import (
    CircuitState,
    EscalationPayload,
    FailureClassification,
    RecoveryResult,
    RetryPolicy,
)

logger = get_logger("jessyca.recovery.coordinator")

T = TypeVar("T")


class ControlledFailureRecovery:
    """Orquestador de resiliencia y recuperación controlada ante fallos."""

    def __init__(self, default_policy: RetryPolicy | None = None) -> None:
        self.default_policy = default_policy or RetryPolicy()
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()

    def get_or_create_circuit_breaker(
        self,
        tool_name: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 5.0,
    ) -> CircuitBreaker:
        """Obtiene o instancia un Circuit Breaker dedicado para la herramienta especificada."""
        key = tool_name.strip().lower()
        with self._lock:
            if key not in self._circuit_breakers:
                self._circuit_breakers[key] = CircuitBreaker(
                    name=key,
                    failure_threshold=failure_threshold,
                    cooldown_seconds=cooldown_seconds,
                )
            return self._circuit_breakers[key]

    def execute_with_recovery(
        self,
        tool_name: str,
        operation: str,
        risk_level: TaskActionRisk,
        action_fn: Callable[[], T],
        policy: RetryPolicy | None = None,
    ) -> RecoveryResult:
        """Ejecuta una acción aplicando las políticas de recuperación controlada.

        GARANTÍAS DE SEGURIDAD (Etapa 17.3):
        1. Si el Circuit Breaker está OPEN -> Rechazo inmediato sin ejecutar action_fn.
        2. Si risk_level es DANGEROUS o CRITICAL -> max_retries = 0 (CERO reintentos automáticos).
        3. Si el fallo es PERMANENT -> CERO reintentos (falla inmediatamente).
        4. Si el fallo es TRANSIENT y risk_level es seguro -> reintento acotado con backoff exponencial.
        5. Tras agotar reintentos o fallo permanente -> Escalado estructurado al usuario.
        """
        active_policy = policy or self.default_policy
        circuit_breaker = self.get_or_create_circuit_breaker(tool_name)
        start_time = time.perf_counter()

        # 1. Comprobación del Circuit Breaker
        if not circuit_breaker.allow_request():
            duration_ms = (time.perf_counter() - start_time) * 1000
            escalation = EscalationPayload(
                tool_name=tool_name,
                operation=operation,
                failure_reason=f"Circuit Breaker '{tool_name}' está OPEN por fallos repetidos previos.",
                classification=FailureClassification.TRANSIENT,
                attempts_made=0,
                circuit_state=CircuitState.OPEN,
                suggested_user_action="Esperar periodo de enfriamiento o verificar manualmente el subsistema.",
            )
            return RecoveryResult(
                success=False,
                result=None,
                attempts=0,
                final_error=f"CircuitBreaker OPEN para '{tool_name}'",
                classification=FailureClassification.TRANSIENT,
                escalated_to_user=True,
                escalation_payload=escalation,
                circuit_state=CircuitState.OPEN,
                duration_ms=duration_ms,
            )

        # 2. Determinar reintentos permitidos según riesgo de la operación
        # REGLA INMUTABLE: DANGEROUS y CRITICAL NUNCA se reintentan automáticamente
        if not active_policy.is_retry_allowed_for_risk(risk_level):
            effective_max_retries = 0
            logger.debug(
                f"[RECOVERY] Operación '{tool_name}.{operation}' clasificada como {risk_level.value}. "
                "Reintentos automáticos desactivados por seguridad (max_retries=0)."
            )
        else:
            effective_max_retries = active_policy.max_retries

        max_attempts = effective_max_retries + 1
        last_error: BaseException | None = None
        last_classification = FailureClassification.UNKNOWN

        # 3. Bucle de ejecución y reintentos acotados
        for attempt in range(1, max_attempts + 1):
            try:
                result = action_fn()
                # Éxito
                circuit_breaker.record_success()
                duration_ms = (time.perf_counter() - start_time) * 1000
                return RecoveryResult(
                    success=True,
                    result=result,
                    attempts=attempt,
                    final_error=None,
                    classification=FailureClassification.TRANSIENT,
                    escalated_to_user=False,
                    circuit_state=circuit_breaker.state,
                    duration_ms=duration_ms,
                )
            except BaseException as exc:
                last_error = exc
                last_classification = FailureClassifier.classify(exc)

                logger.warning(
                    f"[RECOVERY ATTEMPT {attempt}/{max_attempts}] Fallo en '{tool_name}.{operation}': "
                    f"[{last_classification.value}] {type(exc).__name__}: {exc}"
                )

                # Si es un fallo permanente (ej: FileNotFoundError, PermissionDenied, etc.) -> NO reintentar
                if last_classification == FailureClassification.PERMANENT:
                    logger.info(
                        f"[RECOVERY] Error permanente detectado en '{tool_name}.{operation}'. "
                        "Deteniendo reintentos inmediatamente."
                    )
                    break

                # Si quedan reintentos disponibles y es transitorio
                if attempt < max_attempts and last_classification in (
                    FailureClassification.TRANSIENT,
                    FailureClassification.RECOVERABLE,
                ):
                    delay = min(
                        active_policy.max_delay_sec,
                        active_policy.initial_delay_sec * (active_policy.backoff_multiplier ** (attempt - 1)),
                    )
                    logger.debug(f"[RECOVERY] Esperando {delay:.2f}s antes de reintentar (Backoff exponencial)...")
                    time.sleep(delay)

        # 4. Registro de fallo final en el Circuit Breaker y Escalado al Usuario
        circuit_breaker.record_failure()
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Construir payload de escalado al usuario
        escalation_payload = EscalationPayload(
            tool_name=tool_name,
            operation=operation,
            failure_reason=str(last_error) if last_error else "Error desconocido",
            classification=last_classification,
            attempts_made=attempt,
            circuit_state=circuit_breaker.state,
            suggested_user_action=self._get_user_suggestion(last_classification, tool_name),
        )

        return RecoveryResult(
            success=False,
            result=None,
            attempts=attempt,
            final_error=str(last_error) if last_error else "Error desconocido",
            classification=last_classification,
            escalated_to_user=True,
            escalation_payload=escalation_payload,
            circuit_state=circuit_breaker.state,
            duration_ms=duration_ms,
        )

    def _get_user_suggestion(self, classification: FailureClassification, tool_name: str) -> str:
        """Genera una recomendación estructurada para el usuario según la clasificación del error."""
        if classification == FailureClassification.PERMANENT:
            return "Revisar los parámetros, la existencia de los recursos o los permisos requeridos."
        elif classification == FailureClassification.TRANSIENT:
            return f"El subsistema '{tool_name}' no respondió a tiempo. Verificar conectividad o reintentar más tarde."
        elif classification == FailureClassification.RECOVERABLE:
            return "El estado del servicio requiere reinicialización manual de la sesión."
        return "Consulte los logs estructurados para más detalles del fallo."


# Singleton global
_global_recovery_coordinator: ControlledFailureRecovery | None = None
_recovery_lock = threading.Lock()


def get_recovery_coordinator() -> ControlledFailureRecovery:
    """Retorna la instancia singleton global del ControlledFailureRecovery."""
    global _global_recovery_coordinator
    if _global_recovery_coordinator is None:
        with _recovery_lock:
            if _global_recovery_coordinator is None:
                _global_recovery_coordinator = ControlledFailureRecovery()
    return _global_recovery_coordinator
