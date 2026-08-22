"""Motor de Despliegue Controlado de Automejora (deployment.py - Fase 60).

Aplica candidatos aprobados sobre el sistema bajo control formal:
1. Exige que el candidato haya aprobado todas las pruebas unitarias/integración.
2. Exige que la evaluación haya confirmado cero regresiones críticas.
3. Exige una aprobación explícita (HUMAN_APPROVAL o POLICY_APPROVAL).
4. Registra el nuevo VersionSnapshot en el VersionManager y actualiza la versión activa.
5. Prohíbe terminantemente el auto-despliegue incondicional.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.learning.evaluator import EvaluationResult
from core.learning.sandbox import is_in_immutable_security_zone
from core.learning.version_manager import (
    CandidateStatus,
    ImprovementCandidate,
    VersionManager,
    VersionSnapshot,
)
from core.logger import get_logger

logger = get_logger("jessyca.learning.deployment")


class ApprovalType(StrEnum):
    """Tipos de aprobación formal requeridos para despliegue."""

    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    POLICY_APPROVAL = "POLICY_APPROVAL"


class DeploymentResult(BaseModel):
    """Resultado auditable del despliegue de una nueva versión del sistema."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    deployed_version_id: str
    previous_version_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_by: str
    approval_type: ApprovalType
    status: str = "DEPLOYED"
    files_applied: list[str] = Field(default_factory=list)
    checksum: str = ""
    notes: str = ""


class ControlledDeployer:
    """Gestor de despliegue seguro y controlado de automejora."""

    def __init__(
        self,
        version_manager: VersionManager,
        regression_engine: Any | None = None,
    ) -> None:
        self.version_manager = version_manager
        self.regression_engine = regression_engine

    def deploy_candidate(
        self,
        candidate: ImprovementCandidate,
        evaluation: EvaluationResult,
        approved_by: str,
        approval_type: ApprovalType,
    ) -> DeploymentResult:
        """Despliega un candidato validado como nueva versión activa del sistema."""
        # 1. Verificación de Seguridad Inmutable
        for f in candidate.affected_files:
            if is_in_immutable_security_zone(f):
                raise ValueError(
                    f"CRITICAL SECURITY VIOLATION: Intento de desplegar modificaciones "
                    f"sobre la Zona Inmutable de Seguridad ('{f}'). Despliegue abortado."
                )

        # 2. Verificación de pruebas pasadas
        if not candidate.tests_passed:
            raise ValueError(
                f"Despliegue rechazado: el candidato '{candidate.version_tag}' "
                "no ha aprobado las pruebas requeridas."
            )

        # 3. Verificación de evaluación aceptable
        if not evaluation.is_acceptable:
            raise ValueError(
                f"Despliegue rechazado: la evaluación detectó regresiones críticas: {evaluation.details}"
            )

        # 4. Verificación de aprobación explícita
        if not approved_by or not approved_by.strip():
            raise ValueError("Despliegue rechazado: se requiere un aprobador explícito (aprobación incondicional prohibida).")

        # 5. Verificación obligatoria de la suite de regresiones activas (Fase 61)
        if self.regression_engine:
            all_passed, tests_run, failures = self.regression_engine.run_regression_suite(active_only=True)
            if not all_passed:
                raise ValueError(
                    f"DEPLOYMENT BLOCKED: Falla en suite de regresiones activas ({len(failures)} fallos): {'; '.join(failures)}"
                )

        # 6. Generar identificador de versión de producción (ej. v2-candidate -> v2.0.0)
        current_active = self.version_manager.active_version
        target_version_id = candidate.version_tag.replace("-candidate", "")
        if not target_version_id.startswith("v"):
            target_version_id = f"v{target_version_id}"

        # 6. Crear y registrar nuevo VersionSnapshot
        new_snapshot = VersionSnapshot.create_snapshot(
            version_id=target_version_id,
            parent_version=current_active.version_id,
            source_proposal_id=candidate.source_proposal_id,
            files_changed=candidate.affected_files,
            metrics=candidate.candidate_metrics,
            status="ACTIVE",
        )

        self.version_manager.register_snapshot(new_snapshot)
        self.version_manager.set_active_version(target_version_id)

        # Actualizar estado del candidato
        updated_cand_dict = candidate.to_dict()
        updated_cand_dict["status"] = CandidateStatus.DEPLOYED.value
        self.version_manager.update_candidate(ImprovementCandidate.model_validate(updated_cand_dict))

        logger.info(
            f"[CONTROLLED DEPLOYMENT] Versión '{target_version_id}' desplegada exitosamente "
            f"por '{approved_by}' ({approval_type.value}). Checksum: {new_snapshot.checksum[:12]}..."
        )

        return DeploymentResult(
            deployed_version_id=target_version_id,
            previous_version_id=current_active.version_id,
            approved_by=approved_by,
            approval_type=approval_type,
            status="DEPLOYED",
            files_applied=candidate.affected_files,
            checksum=new_snapshot.checksum,
            notes=f"Despliegue exitoso desde propuesta {candidate.source_proposal_id}.",
        )
