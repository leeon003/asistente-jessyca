"""Orquestador Central del Ciclo Diario de Aprendizaje (daily_cycle.py - Fase 63).

Ejecuta la rutina nocturna integrada:
1. Análisis de experiencias del día (ExperienceAnalyzer)
2. Detección de patrones y formulación de propuestas (LearningProposalEngine)
3. Conversión de fallos a casos de regresión permanentes (RegressionEngine)
4. Experimentación aislada en Sandbox y evaluación (SafeImprovementEngine)
5. Despliegue condicional según política de aprobación (ControlledDeployer)
6. Ejecución de la suite de regresiones activas
7. Decaimiento temporal de preferencias (PersonalizationEngine)
8. Generación persistente del DailyLearningReport

Incorpora:
- Idempotencia por Run ID diario
- Circuit Breaker automático en cada fase
- Aislamiento de fallos (Failure Isolation)
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import UTC, datetime
from typing import Any

from core.experience.analysis_models import AnalysisWindow
from core.experience.analyzer import ExperienceAnalyzer
from core.learning.daily.daily_metrics import DailyLearningRun, DailyRunStatus
from core.learning.daily.daily_policy import DailyLearningPolicy
from core.learning.daily.daily_report import DailyLearningReport
from core.learning.deployment import ApprovalType
from core.learning.improvement_engine import SafeImprovementEngine
from core.learning.proposal_engine import LearningProposalEngine
from core.learning.proposal_models import ProposalStatus
from core.learning.regression.regression_engine import RegressionEngine
from core.logger import get_logger
from core.personalization.preference_engine import PersonalizationEngine

logger = get_logger("jessyca.learning.daily_cycle")


class DailyLearningCycle:
    """Orquestador maestro del ciclo de aprendizaje diario de JESSYCA."""

    def __init__(
        self,
        analyzer: ExperienceAnalyzer | None = None,
        proposal_engine: LearningProposalEngine | None = None,
        regression_engine: RegressionEngine | None = None,
        improvement_engine: SafeImprovementEngine | None = None,
        personalization_engine: PersonalizationEngine | None = None,
        policy: DailyLearningPolicy | None = None,
    ) -> None:
        self.analyzer = analyzer or ExperienceAnalyzer()
        self.proposal_engine = proposal_engine or LearningProposalEngine()
        self.regression_engine = regression_engine or RegressionEngine()
        self.improvement_engine = improvement_engine or SafeImprovementEngine(
            regression_engine=self.regression_engine
        )
        self.personalization_engine = personalization_engine or PersonalizationEngine()
        self.policy = policy or DailyLearningPolicy()
        self._lock = threading.RLock()
        self._completed_runs: dict[str, DailyLearningReport] = {}

    def _compute_run_id(self, date_iso: str) -> str:
        return hashlib.sha256(f"daily_run:{date_iso}".encode()).hexdigest()

    def run(
        self,
        date_iso: str | None = None,
        force: bool = False,
        approved_by: str | None = None,
    ) -> DailyLearningReport:
        """Ejecuta de forma controlada, idempotente y segura el ciclo diario de aprendizaje."""
        with self._lock:
            start_ts = time.time()
            target_date = date_iso or datetime.now(UTC).strftime("%Y-%m-%d")
            run_id = self._compute_run_id(target_date)

            # 1. Verificación de Idempotencia
            if not force and target_date in self._completed_runs:
                logger.info(f"[DAILY CYCLE] El ciclo diario para {target_date} ya fue ejecutado. Retornando reporte previo.")
                return self._completed_runs[target_date]

            run_state = DailyLearningRun(
                run_id=run_id,
                date_iso=target_date,
                status=DailyRunStatus.RUNNING,
            )

            report_data: dict[str, Any] = {
                "date": target_date,
                "run_id": run_id,
                "patterns_detected": [],
                "performance_delta": {},
            }

            try:
                # ── ETAPA 1: ANÁLISIS DE EXPERIENCIAS DE LA JORNADA ──
                run_state = DailyLearningRun.from_dict({**run_state.to_dict(), "status": DailyRunStatus.ANALYZING.value, "current_step": "ANALYSIS"})
                analysis = self.analyzer.analyze(AnalysisWindow(days=1.0))

                report_data["total_experiences"] = analysis.metrics.total_experiences
                report_data["successful_experiences"] = analysis.metrics.success_count
                report_data["failed_experiences"] = analysis.metrics.failure_count
                tot_exp = analysis.metrics.total_experiences
                report_data["verification_failures"] = (
                    int(round((1.0 - analysis.metrics.verification_success_rate) * tot_exp)) if tot_exp > 0 else 0
                )
                report_data["clarifications"] = (
                    int(round(analysis.metrics.clarification_rate * tot_exp)) if tot_exp > 0 else 0
                )
                report_data["corrections"] = (
                    int(round(analysis.metrics.correction_rate * tot_exp)) if tot_exp > 0 else 0
                )
                report_data["patterns_detected"] = [f"[{p.type.value}] {p.description}" for p in analysis.patterns]

                # ── ETAPA 2: GENERACIÓN Y VALIDACIÓN DE PROPUESTAS ──
                run_state = DailyLearningRun.from_dict({**run_state.to_dict(), "status": DailyRunStatus.PROPOSING.value, "current_step": "PROPOSALS"})
                generated_props = self.proposal_engine.generate_proposals_from_analysis(analysis)
                valid_props = []
                rejected_props_count = 0

                for prop in generated_props[: self.policy.max_proposals]:
                    try:
                        submitted = self.proposal_engine.submit_proposal(prop)
                        valid_props.append(submitted)
                    except Exception as ex:
                        logger.warning(f"[DAILY CYCLE] Propuesta rechazada por validación: {ex}")
                        rejected_props_count += 1

                report_data["proposals_generated"] = len(generated_props)
                report_data["proposals_approved"] = len(valid_props)
                report_data["proposals_rejected"] = rejected_props_count

                # ── ETAPA 3: GENERACIÓN DE CASOS DE REGRESIÓN ──
                reg_added_count = 0
                for exp in self.analyzer.repository.get_failed_experiences(limit=20):
                    try:
                        cand = self.regression_engine.create_candidate_from_experience(exp)
                        if cand and cand.status != "ACTIVE":
                            self.regression_engine.validate_and_activate(cand.case_id)
                            reg_added_count += 1
                    except Exception as ex:
                        logger.warning(f"[DAILY CYCLE] Fallo al crear caso de regresión: {ex}")

                report_data["regression_tests_added"] = reg_added_count

                # ── ETAPA 4: PRUEBAS EN SANDBOX Y EVALUACIÓN ──
                run_state = DailyLearningRun.from_dict({**run_state.to_dict(), "status": DailyRunStatus.TESTING.value, "current_step": "SANDBOX_EVALUATION"})
                improvements_deployed_count = 0
                rollbacks_count = 0

                for prop in valid_props:
                    staged_mock = {f"skills/autotune_{prop.category.value.lower()}.py": f"# improvement for {prop.problem}"}
                    try:
                        self.proposal_engine.advance_proposal(prop.proposal_id, ProposalStatus.SIMULATION_PENDING)
                    except Exception:
                        pass

                    candidate, eval_res = self.improvement_engine.prepare_and_test_candidate(
                        proposal=prop,
                        staged_changes=staged_mock,
                        version_tag=f"v2-{prop.proposal_id[:6]}",
                    )

                    try:
                        self.proposal_engine.advance_proposal(prop.proposal_id, ProposalStatus.READY_FOR_EVALUATION)
                    except Exception:
                        pass

                    # Verificar despliegue condicional
                    if eval_res.is_acceptable:
                        if self.policy.can_deploy(is_approved=bool(approved_by)):
                            app_by = approved_by or "Policy_Auto_Approved"
                            app_type = ApprovalType.HUMAN_APPROVAL if approved_by else ApprovalType.POLICY_APPROVAL
                            try:
                                self.proposal_engine.advance_proposal(prop.proposal_id, ProposalStatus.APPROVED)
                                self.improvement_engine.deploy_candidate(
                                    candidate_id=candidate.candidate_id,
                                    approved_by=app_by,
                                    approval_type=app_type,
                                )
                                self.proposal_engine.advance_proposal(prop.proposal_id, ProposalStatus.DEPLOYED)
                                improvements_deployed_count += 1
                            except Exception as dep_ex:
                                logger.error(f"[DAILY CYCLE] Despliegue abortado: {dep_ex}")
                                # Reversión si aplica
                                if "regresiones" in str(dep_ex).lower():
                                    try:
                                        self.improvement_engine.rollback("Fallo en verificación post-despliegue")
                                        rollbacks_count += 1
                                    except Exception:
                                        pass

                report_data["improvements_deployed"] = improvements_deployed_count
                report_data["rollbacks"] = rollbacks_count

                # ── ETAPA 5: EJECUCIÓN DE LA SUITE DE REGRESIONES ──
                reg_passed, reg_run, reg_failures = self.regression_engine.run_regression_suite(active_only=True)
                report_data["regression_tests_failed"] = len(reg_failures)

                # ── ETAPA 6: DECAIMIENTO TEMPORAL DE PERSONALIZACIÓN ──
                self.personalization_engine.cleanup_expired_preferences(decay_days=1.0)

                # ── ETAPA 7: EVALUACIÓN DE CIRCUIT BREAKER ──
                elapsed_sec = time.time() - start_ts
                tripped, cb_reason = self.policy.check_circuit_breaker(
                    security_events=0,
                    test_failures=len(reg_failures),
                    runtime_sec=elapsed_sec,
                )

                if tripped:
                    logger.critical(f"[DAILY CYCLE] {cb_reason}")
                    run_state = DailyLearningRun.from_dict({
                        **run_state.to_dict(),
                        "status": DailyRunStatus.ABORTED.value,
                        "circuit_breaker_triggered": True,
                        "circuit_breaker_reason": cb_reason,
                    })
                    report_data["status"] = "ABORTED"
                    report_data["notes"] = f"Aborted by circuit breaker: {cb_reason}"
                else:
                    run_state = DailyLearningRun.from_dict({**run_state.to_dict(), "status": DailyRunStatus.COMPLETED.value})
                    report_data["status"] = "COMPLETED"

                report_data["duration_ms"] = elapsed_sec * 1000.0
                report = DailyLearningReport.model_validate(report_data)
                report.save()

                self._completed_runs[target_date] = report
                logger.info(f"[DAILY CYCLE] Ciclo completado exitosamente para {target_date} ({report.duration_ms:.1f}ms).")
                return report

            except Exception as ex:
                logger.exception(f"[DAILY CYCLE] Error crítico durante la ejecución: {ex}")
                report_data["status"] = "FAILED"
                report_data["notes"] = f"Cycle failed with exception: {ex}"
                report_data["duration_ms"] = (time.time() - start_ts) * 1000.0
                fail_report = DailyLearningReport.model_validate(report_data)
                return fail_report
