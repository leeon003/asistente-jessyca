"""Recorrido Funcional y Orquestador de Asistencia de Programación (ORCA + ADE + ARE).

Implementa el ciclo completo gobernado:
1. Inspeccionar un proyecto dentro de un directorio autorizado.
2. Localizar un problema (ejecución de pruebas reales, diagnóstico de fallos).
3. Proponer y aplicar un cambio acotado con diff unificado real.
4. Ejecutar pruebas autorizadas tras el cambio.
5. Comprobar que la prueba pasa y recopilar evidencias observables (hashes, stdout, exit_code).
6. Separar taxativamente el modo real del modo simulado o evidencia sintética.
7. Manejar degradación elegante cuando falta entorno de ejecución (marcar como UNTESTED_CODE).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.orca_ade.code_assistant import (
    PatchApplicationResult,
    PatchProposal,
    ProblemDiagnosis,
    ProjectBoundaryValidator,
    ProjectCodeAssistant,
    ProjectInspectionReport,
    TestExecutionResult,
)
from core.orca_ade.models import (
    AgentLifecycle,
    AgentState,
    OrcaAdeMode,
    OrcaResultContract,
    OrcaTaskContract,
)

logger = get_logger("jessyca.orca_ade.workflow")


@dataclass
class ProgrammingAssistanceSessionReport:
    """Reporte formal de la sesión de asistencia de programación."""

    project_dir: str
    status: str  # VERIFIED_SUCCESS, CLAIMED_SUCCESS, UNTESTED_CODE, FAILED, DENIED
    verified: bool
    is_real_execution: bool
    inspection: ProjectInspectionReport
    initial_test_result: TestExecutionResult
    diagnosis: ProblemDiagnosis
    patch_proposal: PatchProposal | None
    patch_application: PatchApplicationResult | None
    verification_test_result: TestExecutionResult | None
    diff_unified: str
    evidence: list[dict[str, Any]]
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "status": self.status,
            "verified": self.verified,
            "is_real_execution": self.is_real_execution,
            "total_files": self.inspection.total_files,
            "initial_tests_passed": self.initial_test_result.passed,
            "initial_exit_code": self.initial_test_result.exit_code,
            "has_problem_diagnosed": self.diagnosis.has_problem,
            "failing_test": self.diagnosis.failing_test_name,
            "error_type": self.diagnosis.error_type,
            "patch_applied": bool(self.patch_application and self.patch_application.success),
            "final_tests_passed": bool(self.verification_test_result and self.verification_test_result.passed),
            "final_exit_code": self.verification_test_result.exit_code if self.verification_test_result else None,
            "diff_unified": self.diff_unified,
            "evidence_count": len(self.evidence),
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


class CodeAssistantWorkflow:
    """Orquestador gobernado del recorrido de asistencia de programación."""

    def __init__(self, authorized_project_dir: str | Path) -> None:
        self.project_dir = ProjectBoundaryValidator.validate_project_dir(authorized_project_dir)
        self.assistant = ProjectCodeAssistant(self.project_dir)

    def run_assisted_repair_workflow(
        self,
        test_target: str | None = None,
        fix_provider_fn: Any | None = None,
        simulate_synthetic_evidence: bool = False,
    ) -> ProgrammingAssistanceSessionReport:
        """Ejecuta el recorrido completo de inspección, diagnóstico, corrección y verificación."""
        start_time = time.perf_counter()
        evidence: list[dict[str, Any]] = []

        # Paso 1: Inspeccionar el proyecto
        inspection = self.assistant.inspect_project()
        evidence.append({
            "step": "INSPECT_PROJECT",
            "files_count": inspection.total_files,
            "code_files": inspection.code_files,
            "test_files": inspection.test_files,
            "provenance": "REAL_FILESYSTEM",
            "synthetic": False,
        })

        # Paso 2: Ejecutar pruebas autorizadas iniciales (localizar problema)
        initial_test = self.assistant.run_tests(test_target=test_target)
        evidence.append({
            "step": "INITIAL_TEST_RUN",
            "exit_code": initial_test.exit_code,
            "passed": initial_test.passed,
            "tests_executed": initial_test.tests_executed,
            "failing_tests": initial_test.failing_tests,
            "provenance": "SUBPROCESS_PYTEST",
            "synthetic": False,
        })

        # Paso 3: Diagnosticar el fallo real
        diagnosis = self.assistant.diagnose_problem(initial_test)
        evidence.append({
            "step": "DIAGNOSE_PROBLEM",
            "has_problem": diagnosis.has_problem,
            "error_type": diagnosis.error_type,
            "failing_test": diagnosis.failing_test_name,
            "suspected_file": diagnosis.suspected_file,
            "suspected_line": diagnosis.suspected_line,
            "provenance": "TRACEBACK_ANALYSIS",
            "synthetic": False,
        })

        # Si el entorno de pruebas no estuvo disponible
        if not initial_test.environment_available:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return ProgrammingAssistanceSessionReport(
                project_dir=str(self.project_dir),
                status="UNTESTED_CODE",
                verified=False,
                is_real_execution=False,
                inspection=inspection,
                initial_test_result=initial_test,
                diagnosis=diagnosis,
                patch_proposal=None,
                patch_application=None,
                verification_test_result=None,
                diff_unified="",
                evidence=evidence,
                duration_ms=duration_ms,
                metadata={"reason": "Entorno de ejecución no disponible; código entregado sin probar."},
            )

        # Si no hay problema, el proyecto ya está pasando sus pruebas
        if not diagnosis.has_problem:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return ProgrammingAssistanceSessionReport(
                project_dir=str(self.project_dir),
                status="VERIFIED_SUCCESS",
                verified=True,
                is_real_execution=True,
                inspection=inspection,
                initial_test_result=initial_test,
                diagnosis=diagnosis,
                patch_proposal=None,
                patch_application=None,
                verification_test_result=initial_test,
                diff_unified="No diff required (all tests passed initially)",
                evidence=evidence,
                duration_ms=duration_ms,
                metadata={"message": "El proyecto ya cumple todas las pruebas autorizadas."},
            )

        # Paso 4: Proponer el cambio acotado (parche)
        # Si se suministró un proveedor de corrección (función que genera el código corregido)
        patch_proposal: PatchProposal | None = None
        patch_application: PatchApplicationResult | None = None
        verification_test: TestExecutionResult | None = None

        if fix_provider_fn is not None:
            # Obtener el archivo objetivo y el contenido corregido
            target_rel, corrected_content = fix_provider_fn(diagnosis, inspection)
            patch_proposal = self.assistant.propose_patch(target_rel, corrected_content)

            evidence.append({
                "step": "PROPOSE_PATCH",
                "target_file": target_rel,
                "diff_lines": patch_proposal.diff_lines_count,
                "pre_sha256": patch_proposal.original_sha256,
                "post_sha256": patch_proposal.patched_sha256,
                "provenance": "DIFFLIB_UNIFIED",
                "synthetic": False,
            })

            # Paso 5: Aplicar el cambio acotado
            patch_application = self.assistant.apply_patch(patch_proposal, create_backup=True)
            evidence.append({
                "step": "APPLY_PATCH",
                "success": patch_application.success,
                "target_file": patch_application.target_file,
                "pre_sha256": patch_application.pre_sha256,
                "post_sha256": patch_application.post_sha256,
                "bytes_written": patch_application.bytes_written,
                "provenance": "REAL_DISK_WRITE",
                "synthetic": False,
            })

            # Paso 6: Ejecutar nuevamente las pruebas autorizadas
            verification_test = self.assistant.run_tests(test_target=test_target)
            evidence.append({
                "step": "VERIFICATION_TEST_RUN",
                "exit_code": verification_test.exit_code,
                "passed": verification_test.passed,
                "tests_executed": verification_test.tests_executed,
                "failing_tests": verification_test.failing_tests,
                "provenance": "SUBPROCESS_PYTEST",
                "synthetic": False,
            })

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Paso 7: Evaluación de Estado y Anti-Simulación
        diff_str = patch_proposal.unified_diff if patch_proposal else ""

        # Regla: Simulación / Evidencia sintética
        if simulate_synthetic_evidence:
            evidence.append({
                "type": "SYNTHETIC_OVERRIDE",
                "synthetic": True,
                "provenance": "SYNTHETIC_TEST",
                "note": "Evidencia marcada como sintética: prohíbe VERIFIED_SUCCESS",
            })
            return ProgrammingAssistanceSessionReport(
                project_dir=str(self.project_dir),
                status="UNVERIFIED",
                verified=False,
                is_real_execution=False,
                inspection=inspection,
                initial_test_result=initial_test,
                diagnosis=diagnosis,
                patch_proposal=patch_proposal,
                patch_application=patch_application,
                verification_test_result=verification_test,
                diff_unified=diff_str,
                evidence=evidence,
                duration_ms=duration_ms,
                metadata={"reason": "Evidencia sintética detectada; no certifica efectos físicos."},
            )

        # Regla: Verificación real exitosa
        if (
            patch_application
            and patch_application.success
            and verification_test
            and verification_test.passed
            and verification_test.exit_code == 0
        ):
            status = "VERIFIED_SUCCESS"
            verified = True
        elif verification_test and not verification_test.passed:
            status = "FAILED"
            verified = False
        else:
            status = "CLAIMED_SUCCESS" if patch_application and patch_application.success else "FAILED"
            verified = False

        return ProgrammingAssistanceSessionReport(
            project_dir=str(self.project_dir),
            status=status,
            verified=verified,
            is_real_execution=True,
            inspection=inspection,
            initial_test_result=initial_test,
            diagnosis=diagnosis,
            patch_proposal=patch_proposal,
            patch_application=patch_application,
            verification_test_result=verification_test,
            diff_unified=diff_str,
            evidence=evidence,
            duration_ms=duration_ms,
            metadata={"message": "Recorrido completado bajo gobernanza estricta."},
        )
