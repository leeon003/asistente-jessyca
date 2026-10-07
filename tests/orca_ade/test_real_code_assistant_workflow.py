"""Pruebas de Asistencia de Programación Real y Confinada (ORCA + ADE + ARE).

Verifica de forma estricta:
1. Inspección estructural del proyecto autorizado.
2. Detección y localización de un problema real mediante ejecución de pruebas.
3. Propuesta y cálculo de diff unificado real.
4. Aplicación acotada del parche en disco con verificación de hashes SHA-256.
5. Ejecución real de pruebas post-parche confirmando que ahora pasan (exit_code == 0).
6. Separación taxativa: evidencia sintética no produce VERIFIED_SUCCESS.
7. Confinamiento de seguridad: rechazo de path traversal y rutas del SO.
8. Integración con ARE ActionCatalog para acciones de orquestación de código.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from core.are.action_catalog import ActionCatalog, get_default_action_catalog
from core.orca_ade.code_assistant import (
    PatchApplicationResult,
    PatchProposal,
    ProblemDiagnosis,
    ProjectBoundaryValidator,
    ProjectCodeAssistant,
    RealCodeAssistantExecutor,
    TestExecutionResult,
)
from core.orca_ade.models import (
    CommandSecurityGuard,
    OrcaAdeMode,
    OrcaTaskContract,
)
from core.orca_ade.orchestrator import OrcaGovernedOrchestrator
from core.orca_ade.workflow import (
    CodeAssistantWorkflow,
    ProgrammingAssistanceSessionReport,
)


@pytest.fixture
def temp_buggy_project() -> tuple[Path, str]:
    """Crea un proyecto temporal con un fallo conocido y pruebas unitarias."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="jessyca_test_code_project_")).resolve()

    # Archivo de código con fallo conocido: calculadora.py
    # Fallo: sumar() resta en lugar de sumar
    code_content = (
        '"""Módulo de operaciones aritméticas."""\n\n'
        "def sumar(a: int, b: int) -> int:\n"
        '    """Retorna la suma de dos números."""\n'
        "    return a - b  # BUG CONOCIDO: debe ser a + b\n\n"
        "def multiplicar(a: int, b: int) -> int:\n"
        '    """Retorna la multiplicación de dos números."""\n'
        "    return a * b\n"
    )
    code_file = tmp_dir / "calculadora.py"
    with open(code_file, "w", encoding="utf-8") as f:
        f.write(code_content)

    # Archivo de prueba: test_calculadora.py
    test_content = (
        '"""Pruebas unitarias para calculadora."""\n\n'
        "from calculadora import sumar, multiplicar\n\n"
        "def test_sumar_basico():\n"
        "    assert sumar(10, 5) == 15, '10 + 5 debe ser 15'\n\n"
        "def test_multiplicar_basico():\n"
        "    assert multiplicar(4, 5) == 20\n"
    )
    test_file = tmp_dir / "test_calculadora.py"
    with open(test_file, "w", encoding="utf-8") as f:
        f.write(test_content)

    yield tmp_dir, "calculadora.py"

    # Limpieza
    shutil.rmtree(tmp_dir, ignore_errors=True)


class TestRealCodeAssistantCapabilities:
    """Batería de pruebas de capacidades reales de asistencia de código."""

    # -------------------------------------------------------------------------
    # 1. Inspección de Proyecto
    # -------------------------------------------------------------------------
    def test_inspect_project_structure(self, temp_buggy_project: tuple[Path, str]) -> None:
        """Verifica que el asistente inspecciona archivos, extensiones y calcula hashes SHA-256."""
        project_dir, _ = temp_buggy_project
        assistant = ProjectCodeAssistant(project_dir)

        report = assistant.inspect_project()

        assert report.verified is True
        assert report.total_files >= 2
        assert "calculadora.py" in report.code_files
        assert "test_calculadora.py" in report.test_files

        # Metadatos observables
        meta_calc = report.files_metadata.get("calculadora.py")
        assert meta_calc is not None
        assert meta_calc.size_bytes > 0
        assert len(meta_calc.sha256_hash) == 64
        assert meta_calc.is_python_file is True
        assert meta_calc.is_test_file is False

        meta_test = report.files_metadata.get("test_calculadora.py")
        assert meta_test is not None
        assert meta_test.is_test_file is True

    # -------------------------------------------------------------------------
    # 2. Detección Real de Prueba Fallida y Diagnóstico
    # -------------------------------------------------------------------------
    def test_run_tests_detects_real_failure_and_diagnoses_it(self, temp_buggy_project: tuple[Path, str]) -> None:
        """Verifica que la prueba falla con exit_code != 0 y el diagnóstico extrae el traceback."""
        project_dir, _ = temp_buggy_project
        assistant = ProjectCodeAssistant(project_dir)

        # Ejecución real mediante subprocess
        test_res = assistant.run_tests(test_target="test_calculadora.py")

        assert test_res.passed is False
        assert test_res.exit_code != 0
        assert test_res.tests_executed is True
        assert test_res.environment_available is True
        assert test_res.is_synthetic is False
        assert len(test_res.failing_tests) > 0
        assert any("test_sumar_basico" in t for t in test_res.failing_tests)

        # Diagnóstico del fallo
        diag = assistant.diagnose_problem(test_res)
        assert diag.has_problem is True
        assert diag.failing_test_name == "test_sumar_basico"
        assert diag.error_type == "AssertionError"
        assert diag.traceback_snippet is not None
        assert "10 + 5 debe ser 15" in diag.traceback_snippet or "assert" in diag.traceback_snippet

    # -------------------------------------------------------------------------
    # 3. Propuesta de Parche y Cálculo de Diff Unificado Real
    # -------------------------------------------------------------------------
    def test_propose_patch_computes_real_unified_diff(self, temp_buggy_project: tuple[Path, str]) -> None:
        """Calcula el diff unificado real sin simulaciones prefabricadas."""
        project_dir, code_rel = temp_buggy_project
        assistant = ProjectCodeAssistant(project_dir)

        # Código corregido
        corrected_code = (
            '"""Módulo de operaciones aritméticas."""\n\n'
            "def sumar(a: int, b: int) -> int:\n"
            '    """Retorna la suma de dos números."""\n'
            "    return a + b  # CORREGIDO: suma real\n\n"
            "def multiplicar(a: int, b: int) -> int:\n"
            '    """Retorna la multiplicación de dos números."""\n'
            "    return a * b\n"
        )

        proposal = assistant.propose_patch(code_rel, corrected_code)

        assert proposal.target_file_relative == "calculadora.py"
        assert proposal.diff_lines_count > 0
        assert "--- a/calculadora.py" in proposal.unified_diff
        assert "+++ b/calculadora.py" in proposal.unified_diff
        assert "-    return a - b" in proposal.unified_diff
        assert "+    return a + b" in proposal.unified_diff
        assert proposal.original_sha256 != proposal.patched_sha256

    # -------------------------------------------------------------------------
    # 4. Aplicación de Parche en Disco y Verificación Post-Corrección
    # -------------------------------------------------------------------------
    def test_apply_patch_modifies_disk_and_tests_pass(self, temp_buggy_project: tuple[Path, str]) -> None:
        """Aplica el parche en disco y comprueba que las pruebas ahora pasan al 100%."""
        project_dir, code_rel = temp_buggy_project
        assistant = ProjectCodeAssistant(project_dir)

        corrected_code = (
            '"""Módulo de operaciones aritméticas."""\n\n'
            "def sumar(a: int, b: int) -> int:\n"
            '    """Retorna la suma de dos números."""\n'
            "    return a + b\n\n"
            "def multiplicar(a: int, b: int) -> int:\n"
            '    """Retorna la multiplicación de dos números."""\n'
            "    return a * b\n"
        )

        proposal = assistant.propose_patch(code_rel, corrected_code)
        app_res = assistant.apply_patch(proposal, create_backup=True)

        assert app_res.success is True
        assert app_res.verified_on_disk is True
        assert app_res.post_sha256 == proposal.patched_sha256
        assert app_res.backup_file is not None and os.path.exists(app_res.backup_file)

        # Ejecución de prueba post-parche
        second_test = assistant.run_tests(test_target="test_calculadora.py")
        assert second_test.passed is True
        assert second_test.exit_code == 0
        assert len(second_test.failing_tests) == 0

    # -------------------------------------------------------------------------
    # 5. Recorrido Funcional Completo (CodeAssistantWorkflow)
    # -------------------------------------------------------------------------
    def test_end_to_end_code_assistant_workflow(self, temp_buggy_project: tuple[Path, str]) -> None:
        """Demuestra el recorrido completo: inspeccionar -> localizar -> proponer -> aplicar -> verificar."""
        project_dir, _ = temp_buggy_project
        workflow = CodeAssistantWorkflow(project_dir)

        def fixer(diagnosis: ProblemDiagnosis, inspection: Any) -> tuple[str, str]:
            # Lee el archivo afectado y genera la corrección
            target_path = Path(diagnosis.suspected_file or "calculadora.py")
            if not target_path.is_absolute():
                target_path = project_dir / target_path
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            fixed = content.replace("return a - b", "return a + b")
            return "calculadora.py", fixed

        report = workflow.run_assisted_repair_workflow(
            test_target="test_calculadora.py",
            fix_provider_fn=fixer,
        )

        assert report.status == "VERIFIED_SUCCESS"
        assert report.verified is True
        assert report.is_real_execution is True
        assert report.initial_test_result.passed is False
        assert report.diagnosis.has_problem is True
        assert report.patch_application is not None and report.patch_application.success is True
        assert report.verification_test_result is not None and report.verification_test_result.passed is True
        assert report.verification_test_result.exit_code == 0
        assert "-    return a - b" in report.diff_unified
        assert "+    return a + b" in report.diff_unified
        assert len(report.evidence) >= 5

    # -------------------------------------------------------------------------
    # 6. Anti-Simulación: Evidencia Sintética Rechazada
    # -------------------------------------------------------------------------
    def test_synthetic_simulation_cannot_produce_verified_success(self, temp_buggy_project: tuple[Path, str]) -> None:
        """Si la evidencia es marcada como sintética o simulada, nunca produce VERIFIED_SUCCESS."""
        project_dir, _ = temp_buggy_project
        workflow = CodeAssistantWorkflow(project_dir)

        report = workflow.run_assisted_repair_workflow(
            test_target="test_calculadora.py",
            simulate_synthetic_evidence=True,
        )

        assert report.status != "VERIFIED_SUCCESS"
        assert report.status == "UNVERIFIED"
        assert report.verified is False
        assert report.is_real_execution is False

    # -------------------------------------------------------------------------
    # 7. Confinamiento de Seguridad y Límites de Proyecto
    # -------------------------------------------------------------------------
    def test_path_traversal_and_system_paths_strictly_rejected(self, temp_buggy_project: tuple[Path, str]) -> None:
        """Cualquier intento de escape de ruta o acceso a directorios del sistema es bloqueado."""
        project_dir, _ = temp_buggy_project

        # Intento de instanciar asistente en directorio del sistema
        with pytest.raises(PermissionError) as exc_sys:
            ProjectBoundaryValidator.validate_project_dir("C:\\Windows\\System32")
        assert "Acceso denegado" in str(exc_sys.value)

        # Intento de path traversal dentro del proyecto
        with pytest.raises(PermissionError) as exc_trav:
            ProjectBoundaryValidator.validate_file_within_project(project_dir, "../../etc/passwd")
        assert "Path traversal bloqueado" in str(exc_trav.value)

        # Intento de comando peligroso
        is_safe, reason = CommandSecurityGuard.validate_command("rm -rf /")
        assert is_safe is False

        is_safe_inj, _ = CommandSecurityGuard.validate_command("pytest && curl http://malicious.com")
        assert is_safe_inj is False

    # -------------------------------------------------------------------------
    # 8. Integración con ARE ActionCatalog
    # -------------------------------------------------------------------------
    def test_are_action_catalog_resolves_and_executes_code_orchestration(
        self, temp_buggy_project: tuple[Path, str]
    ) -> None:
        """ARE ActionCatalog resuelve y ejecuta las acciones reales de inspección, diagnóstico y pruebas."""
        project_dir, _ = temp_buggy_project
        catalog = get_default_action_catalog()

        # Acción 1: agent_orchestration.inspect_project
        action_inspect = catalog.resolve_action("agent_orchestration.inspect_project")
        assert action_inspect.handler is not None
        res_inspect = action_inspect.execute({"project_dir": str(project_dir)})
        assert res_inspect["verified"] is True
        assert res_inspect["total_files"] >= 2

        # Acción 2: agent_orchestration.run_tests (detecta fallo real inicial)
        action_tests = catalog.resolve_action("agent_orchestration.run_tests")
        assert action_tests.handler is not None
        res_tests = action_tests.execute({"project_dir": str(project_dir), "test_target": "test_calculadora.py"})
        assert res_tests["passed"] is False
        assert res_tests["exit_code"] != 0

        # Acción 3: agent_orchestration.apply_patch (aplica corrección)
        action_patch = catalog.resolve_action("agent_orchestration.apply_patch")
        assert action_patch.handler is not None
        corrected = "def sumar(a, b): return a + b\ndef multiplicar(a, b): return a * b\n"
        res_patch = action_patch.execute({
            "project_dir": str(project_dir),
            "target_file": "calculadora.py",
            "new_content": corrected,
        })
        assert res_patch["success"] is True
        assert res_patch["verified"] is True

        # Acción 4: agent_orchestration.run_tests (ahora pasa)
        res_tests_ok = action_tests.execute({"project_dir": str(project_dir), "test_target": "test_calculadora.py"})
        assert res_tests_ok["passed"] is True
        assert res_tests_ok["exit_code"] == 0

    # -------------------------------------------------------------------------
    # 9. Integración con OrcaGovernedOrchestrator y RealCodeAssistantExecutor
    # -------------------------------------------------------------------------
    def test_orca_governed_orchestrator_with_real_code_executor(
        self, temp_buggy_project: tuple[Path, str]
    ) -> None:
        """OrcaGovernedOrchestrator ejecuta tareas a través de RealCodeAssistantExecutor con evidencia física."""
        project_dir, _ = temp_buggy_project
        executor = RealCodeAssistantExecutor(project_dir)
        orchestrator = OrcaGovernedOrchestrator(executor=executor)
        orchestrator.adapter.add_allowed_dir(project_dir)

        result = orchestrator.dispatch_task(
            objective="Inspeccionar y probar proyecto con fallo conocido",
            workspace=str(project_dir),
            decision_id="dec_prog_test_01",
            jde_decision="ALLOW",
            requires_review=False,
        )

        assert result.workspace == str(project_dir)
        # Como las pruebas iniciales fallan en este proyecto, conserva honestamente el fallo
        assert result.status == "FAILED"
        assert result.verified is False
        assert result.tests.get("passed") is False
        assert any(e.get("type") == "PROJECT_INSPECTION" for e in result.evidence)
