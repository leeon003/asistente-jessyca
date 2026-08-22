"""Motor Principal de Automejora Segura y Controlada (improvement_engine.py - Fase 60).

Orquesta el ciclo integral de automejora:
Proposal -> Candidate -> Sandbox -> Tests -> Evaluation -> Approval -> Deployment -> Rollback

Garantiza:
1. ZONA INMUTABLE DE SEGURIDAD inviolable.
2. Experimentación aislada en sandbox antes de cualquier consideración.
3. Evaluación comparativa estricta con cero regresiones críticas.
4. Despliegue con aprobación explícita (HUMAN_APPROVAL / POLICY_APPROVAL).
5. Rollback atómico y auditable ante cualquier anomalía.
"""

from __future__ import annotations

import threading
from typing import Any

from core.learning.deployment import ApprovalType, ControlledDeployer, DeploymentResult
from core.learning.evaluator import EvaluationResult, ImprovementEvaluator
from core.learning.proposal_models import LearningProposal
from core.learning.proposal_validator import ProposalValidator
from core.learning.rollback import RollbackManager, RollbackResult
from core.learning.sandbox import SandboxEnvironment, is_in_immutable_security_zone
from core.learning.version_manager import (
    CandidateStatus,
    ImprovementCandidate,
    VersionManager,
    VersionSnapshot,
)
from core.logger import get_logger

logger = get_logger("jessyca.learning.improvement_engine")


class SafeImprovementEngine:
    """Motor central orquestador de automejora controlada y segura."""

    def __init__(
        self,
        version_manager: VersionManager | None = None,
        evaluator: ImprovementEvaluator | None = None,
        regression_engine: Any | None = None,
    ) -> None:
        self.version_manager = version_manager or VersionManager(initial_version="v1.0.0")
        self.evaluator = evaluator or ImprovementEvaluator()
        self.regression_engine = regression_engine
        self.deployer = ControlledDeployer(
            version_manager=self.version_manager,
            regression_engine=self.regression_engine,
        )
        self.rollback_manager = RollbackManager(version_manager=self.version_manager)
        self._lock = threading.RLock()
        self._evaluation_cache: dict[str, EvaluationResult] = {}

    @property
    def active_version(self) -> VersionSnapshot:
        return self.version_manager.active_version

    def prepare_and_test_candidate(
        self,
        proposal: LearningProposal,
        staged_changes: dict[str, str],
        version_tag: str = "v2-candidate",
        simulated_metrics: dict[str, float] | None = None,
    ) -> tuple[ImprovementCandidate, EvaluationResult]:
        """Prepara un candidato a mejora, ejecuta pruebas en Sandbox y evalúa contra el baseline."""
        with self._lock:
            # 1. VERIFICACIÓN DE SEGURIDAD INMUTABLE
            is_valid, errors = ProposalValidator.validate_proposal(proposal)
            if not is_valid:
                raise ValueError(f"Propuesta rechazada por validación de seguridad: {'; '.join(errors)}")

            affected_files = list(staged_changes.keys())
            for f in affected_files:
                if is_in_immutable_security_zone(f):
                    raise ValueError(
                        f"CRITICAL SECURITY VIOLATION: Archivo '{f}' pertenece a la Zona Inmutable de Seguridad. "
                        "Operación abortada inmediatamente."
                    )

            # 2. Crear candidato en VersionManager
            candidate = self.version_manager.create_candidate(
                source_proposal_id=proposal.proposal_id,
                version_tag=version_tag,
                affected_files=affected_files,
                staged_changes=staged_changes,
            )

            # 3. Preparar entorno Sandbox
            sandbox = SandboxEnvironment(sandbox_id=f"sbx-{candidate.candidate_id[:8]}")
            try:
                for file_path, content in staged_changes.items():
                    sandbox.stage_file(file_path, content)

                # 4. Ejecutar pruebas en Sandbox
                tests_passed, tests_run, regressions = sandbox.run_isolated_tests(proposal.required_tests)

                cand_dict = candidate.to_dict()
                cand_dict["tests_run"] = tests_run
                cand_dict["tests_passed"] = tests_passed

                if not tests_passed:
                    cand_dict["status"] = CandidateStatus.TESTS_FAILED.value
                    cand_dict["rejection_reason"] = f"Fallo en pruebas de sandbox: {'; '.join(regressions)}"
                    updated_cand = ImprovementCandidate.model_validate(cand_dict)
                    self.version_manager.update_candidate(updated_cand)

                    eval_res = EvaluationResult(
                        is_acceptable=False,
                        score=0.0,
                        baseline_metrics=self.active_version.metrics,
                        candidate_metrics=simulated_metrics or {},
                        regressions_count=len(regressions),
                        regressions=regressions,
                        details="Pruebas aisladas en Sandbox fallidas.",
                    )
                    return (updated_cand, eval_res)

                # 5. Pruebas superadas -> Evaluación comparativa
                cand_dict["status"] = CandidateStatus.TESTS_PASSED.value
                metrics = simulated_metrics or {
                    "success_rate": 1.0,
                    "failure_rate": 0.0,
                    "avg_latency_ms": 120.0,
                }
                cand_dict["candidate_metrics"] = metrics
                updated_cand = ImprovementCandidate.model_validate(cand_dict)
                self.version_manager.update_candidate(updated_cand)

                # 6. Evaluación contra el baseline
                eval_res = self.evaluator.evaluate(updated_cand, self.active_version)
                self._evaluation_cache[updated_cand.candidate_id] = eval_res

                # Actualizar estado a EVALUATED
                eval_dict = updated_cand.to_dict()
                eval_dict["status"] = (
                    CandidateStatus.EVALUATED.value if eval_res.is_acceptable else CandidateStatus.DISCARDED.value
                )
                if not eval_res.is_acceptable:
                    eval_dict["rejection_reason"] = f"Rechazado en evaluación: {eval_res.details}"

                final_cand = ImprovementCandidate.model_validate(eval_dict)
                self.version_manager.update_candidate(final_cand)

                return (final_cand, eval_res)

            finally:
                sandbox.clean()

    def deploy_candidate(
        self,
        candidate_id: str,
        approved_by: str,
        approval_type: ApprovalType,
    ) -> DeploymentResult:
        """Despliega un candidato previamente probado y evaluado como nueva versión de producción."""
        with self._lock:
            candidate = self.version_manager.get_candidate(candidate_id)
            if not candidate:
                raise ValueError(f"No se encontró el candidato '{candidate_id}'.")

            eval_res = self._evaluation_cache.get(candidate_id)
            if not eval_res:
                eval_res = self.evaluator.evaluate(candidate, self.active_version)

            result = self.deployer.deploy_candidate(
                candidate=candidate,
                evaluation=eval_res,
                approved_by=approved_by,
                approval_type=approval_type,
            )
            return result

    def rollback(self, reason: str) -> RollbackResult:
        """Ejecuta un rollback inmediato a la versión padre previa."""
        with self._lock:
            return self.rollback_manager.rollback_to_parent(reason=reason)
