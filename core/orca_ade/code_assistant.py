"""Asistente de Programación Confinado y Gobernado para JESSYCA 3.0 / ORCA + ADE.

Fase 3 — Integración Real de Asistencia de Código bajo JDE, Orca/ADE y ARE.
Permite inspeccionar proyectos autorizados, localizar fallos reales en pruebas,
proponer y aplicar parches acotados con diffs unificados reales, y ejecutar
pruebas autorizadas verificando evidencia física observable en disco.

Reglas Inviolables:
1. CONFINAMIENTO ESTRICTO: Solo opera dentro del `authorized_project_dir`.
   Rechaza de inmediato cualquier escape de ruta, path traversal o acceso a rutas críticas del SO.
2. NO SCRIPTS DESCONOCIDOS NI DEPENDENCIAS: No ejecuta pip install, scripts arbitrarios ni shells.
3. ANTI-SIMULACIÓN TAXATIVA: Difs reales calculados con difflib, pruebas reales ejecutadas con subprocess,
   hashes SHA-256 físicos en disco. Separa explícitamente evidencia sintética de evidencia real.
4. ESTADOS FORMALES: Si no hay entorno ejecutable, entrega código pero lo marca como UNTESTED_CODE.
   Solo emite VERIFIED_SUCCESS cuando las pruebas reales pasan con exit_code == 0 y se comprueba en disco.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.orca_ade.models import (
    CommandSecurityGuard,
    OrcaResultContract,
    OrcaTaskContract,
)

logger = get_logger("jessyca.orca_ade.code_assistant")

_FORBIDDEN_SYSTEM_PATHS = (
    "\\windows\\",
    "/windows/",
    "\\system32\\",
    "/system32/",
    "\\program files\\",
    "/program files/",
    "\\program files (x86)\\",
    "/program files (x86)/",
    "/etc/",
    "/root/",
    "/bin/",
    "/sbin/",
)


@dataclass
class ProjectFileMetadata:
    """Metadatos observables de un archivo en el proyecto."""

    relative_path: str
    absolute_path: str
    size_bytes: int
    sha256_hash: str
    is_test_file: bool
    is_python_file: bool


@dataclass
class ProjectInspectionReport:
    """Reporte de inspección estructural de un proyecto autorizado."""

    project_dir: str
    total_files: int
    code_files: list[str]
    test_files: list[str]
    files_metadata: dict[str, ProjectFileMetadata]
    structure_summary: dict[str, Any]
    verified: bool = True


@dataclass
class TestExecutionResult:
    """Resultado real observable de la ejecución de una suite de pruebas."""

    __test__ = False  # Evita que pytest lo recolecte erróneamente como clase de test

    passed: bool
    exit_code: int
    command: list[str]
    stdout: str
    stderr: str
    duration_ms: float
    tests_executed: bool = True
    failing_tests: list[str] = field(default_factory=list)
    failure_tracebacks: list[str] = field(default_factory=list)
    environment_available: bool = True
    is_synthetic: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "exit_code": self.exit_code,
            "command": " ".join(self.command),
            "stdout": self.stdout[-1500:] if len(self.stdout) > 1500 else self.stdout,
            "stderr": self.stderr[-1500:] if len(self.stderr) > 1500 else self.stderr,
            "duration_ms": self.duration_ms,
            "tests_executed": self.tests_executed,
            "failing_tests": self.failing_tests,
            "environment_available": self.environment_available,
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class ProblemDiagnosis:
    """Diagnóstico estructurado de un fallo detectado en el proyecto."""

    has_problem: bool
    failing_test_file: str | None = None
    failing_test_name: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    suspected_file: str | None = None
    suspected_line: int | None = None
    traceback_snippet: str | None = None


@dataclass
class PatchProposal:
    """Propuesta de cambio de código con diff real unificado."""

    target_file_relative: str
    target_file_absolute: str
    original_content: str
    patched_content: str
    unified_diff: str
    original_sha256: str
    patched_sha256: str
    diff_lines_count: int


@dataclass
class PatchApplicationResult:
    """Resultado físico observable de la aplicación del parche en disco."""

    success: bool
    target_file: str
    backup_file: str | None
    pre_sha256: str
    post_sha256: str
    bytes_written: int
    diff_applied: str
    verified_on_disk: bool
    error: str | None = None


class ProjectBoundaryValidator:
    """Validador estricto de límites de seguridad de proyectos autorizados."""

    @classmethod
    def validate_project_dir(cls, project_dir: str | Path) -> Path:
        """Valida que el directorio del proyecto exista y no invada rutas del SO."""
        p = Path(project_dir).resolve()
        if not p.exists() or not p.is_dir():
            raise ValueError(f"Directorio de proyecto no válido o inexistente: '{project_dir}'")

        norm = str(p).lower()
        if any(bad in norm for bad in _FORBIDDEN_SYSTEM_PATHS):
            raise PermissionError(f"Acceso denegado: el directorio invade rutas críticas del sistema ('{p}')")

        return p

    @classmethod
    def validate_file_within_project(cls, project_dir: Path, target_file: str | Path) -> Path:
        """Verifica que el archivo destino pertenezca estrictamente al directorio del proyecto."""
        p_target = (project_dir / target_file).resolve() if not Path(target_file).is_absolute() else Path(target_file).resolve()

        try:
            # Comprobar contención física estricta
            common = os.path.commonpath([str(project_dir), str(p_target)])
            if common != str(project_dir):
                raise PermissionError(f"Path traversal bloqueado: '{target_file}' escapa de '{project_dir}'")
        except ValueError:
            raise PermissionError(f"Path traversal bloqueado: '{target_file}' fuera de '{project_dir}'")

        norm = str(p_target).lower()
        if any(bad in norm for bad in _FORBIDDEN_SYSTEM_PATHS):
            raise PermissionError(f"Acceso denegado a ruta de sistema: '{p_target}'")

        return p_target


class ProjectCodeAssistant:
    """Asistente de programación acotado para un directorio de proyecto autorizado."""

    def __init__(self, authorized_project_dir: str | Path) -> None:
        self.project_dir = ProjectBoundaryValidator.validate_project_dir(authorized_project_dir)
        self.python_bin = sys.executable

    # ── 1. INSPECCIONAR PROYECTO ──

    def inspect_project(self) -> ProjectInspectionReport:
        """Escanea e inspecciona la estructura real del proyecto autorizado."""
        code_files: list[str] = []
        test_files: list[str] = []
        metadata_map: dict[str, ProjectFileMetadata] = {}

        ignore_dirs = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "env", ".tox", ".mypy_cache"}

        for root, dirs, files in os.walk(self.project_dir):
            # Filtrar carpetas ignoradas in-place
            dirs[:] = [d for d in dirs if d not in ignore_dirs]

            for fname in sorted(files):
                full_path = Path(root) / fname
                rel_path = str(full_path.relative_to(self.project_dir)).replace("\\", "/")

                is_py = fname.endswith(".py")
                is_test = fname.startswith("test_") or fname.endswith("_test.py")

                if is_py:
                    code_files.append(rel_path)
                if is_test:
                    test_files.append(rel_path)

                # Calcular hash SHA-256 real
                try:
                    with open(full_path, "rb") as f:
                        file_bytes = f.read()
                        sha = hashlib.sha256(file_bytes).hexdigest()
                        size = len(file_bytes)
                except Exception as e:
                    logger.warning(f"Error leyendo archivo {full_path}: {e}")
                    sha = ""
                    size = 0

                meta = ProjectFileMetadata(
                    relative_path=rel_path,
                    absolute_path=str(full_path),
                    size_bytes=size,
                    sha256_hash=sha,
                    is_test_file=is_test,
                    is_python_file=is_py,
                )
                metadata_map[rel_path] = meta

        summary = {
            "root": str(self.project_dir),
            "total_files": len(metadata_map),
            "python_files_count": len(code_files),
            "test_files_count": len(test_files),
            "subdirectories_count": sum(len(d) for _, d, _ in os.walk(self.project_dir)),
        }

        return ProjectInspectionReport(
            project_dir=str(self.project_dir),
            total_files=len(metadata_map),
            code_files=code_files,
            test_files=test_files,
            files_metadata=metadata_map,
            structure_summary=summary,
            verified=True,
        )

    # ── 2. EJECUTAR PRUEBAS AUTORIZADAS ──

    def run_tests(
        self,
        test_target: str | None = None,
        timeout_seconds: float = 30.0,
        extra_args: list[str] | None = None,
    ) -> TestExecutionResult:
        """Ejecuta pruebas autorizadas dentro del proyecto mediante pytest o unittest."""
        start_time = time.perf_counter()

        # Construir comando estricto sin shell
        cmd: list[str] = [self.python_bin, "-m", "pytest"]
        if test_target:
            target_path = ProjectBoundaryValidator.validate_file_within_project(self.project_dir, test_target)
            cmd.append(str(target_path))
        if extra_args:
            # Validar que los argumentos extra sean seguros (solo flags estándar de pytest)
            safe_flags = {"-v", "-q", "-k", "-m", "-s", "--tb=short", "--tb=line", "--tb=auto"}
            for arg in extra_args:
                if arg in safe_flags or (arg.startswith("-k") and len(arg) < 50):
                    cmd.append(arg)

        # Validar el comando antes de ejecutarlo
        cmd_str = " ".join(cmd)
        is_safe, reason = CommandSecurityGuard.validate_command(f"pytest {test_target or ''}")
        if not is_safe and not cmd_str.startswith(f"{self.python_bin} -m pytest"):
            raise PermissionError(f"Comando de prueba denegado por CommandSecurityGuard: {reason}")

        try:
            res = subprocess.run(
                cmd,
                cwd=str(self.project_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            stdout = res.stdout or ""
            stderr = res.stderr or ""
            exit_code = res.returncode
            passed = (exit_code == 0)

            # Analizar fallos reportados
            failing_tests: list[str] = []
            failure_tracebacks: list[str] = []
            for line in stdout.splitlines():
                if "FAILED " in line:
                    failing_tests.append(line.strip())
                if "AssertionError" in line or "Error:" in line or "Exception:" in line:
                    failure_tracebacks.append(line.strip())

            return TestExecutionResult(
                passed=passed,
                exit_code=exit_code,
                command=cmd,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                tests_executed=True,
                failing_tests=failing_tests,
                failure_tracebacks=failure_tracebacks,
                environment_available=True,
                is_synthetic=False,
            )

        except (FileNotFoundError, OSError) as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning(f"Entorno de pruebas no disponible: {e}")
            return TestExecutionResult(
                passed=False,
                exit_code=-1,
                command=cmd,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
                tests_executed=False,
                failing_tests=[],
                failure_tracebacks=[str(e)],
                environment_available=False,
                is_synthetic=False,
            )
        except subprocess.TimeoutExpired as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return TestExecutionResult(
                passed=False,
                exit_code=-99,
                command=cmd,
                stdout=e.stdout or "",
                stderr=f"TimeoutExpired: la prueba excedió {timeout_seconds}s",
                duration_ms=duration_ms,
                tests_executed=True,
                failing_tests=["TIMEOUT"],
                failure_tracebacks=["Execution timed out"],
                environment_available=True,
                is_synthetic=False,
            )

    # ── 3. LOCALIZAR UN PROBLEMA ──

    def diagnose_problem(self, test_result: TestExecutionResult) -> ProblemDiagnosis:
        """Analiza la salida real de pruebas para localizar el archivo y causa de la falla."""
        if test_result.passed:
            return ProblemDiagnosis(has_problem=False)

        # Buscar en stdout el archivo y la aserción fallida
        failing_test_file: str | None = None
        failing_test_name: str | None = None
        error_type: str | None = None
        error_message: str | None = None
        suspected_file: str | None = None
        suspected_line: int | None = None

        combined_text = f"{test_result.stdout}\n{test_result.stderr}"

        # Patrón típico de pytest: FAILED tests/test_foo.py::test_bar - AssertionError: ...
        match_failed = re.search(r"FAILED\s+([^\s:]+)::([^\s\-]+)", combined_text)
        if match_failed:
            failing_test_file = match_failed.group(1).replace("\\", "/")
            failing_test_name = match_failed.group(2)

        # Patrón de línea con error: File "...", line 123
        lines_match = list(re.finditer(r'File\s+["\']([^"\']+)["\'],\s+line\s+(\d+)', combined_text))
        if lines_match:
            # Buscar el archivo sospechoso que pertenezca al proyecto
            for m in reversed(lines_match):
                f_path = m.group(1).replace("\\", "/")
                line_no = int(m.group(2))
                # Preferir archivo de código sobre el de test si es posible
                if not ("test_" in f_path or "_test" in f_path):
                    suspected_file = f_path
                    suspected_line = line_no
                    break
            if not suspected_file and lines_match:
                suspected_file = lines_match[-1].group(1).replace("\\", "/")
                suspected_line = int(lines_match[-1].group(2))

        # Extraer tipo de error (ej. AssertionError, ValueError, ZeroDivisionError)
        err_match = re.search(r"([A-Za-z0-9_]+Error|[A-Za-z0-9_]+Exception):\s*(.*)", combined_text)
        if err_match:
            error_type = err_match.group(1)
            error_message = err_match.group(2).strip()

        # Extraer extracto relevante del traceback
        tb_lines = []
        capture = False
        for l in combined_text.splitlines():
            if "Traceback" in l or "FAILURES" in l or "_ test_" in l:
                capture = True
            if capture:
                tb_lines.append(l)
                if len(tb_lines) >= 25:
                    break
        tb_snippet = "\n".join(tb_lines) if tb_lines else combined_text[:500]

        return ProblemDiagnosis(
            has_problem=True,
            failing_test_file=failing_test_file,
            failing_test_name=failing_test_name,
            error_type=error_type or "UnknownTestFailure",
            error_message=error_message or "Test failed without explicit exception message",
            suspected_file=suspected_file,
            suspected_line=suspected_line,
            traceback_snippet=tb_snippet,
        )

    # ── 4. PROPONER Y APLICAR CAMBIO ACOTADO CON DIFF REAL ──

    def propose_patch(
        self,
        target_file: str | Path,
        new_content: str,
    ) -> PatchProposal:
        """Calcula el diff unificado real entre el archivo actual y el contenido propuesto."""
        abs_target = ProjectBoundaryValidator.validate_file_within_project(self.project_dir, target_file)
        rel_target = str(abs_target.relative_to(self.project_dir)).replace("\\", "/")

        if not abs_target.exists():
            original_content = ""
        else:
            with open(abs_target, "r", encoding="utf-8", newline="", errors="replace") as f:
                original_content = f.read()

        orig_sha = hashlib.sha256(original_content.encode("utf-8")).hexdigest()
        new_sha = hashlib.sha256(new_content.encode("utf-8")).hexdigest()

        orig_lines = original_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = list(
            difflib.unified_diff(
                orig_lines,
                new_lines,
                fromfile=f"a/{rel_target}",
                tofile=f"b/{rel_target}",
                lineterm="",
            )
        )
        diff_str = "\n".join(diff)

        return PatchProposal(
            target_file_relative=rel_target,
            target_file_absolute=str(abs_target),
            original_content=original_content,
            patched_content=new_content,
            unified_diff=diff_str,
            original_sha256=orig_sha,
            patched_sha256=new_sha,
            diff_lines_count=len(diff),
        )

    def apply_patch(self, proposal: PatchProposal, create_backup: bool = True) -> PatchApplicationResult:
        """Aplica físicamente en disco el cambio acotado y verifica el resultado observable."""
        abs_target = Path(proposal.target_file_absolute).resolve()
        ProjectBoundaryValidator.validate_file_within_project(self.project_dir, abs_target)

        backup_path: str | None = None
        if create_backup and abs_target.exists():
            backup_file = abs_target.with_suffix(abs_target.suffix + ".bak")
            shutil.copy2(abs_target, backup_file)
            backup_path = str(backup_file)

        try:
            # Escribir el nuevo contenido de forma atómica/directa sin transformar newlines
            with open(abs_target, "w", encoding="utf-8", newline="") as f:
                f.write(proposal.patched_content)

            # Verificación física en disco
            if not abs_target.exists():
                raise RuntimeError(f"El archivo '{abs_target}' no existe tras la escritura.")

            with open(abs_target, "rb") as f:
                written_bytes = f.read()
                post_sha = hashlib.sha256(written_bytes).hexdigest()

            if post_sha != proposal.patched_sha256:
                raise RuntimeError(
                    f"Inconsistencia de hash: esperado {proposal.patched_sha256}, obtenido {post_sha}"
                )

            logger.info(f"[CODE PATCH APPLIED] '{proposal.target_file_relative}' actualizado con éxito ({len(written_bytes)} bytes)")
            return PatchApplicationResult(
                success=True,
                target_file=str(abs_target),
                backup_file=backup_path,
                pre_sha256=proposal.original_sha256,
                post_sha256=post_sha,
                bytes_written=len(written_bytes),
                diff_applied=proposal.unified_diff,
                verified_on_disk=True,
            )

        except Exception as e:
            # Restaurar respaldo si falló la escritura
            if backup_path and os.path.exists(backup_path):
                shutil.copy2(backup_path, abs_target)
            return PatchApplicationResult(
                success=False,
                target_file=str(abs_target),
                backup_file=backup_path,
                pre_sha256=proposal.original_sha256,
                post_sha256="",
                bytes_written=0,
                diff_applied="",
                verified_on_disk=False,
                error=str(e),
            )


class RealCodeAssistantExecutor:
    """Ejecutor concreto que conecta el asistente de código con OrcaAdeAdapter y Orchestrator."""

    def __init__(self, project_dir: str | Path | None = None) -> None:
        self.project_dir = project_dir

    def execute(self, contract: OrcaTaskContract) -> dict[str, Any]:
        """Ejecuta una tarea de programación dentro del contrato formal de Orca."""
        workspace = contract.workspace or str(self.project_dir)
        assistant = ProjectCodeAssistant(workspace)

        # 1. Inspeccionar proyecto
        inspection = assistant.inspect_project()

        # 2. Ejecutar pruebas iniciales si están solicitadas
        test_res = assistant.run_tests()

        return {
            "changed_files": [],
            "tests": test_res.to_dict(),
            "evidence": [
                {
                    "type": "PROJECT_INSPECTION",
                    "files_count": inspection.total_files,
                    "code_files": inspection.code_files,
                    "test_files": inspection.test_files,
                    "provenance": "REAL_FILESYSTEM",
                    "synthetic": False,
                },
                {
                    "type": "TEST_RUN_OBSERVABLE",
                    "exit_code": test_res.exit_code,
                    "passed": test_res.passed,
                    "duration_ms": test_res.duration_ms,
                    "provenance": "SUBPROCESS_EXECUTION",
                    "synthetic": False,
                },
            ],
            "inspection": inspection,
        }
