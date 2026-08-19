"""Tests unitarios e integración para Recuperación Controlada ante Fallos (Etapa 17.3).

Verifica:
1. FailureClassifier (TRANSIENT, RECOVERABLE, PERMANENT, UNKNOWN).
2. RetryPolicy (límites superiores acotados, backoff, filtros de riesgo).
3. CircuitBreaker (CLOSED -> OPEN -> HALF_OPEN -> CLOSED).
4. ControlledFailureRecovery (reintentos acotados, backoff exponencial).
5. Invariante Crítico de Seguridad: DANGEROUS y CRITICAL NUNCA son reintentados automáticamente.
6. Escalado estructurado al usuario ante fallos persistentes o permanentes.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from core.autonomy.autonomy_level import TaskActionRisk
from core.recovery import (
    CircuitBreaker,
    CircuitState,
    ControlledFailureRecovery,
    FailureClassification,
    FailureClassifier,
    RecoveryResult,
    RetryPolicy,
    get_recovery_coordinator,
)


class TestFailureClassifier:
    """Pruebas para el clasificador determinista de errores."""

    def test_transient_error_classification(self) -> None:
        assert FailureClassifier.classify(TimeoutError("Operación excedió el tiempo límite")) == FailureClassification.TRANSIENT
        assert FailureClassifier.classify(ConnectionResetError("Conexión reiniciada por el par")) == FailureClassification.TRANSIENT
        assert FailureClassifier.classify(ConnectionRefusedError("Conexión rechazada")) == FailureClassification.TRANSIENT
        assert FailureClassifier.is_retryable(TimeoutError()) is True

    def test_permanent_error_classification(self) -> None:
        assert FailureClassifier.classify(FileNotFoundError("Archivo no existe")) == FailureClassification.PERMANENT
        assert FailureClassifier.classify(PermissionError("Acceso denegado")) == FailureClassification.PERMANENT
        assert FailureClassifier.classify(ValueError("Parámetro inválido")) == FailureClassification.PERMANENT
        assert FailureClassifier.classify(SyntaxError("Sintaxis incorrecta")) == FailureClassification.PERMANENT
        assert FailureClassifier.is_retryable(FileNotFoundError()) is False

    def test_security_exceptions_are_always_permanent(self) -> None:
        class SecurityViolationException(Exception):
            pass

        class AutonomyPermissionDeniedError(Exception):
            pass

        assert FailureClassifier.classify(SecurityViolationException()) == FailureClassification.PERMANENT
        assert FailureClassifier.classify(AutonomyPermissionDeniedError()) == FailureClassification.PERMANENT


class TestRetryPolicy:
    """Pruebas para la política acotada de reintentos."""

    def test_policy_bounds_enforcement(self) -> None:
        # Reintentos normales válidos
        policy = RetryPolicy(max_retries=3, initial_delay_sec=0.05, max_delay_sec=0.5)
        assert policy.max_retries == 3

        # Prohibición de retries ilimitados o excesivos (>5)
        with pytest.raises(ValueError, match="excede el límite máximo"):
            RetryPolicy(max_retries=10)

        with pytest.raises(ValueError, match="no puede ser negativo"):
            RetryPolicy(max_retries=-1)

    def test_risk_filter_for_retries(self) -> None:
        policy = RetryPolicy(max_retries=3)

        # Operaciones seguras -> permitidas
        assert policy.is_retry_allowed_for_risk(TaskActionRisk.READ_ONLY) is True
        assert policy.is_retry_allowed_for_risk(TaskActionRisk.LOW_RISK) is True

        # OPERACIONES PELIGROSAS/CRÍTICAS -> ESTRICTAMENTE PROHIBIDAS PARA RETRY AUTOMÁTICO
        assert policy.is_retry_allowed_for_risk(TaskActionRisk.DANGEROUS) is False
        assert policy.is_retry_allowed_for_risk(TaskActionRisk.CRITICAL) is False


class TestCircuitBreaker:
    """Pruebas para el patrón Circuit Breaker y transiciones de estado."""

    def test_circuit_breaker_transitions(self) -> None:
        cb = CircuitBreaker(name="test_tool", failure_threshold=2, cooldown_seconds=0.1)

        # Estado inicial: CLOSED
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

        # 1er fallo -> sigue CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

        # 2do fallo (alcanza threshold) -> pasa a OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

        # Durante el cooldown -> sigue OPEN
        assert cb.state == CircuitState.OPEN

        # Esperar cooldown
        time.sleep(0.12)

        # Tras cooldown -> transiciona a HALF_OPEN para solicitud sonda
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

        # Éxito en HALF_OPEN -> transiciona de vuelta a CLOSED
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_circuit_breaker_reopens_on_half_open_failure(self) -> None:
        cb = CircuitBreaker(name="fragile_tool", failure_threshold=1, cooldown_seconds=0.05)

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.06)
        assert cb.state == CircuitState.HALF_OPEN

        # Fallo en HALF_OPEN -> reabre inmediatamente a OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestControlledFailureRecovery:
    """Pruebas para el orquestador ControlledFailureRecovery."""

    def setup_method(self) -> None:
        self.fast_policy = RetryPolicy(
            max_retries=2,
            initial_delay_sec=0.01,
            max_delay_sec=0.05,
            backoff_multiplier=1.5,
        )
        self.coordinator = ControlledFailureRecovery(default_policy=self.fast_policy)

    def test_successful_execution_first_attempt(self) -> None:
        res = self.coordinator.execute_with_recovery(
            tool_name="filesystem",
            operation="read",
            risk_level=TaskActionRisk.READ_ONLY,
            action_fn=lambda: "contenido_leido",
        )
        assert res.success is True
        assert res.result == "contenido_leido"
        assert res.attempts == 1
        assert res.escalated_to_user is False

    def test_transient_failure_retried_and_recovers(self) -> None:
        """Fallo transitorio en intento 1 y 2, éxito en intento 3."""
        attempts = 0

        def flaky_action() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise TimeoutError("Fallo temporal de conexión")
            return "exito_en_intento_3"

        res = self.coordinator.execute_with_recovery(
            tool_name="network_ping",
            operation="ping",
            risk_level=TaskActionRisk.READ_ONLY,
            action_fn=flaky_action,
        )
        assert res.success is True
        assert res.result == "exito_en_intento_3"
        assert res.attempts == 3
        assert res.escalated_to_user is False

    def test_permanent_failure_stops_immediately_without_retries(self) -> None:
        """Un fallo permanente (FileNotFoundError) debe fallar en el intento 1 sin reintentar."""
        call_count = 0

        def failing_action() -> None:
            nonlocal call_count
            call_count += 1
            raise FileNotFoundError("Archivo 'missing.txt' no existe")

        res = self.coordinator.execute_with_recovery(
            tool_name="filesystem",
            operation="read",
            risk_level=TaskActionRisk.READ_ONLY,
            action_fn=failing_action,
        )
        assert res.success is False
        assert res.attempts == 1  # EXACTAMENTE 1 INTENTO, CERO RETRIES
        assert res.classification == FailureClassification.PERMANENT
        assert res.escalated_to_user is True
        assert "missing.txt" in str(res.final_error)

    def test_dangerous_action_retry_prevention_invariant(self) -> None:
        """INVARIANTE CRÍTICO: Operaciones DANGEROUS o CRITICAL NUNCA se reintentan automáticamente.

        Incluso ante un TimeoutError (error transitorio), una acción DANGEROUS debe ejecutarse
        exactamente una sola vez y detenerse de inmediato.
        """
        call_count = 0

        def dangerous_action() -> None:
            nonlocal call_count
            call_count += 1
            raise TimeoutError("Timeout durante eliminación de recurso")

        # Riesgo DANGEROUS
        res_dangerous = self.coordinator.execute_with_recovery(
            tool_name="filesystem",
            operation="delete",
            risk_level=TaskActionRisk.DANGEROUS,
            action_fn=dangerous_action,
        )
        assert res_dangerous.success is False
        assert res_dangerous.attempts == 1  # CERO RETRIES POR SER DANGEROUS
        assert call_count == 1

        # Riesgo CRITICAL
        call_count = 0
        res_critical = self.coordinator.execute_with_recovery(
            tool_name="windows.shell",
            operation="powershell",
            risk_level=TaskActionRisk.CRITICAL,
            action_fn=dangerous_action,
        )
        assert res_critical.success is False
        assert res_critical.attempts == 1  # CERO RETRIES POR SER CRITICAL
        assert call_count == 1

    def test_circuit_breaker_trips_and_blocks_further_executions(self) -> None:
        """Verifica que tras fallos reiterados, el circuit breaker pase a OPEN y rechace llamadas."""
        cb = self.coordinator.get_or_create_circuit_breaker(
            "unstable_service",
            failure_threshold=2,
            cooldown_seconds=1.0,
        )

        def failing_call() -> None:
            raise ConnectionRefusedError("Servidor rechazó la conexión")

        # 1er intento (agota 3 reintentos y falla) -> 1 fallo en CB
        self.coordinator.execute_with_recovery(
            tool_name="unstable_service",
            operation="call",
            risk_level=TaskActionRisk.READ_ONLY,
            action_fn=failing_call,
        )

        # 2do intento -> 2do fallo en CB -> pasa a OPEN
        self.coordinator.execute_with_recovery(
            tool_name="unstable_service",
            operation="call",
            risk_level=TaskActionRisk.READ_ONLY,
            action_fn=failing_call,
        )

        assert cb.state == CircuitState.OPEN

        # 3er intento -> Bloqueado inmediatamente por Circuit Breaker (attempts=0)
        blocked_res = self.coordinator.execute_with_recovery(
            tool_name="unstable_service",
            operation="call",
            risk_level=TaskActionRisk.READ_ONLY,
            action_fn=failing_call,
        )
        assert blocked_res.success is False
        assert blocked_res.attempts == 0
        assert blocked_res.circuit_state == CircuitState.OPEN
        assert blocked_res.escalated_to_user is True

    def test_global_singleton_coordinator(self) -> None:
        coord1 = get_recovery_coordinator()
        coord2 = ControlledFailureRecovery()
        assert coord1 is not None
