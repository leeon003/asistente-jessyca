"""Motor Central de Aprendizaje de Regresiones (regression_engine.py - Fase 61).

Orquesta el ciclo:
Error / Corrección -> Candidato -> Validación -> Test Determinista -> Protección Activa

Proporciona:
1. Generación de candidatos desde experiencias problemáticas o propuestas.
2. Deduplicación por firma criptográfica de fallo.
3. Validación de seguridad y activación formal.
4. Desactivación (DISABLED) y retiro (RETIRED).
5. Ejecución determinista de la suite de regresiones para bloqueo de despliegue.
6. Estadísticas dinámicas de la suite de regresión.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any

from core.experience.models import (
    ExecutionStatus,
    Experience,
    ExperienceCategory,
)
from core.learning.regression.regression_models import (
    RegressionCase,
    RegressionCategory,
    RegressionSeverity,
    RegressionStatus,
    RegressionSuiteStats,
)
from core.learning.regression.regression_store import (
    IRegressionStore,
    SQLiteRegressionStore,
)
from core.learning.regression.regression_validator import RegressionValidator
from core.learning.regression.test_generator import RegressionTestGenerator
from core.logger import get_logger

logger = get_logger("jessyca.learning.regression_engine")

# Conteo base dinámico del sistema (obtenido del benchmark / suite certificada)
DEFAULT_BASELINE_TEST_COUNT = 2093


class RegressionEngine:
    """Motor de gestión, validación y ejecución de casos de prueba de regresión."""

    def __init__(
        self,
        store: IRegressionStore | None = None,
        baseline_tests_count: int = DEFAULT_BASELINE_TEST_COUNT,
    ) -> None:
        self._store = store or SQLiteRegressionStore()
        self.baseline_tests_count = baseline_tests_count
        self._lock = threading.RLock()

    @property
    def store(self) -> IRegressionStore:
        return self._store

    def _compute_failure_signature(
        self,
        category: RegressionCategory,
        input_text: str,
        error_sig: str,
    ) -> str:
        """Calcula el hash canónico SHA-256 para deduplicación estricta de regresiones."""
        raw = f"{category.value}:{input_text.lower().strip()}:{error_sig.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def create_candidate_from_experience(
        self,
        experience: Experience,
        proposal_id: str | None = None,
        severity: RegressionSeverity = RegressionSeverity.MEDIUM,
    ) -> RegressionCase | None:
        """Transforma una experiencia problemática o corregida en un candidato a caso de regresión."""
        with self._lock:
            input_text = experience.input.raw_text if experience.input else "comando desconocido"
            error_type = experience.error.error_type if experience.error else "ExecutionAnomaly"

            # 1. Determinar categoría de regresión
            cat = RegressionCategory.INTENT
            expected: dict[str, Any] = {}

            if experience.category in (ExperienceCategory.LOW_STT_CONFIDENCE, ExperienceCategory.USER_CORRECTION):
                cat = RegressionCategory.STT
                canonical = (
                    experience.correction.corrected_target
                    if (experience.correction and experience.correction.corrected_target)
                    else (experience.target.value if experience.target else "notepad")
                )
                expected = {"canonical_target": canonical, "input_variant": input_text}
            elif experience.category == ExperienceCategory.AMBIGUOUS_INTENT:
                cat = RegressionCategory.INTENT
                intent_name = experience.intent.name if experience.intent else "open_application"
                expected = {"intent": intent_name, "is_ambiguous": False}
            elif experience.category == ExperienceCategory.CLARIFICATION_REQUESTED:
                cat = RegressionCategory.CLARIFICATION
                expected = {"needs_clarification": True, "required_slot": "target"}
            elif experience.execution and experience.execution.status == ExecutionStatus.FAILED:
                cat = RegressionCategory.TOOL
                tool_name = experience.execution.tool_name or "windows.apps"
                expected = {"tool_name": tool_name, "action": experience.execution.action or "execute"}
            else:
                cat = RegressionCategory.INTENT
                expected = {"intent": experience.intent.name if experience.intent else "general_task"}

            # 2. Calcular firma determinista
            sig = self._compute_failure_signature(cat, input_text, error_type)

            # 3. Deduplicación
            existing = self._store.get_by_signature(sig)
            if existing:
                logger.info(f"[REGRESSION ENGINE] Caso existente encontrado para firma {sig[:10]}... (ID: {existing.case_id}).")
                return existing

            # 4. Crear candidato
            test_ref = f"test_regression_{cat.value.lower()}_{sig[:8]}"
            case = RegressionCase(
                source_experience_id=experience.experience_id,
                source_proposal_id=proposal_id,
                category=cat,
                description=f"Regresión detectada para '{input_text}' tras anomalía {error_type}",
                input_text=input_text,
                expected_behavior=expected,
                failure_signature=sig,
                test_reference=test_ref,
                status=RegressionStatus.CANDIDATE,
                severity=severity,
                requires_real_windows=False,
            )

            # Generar código del test
            case_dict = case.to_dict()
            case_dict["test_code_snippet"] = RegressionTestGenerator.generate_test_snippet(case)
            candidate = RegressionCase.from_dict(case_dict)

            self._store.save(candidate)
            logger.info(f"[REGRESSION ENGINE] Creado candidato de regresión {candidate.case_id} ({cat.value}).")
            return candidate

    def validate_and_activate(self, case_id: str) -> RegressionCase:
        """Valida técnica y éticamente un candidato y lo eleva a estado ACTIVE."""
        with self._lock:
            case = self._store.get(case_id)
            if not case:
                raise ValueError(f"No se encontró el caso de regresión con ID '{case_id}'.")

            # Transición CANDIDATE -> VALIDATED
            validated = RegressionValidator.transition_case(case, RegressionStatus.VALIDATED)
            # Transición VALIDATED -> ACTIVE
            active = RegressionValidator.transition_case(validated, RegressionStatus.ACTIVE)

            self._store.save(active)
            logger.info(f"[REGRESSION ENGINE] Caso {case_id} activado con éxito en la suite permanente.")
            return active

    def disable_regression(self, case_id: str, reason: str) -> RegressionCase:
        """Desactiva temporalmente un caso de regresión."""
        with self._lock:
            case = self._store.get(case_id)
            if not case:
                raise ValueError(f"No se encontró el caso con ID '{case_id}'.")

            disabled = RegressionValidator.transition_case(case, RegressionStatus.DISABLED, reason=reason)
            self._store.save(disabled)
            logger.warning(f"[REGRESSION ENGINE] Caso {case_id} desactivado. Motivo: {reason}.")
            return disabled

    def retire_regression(self, case_id: str, reason: str) -> RegressionCase:
        """Retira definitivamente un caso de regresión obsoleto."""
        with self._lock:
            case = self._store.get(case_id)
            if not case:
                raise ValueError(f"No se encontró el caso con ID '{case_id}'.")

            retired = RegressionValidator.transition_case(case, RegressionStatus.RETIRED, reason=reason)
            self._store.save(retired)
            logger.info(f"[REGRESSION ENGINE] Caso {case_id} retirado. Motivo: {reason}.")
            return retired

    def run_regression_suite(self, active_only: bool = True) -> tuple[bool, int, list[str]]:
        """Ejecuta determinísticamente las pruebas de regresión activas.

        Retorna (all_passed, tests_run, failures).
        """
        with self._lock:
            cases = (
                self._store.query(status=RegressionStatus.ACTIVE)
                if active_only
                else self._store.query()
            )

            tests_run = 0
            failures: list[str] = []

            for case in cases:
                tests_run += 1
                passed, details = RegressionTestGenerator.execute_test_case(case)
                if not passed:
                    failures.append(f"[{case.category.value}] {case.test_reference}: {details}")

            all_passed = len(failures) == 0
            logger.info(
                f"[REGRESSION SUITE] Ejecutados {tests_run} tests de regresión. "
                f"Estado: {'PASS' if all_passed else f'FAIL ({len(failures)} fallos)'}."
            )
            return (all_passed, tests_run, failures)

    def get_stats(self) -> RegressionSuiteStats:
        """Calcula las estadísticas dinámicas y agregadas de la suite de regresiones."""
        with self._lock:
            active_cnt = self._store.count(status=RegressionStatus.ACTIVE)
            disabled_cnt = self._store.count(status=RegressionStatus.DISABLED)
            retired_cnt = self._store.count(status=RegressionStatus.RETIRED)
            total_gen = self._store.count()

            return RegressionSuiteStats(
                initial_tests=self.baseline_tests_count,
                generated_tests=total_gen,
                active_regressions=active_cnt,
                disabled_regressions=disabled_cnt,
                retired_regressions=retired_cnt,
                total_tests=self.baseline_tests_count + active_cnt,
            )
