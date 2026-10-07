"""Demostración del Recorrido Funcional de Asistencia de Programación (JESSYCA / ORCA + ADE + ARE).

Ejecuta el ciclo completo:
1. Inicializa un proyecto en 'data/pruebas_programacion/demo_proyecto_calculadora/'.
2. Inyecta un módulo 'calculadora.py' con un fallo conocido y una prueba 'test_calculadora.py'.
3. Inspecciona el proyecto y genera el inventario observable.
4. Ejecuta la prueba autorizada inicial y detecta el fallo real (AssertionError).
5. Diagnostica la causa raíz y genera el diff unificado real.
6. Aplica el parche acotado en disco verificando integridad SHA-256.
7. Ejecuta nuevamente la prueba autorizada y verifica que ahora pasa al 100% (exit_code == 0).
8. Emite el reporte formal con evidencia observable y estado VERIFIED_SUCCESS.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# Asegurar raíz del proyecto en sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.orca_ade.code_assistant import ProblemDiagnosis
from core.orca_ade.workflow import CodeAssistantWorkflow


def run_standalone_demo() -> dict:
    base_dir = Path("data/pruebas_programacion/demo_proyecto_calculadora").resolve()
    if base_dir.exists():
        shutil.rmtree(base_dir, ignore_errors=True)
    base_dir.mkdir(parents=True, exist_ok=True)

    # 1. Crear código con fallo conocido
    code_path = base_dir / "calculadora.py"
    with open(code_path, "w", encoding="utf-8", newline="") as f:
        f.write(
            '"""Módulo de operaciones aritméticas JESSYCA Core."""\n\n'
            "def sumar(a: int, b: int) -> int:\n"
            '    """Retorna la suma de dos números enteros."""\n'
            "    return a - b  # BUG CONOCIDO: operación errónea (resta en vez de suma)\n\n"
            "def multiplicar(a: int, b: int) -> int:\n"
            '    """Retorna el producto de dos números enteros."""\n'
            "    return a * b\n"
        )

    # 2. Crear suite de pruebas unitarias
    test_path = base_dir / "test_calculadora.py"
    with open(test_path, "w", encoding="utf-8", newline="") as f:
        f.write(
            '"""Pruebas unitarias autorizadas para calculadora."""\n\n'
            "from calculadora import sumar, multiplicar\n\n"
            "def test_sumar_operacion_basica():\n"
            "    assert sumar(15, 10) == 25, '15 + 10 debe ser igual a 25'\n\n"
            "def test_multiplicar_operacion_basica():\n"
            "    assert multiplicar(6, 7) == 42\n"
        )

    print(f"[DEMO SETUP] Proyecto inicializado en: {base_dir}")
    print(f"[DEMO SETUP] Código con fallo: {code_path}")
    print(f"[DEMO SETUP] Prueba autorizada: {test_path}")

    # 3. Inicializar el workflow gobernado
    workflow = CodeAssistantWorkflow(base_dir)

    def fixer(diag: ProblemDiagnosis, inspection) -> tuple[str, str]:
        target = base_dir / "calculadora.py"
        with open(target, "r", encoding="utf-8", newline="") as f:
            orig = f.read()
        fixed = orig.replace("return a - b  # BUG CONOCIDO: operación errónea (resta en vez de suma)", "return a + b  # CORREGIDO: suma real verificada")
        return "calculadora.py", fixed

    # 4. Ejecutar el recorrido completo
    report = workflow.run_assisted_repair_workflow(
        test_target="test_calculadora.py",
        fix_provider_fn=fixer,
    )

    # 5. Guardar reporte de auditoría inmutable
    report_file = base_dir / "reporte_asistencia_programacion.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 65)
    print("REPORTE DE ASISTENCIA DE PROGRAMACIÓN JESSYCA 3.0 / ORCA + ADE")
    print("=" * 65)
    print(f"Directorio de Proyecto: {report.project_dir}")
    print(f"Estado Final: {report.status} (Verificado: {report.verified})")
    print(f"Ejecución Real en Disco: {report.is_real_execution}")
    print(f"Prueba Inicial Fallida: {report.diagnosis.failing_test_name} ({report.diagnosis.error_type})")
    print(f"Exit Code Inicial: {report.initial_test_result.exit_code}")
    print("\n--- DIFF UNIFICADO REAL ---")
    print(report.diff_unified)
    print("---------------------------")
    print(f"Parche Aplicado: {report.patch_application.target_file if report.patch_application else 'None'}")
    print(f"SHA-256 Pre-parche:  {report.patch_application.pre_sha256 if report.patch_application else 'None'}")
    print(f"SHA-256 Post-parche: {report.patch_application.post_sha256 if report.patch_application else 'None'}")
    print(f"Pruebas Finales Aprobadas: {report.verification_test_result.passed if report.verification_test_result else False}")
    print(f"Exit Code Final: {report.verification_test_result.exit_code if report.verification_test_result else None}")
    print(f"Duración Total: {report.duration_ms:.2f} ms")
    print("=" * 65)

    return report.to_dict()


if __name__ == "__main__":
    run_standalone_demo()
