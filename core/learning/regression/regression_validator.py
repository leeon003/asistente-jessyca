"""Validador y Filtro de Seguridad para Casos de Regresión (regression_validator.py - Fase 61).

Implementa:
1. FILTRO DE SEGURIDAD CONTRA TESTS DESTRUCTIVOS: Rechaza pruebas que intenten
   borrar archivos reales, modificar el registro, exfiltrar datos o acceder a credenciales.
2. VALIDACIÓN DE COMPLETITUD TÉCNICA: Exige campos y firmas de fallo válidos.
3. MÁQUINA DE ESTADOS: Regula el ciclo CANDIDATE -> VALIDATED -> ACTIVE -> DISABLED / RETIRED.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.learning.regression.regression_models import RegressionCase, RegressionStatus

# Comandos y patrones destructivos prohibidos en la generación de tests
FORBIDDEN_DESTRUCTIVE_PATTERNS: tuple[str, ...] = (
    "rmdir",
    "del /",
    "del *",
    "format ",
    "reg delete",
    "reg add",
    "rm -rf",
    "drop table",
    "drop database",
    "truncate ",
    "shutdown",
    "taskkill /f /im explorer.exe",
    "credential_storage",
    "secret_vault",
)

ALLOWED_REGRESSION_TRANSITIONS: dict[RegressionStatus, frozenset[RegressionStatus]] = {
    RegressionStatus.CANDIDATE: frozenset({
        RegressionStatus.VALIDATED,
        RegressionStatus.DISABLED,
        RegressionStatus.RETIRED,
    }),
    RegressionStatus.VALIDATED: frozenset({
        RegressionStatus.ACTIVE,
        RegressionStatus.DISABLED,
        RegressionStatus.RETIRED,
    }),
    RegressionStatus.ACTIVE: frozenset({
        RegressionStatus.DISABLED,
        RegressionStatus.RETIRED,
    }),
    RegressionStatus.DISABLED: frozenset({
        RegressionStatus.ACTIVE,
        RegressionStatus.RETIRED,
    }),
    RegressionStatus.RETIRED: frozenset(),
}


class RegressionValidator:
    """Validador de seguridad, no destructividad y transiciones de casos de regresión."""

    @staticmethod
    def validate_case(case: RegressionCase) -> tuple[bool, list[str]]:
        """Valida que el caso sea determinista, seguro y no destructivo."""
        errors: list[str] = []

        # 1. FILTRO DE SEGURIDAD Y NO DESTRUCTIVIDAD
        combined_text = f"{case.input_text} {case.description} {case.expected_behavior}".lower()
        for pattern in FORBIDDEN_DESTRUCTIVE_PATTERNS:
            if pattern in combined_text:
                errors.append(
                    f"CRITICAL SECURITY VIOLATION: El caso de regresión contiene el patrón destructivo '{pattern}'. "
                    "Se prohíbe terminantemente generar pruebas que alteren el sistema."
                )

        # 2. Completitud técnica
        if not case.description or not case.description.strip():
            errors.append("El campo 'description' no puede estar vacío.")

        if not case.input_text or not case.input_text.strip():
            errors.append("El campo 'input_text' no puede estar vacío.")

        if not case.expected_behavior:
            errors.append("El campo 'expected_behavior' debe contener el comportamiento esperado.")

        if not case.failure_signature or not case.failure_signature.strip():
            errors.append("El campo 'failure_signature' es obligatorio para deduplicación.")

        if not case.test_reference or not case.test_reference.strip():
            errors.append("El campo 'test_reference' es obligatorio.")

        return (len(errors) == 0, errors)

    @staticmethod
    def can_transition(current_status: RegressionStatus, target_status: RegressionStatus) -> bool:
        """Determina si una transición de estado es válida."""
        allowed = ALLOWED_REGRESSION_TRANSITIONS.get(current_status, frozenset())
        return target_status in allowed

    @classmethod
    def transition_case(
        cls,
        case: RegressionCase,
        target_status: RegressionStatus,
        reason: str | None = None,
    ) -> RegressionCase:
        """Ejecuta una transición de estado validada de forma inmutable."""
        if not cls.can_transition(case.status, target_status):
            raise ValueError(
                f"Transición inválida de caso de regresión: '{case.status.value}' "
                f"a '{target_status.value}'."
            )

        # Si avanza a VALIDATED o ACTIVE, validar exhaustivamente
        if target_status in (RegressionStatus.VALIDATED, RegressionStatus.ACTIVE):
            is_valid, errors = cls.validate_case(case)
            if not is_valid:
                raise ValueError(f"Fallo de validación del caso de regresión: {'; '.join(errors)}")

        updated_dict = case.to_dict()
        updated_dict["status"] = target_status.value
        updated_dict["updated_at"] = datetime.now(UTC).isoformat()
        if reason:
            updated_dict.setdefault("metadata", {})["status_change_reason"] = reason

        return RegressionCase.from_dict(updated_dict)
