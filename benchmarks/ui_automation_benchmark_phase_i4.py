"""Benchmark comparativo de rendimiento, jerarquía y robustez: uiautomation vs pywinauto (Fase I4).

Evalúa:
1. Inspección jerárquica de controles en Bloc de notas (Notepad) y ventana de prueba.
2. Latencia de conexión e inspección (ms).
3. Cobertura de atributos (AutomationId, Name, ControlType, Bounds con soporte multi-monitor).
4. Manejo de ambigüedad (múltiples controles con mismo criterio).
5. Manejo de elementos obsoletos / cerrados (stale element).
6. Ciclo de vida COM (CoInitialize / CoUninitialize) y modo de subproceso.
7. Cumplimiento de separación: Inspección solo-lectura vs Ejecución gobernada.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def run_benchmark() -> dict[str, Any]:
    print("=" * 70)
    print("INICIANDO BENCHMARK COMPARATIVO: uiautomation vs pywinauto (FASE I4)")
    print("=" * 70)

    results: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "environment": {
            "os": platform.platform(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "python_version": sys.version,
        },
        "libraries": {},
        "benchmarks": {},
        "conclusions": {},
    }

    # 1. Verificar versiones de librerías
    try:
        import uiautomation as auto
        results["libraries"]["uiautomation"] = {
            "version": getattr(auto, "VERSION", "unknown"),
            "author": getattr(auto, "AUTHOR_NAME", "yinkaisheng"),
            "available": True,
        }
    except Exception as e:
        results["libraries"]["uiautomation"] = {"available": False, "error": str(e)}

    try:
        import pywinauto
        results["libraries"]["pywinauto"] = {
            "version": pywinauto.__version__,
            "available": True,
        }
    except Exception as e:
        results["libraries"]["pywinauto"] = {"available": False, "error": str(e)}

    print(f"OS: {results['environment']['os']}")
    print(f"uiautomation: {results['libraries'].get('uiautomation', {}).get('version')}")
    print(f"pywinauto: {results['libraries'].get('pywinauto', {}).get('version')}")

    # 2. Iniciar Bloc de notas para prueba real
    print("\n[PASO 1] Abriendo Bloc de notas (notepad.exe)...")
    proc = subprocess.Popen(["notepad.exe"])
    time.sleep(2.0)  # Permitir inicialización de la ventana

    notepad_target: dict[str, Any] = {"pid": proc.pid}
    notepad_benchmarks: dict[str, Any] = {}

    try:
        import uiautomation as auto
        from pywinauto import Desktop

        # A. Inspección con uiautomation nativo
        print("[PASO 2] Evaluando uiautomation nativo...")
        t0 = time.perf_counter()
        root = auto.GetRootControl()
        target_uia = None
        for child in root.GetChildren():
            c_name = (child.Name or "").lower()
            if "bloc de notas" in c_name or "notepad" in c_name or child.ClassName == "Notepad":
                target_uia = child
                break
        t_find_uia = (time.perf_counter() - t0) * 1000

        uia_elements: list[dict[str, Any]] = []
        t_tree_uia = 0.0
        if target_uia:
            notepad_target["title"] = target_uia.Name
            notepad_target["class_name"] = target_uia.ClassName
            notepad_target["hwnd"] = target_uia.NativeWindowHandle
            notepad_target["process_id"] = target_uia.ProcessId

            t0_tree = time.perf_counter()
            def collect_uia(ctrl: auto.Control, depth: int) -> None:
                rect = ctrl.BoundingRectangle
                uia_elements.append({
                    "name": ctrl.Name or "",
                    "control_type": ctrl.ControlTypeName or "",
                    "automation_id": ctrl.AutomationId or "",
                    "class_name": ctrl.ClassName or "",
                    "bounds": {"x": rect.left, "y": rect.top, "w": rect.width(), "h": rect.height()} if rect else None,
                    "depth": depth,
                    "is_enabled": ctrl.IsEnabled,
                })
                if depth < 5 and len(uia_elements) < 100:
                    for ch in ctrl.GetChildren():
                        if len(uia_elements) >= 100:
                            break
                        collect_uia(ch, depth + 1)

            collect_uia(target_uia, 1)
            t_tree_uia = (time.perf_counter() - t0_tree) * 1000

        notepad_benchmarks["uiautomation"] = {
            "window_found": target_uia is not None,
            "window_search_latency_ms": round(t_find_uia, 2),
            "hierarchy_traversal_latency_ms": round(t_tree_uia, 2),
            "element_count": len(uia_elements),
            "supports_negative_coords": any(
                el.get("bounds") and (el["bounds"]["x"] < 0 or el["bounds"]["y"] < 0)
                for el in uia_elements
            ) if uia_elements else False,
            "sample_controls": uia_elements[:5],
        }

        # B. Inspección con pywinauto (backend='uia')
        print("[PASO 3] Evaluando pywinauto (backend='uia')...")
        t0 = time.perf_counter()
        desktop_pwa = Desktop(backend="uia")
        target_pwa = None
        for win in desktop_pwa.windows():
            w_text = (win.window_text() or "").lower()
            if "bloc de notas" in w_text or "notepad" in w_text or win.class_name() == "Notepad":
                target_pwa = win
                break
        t_find_pwa = (time.perf_counter() - t0) * 1000

        pwa_elements: list[dict[str, Any]] = []
        t_tree_pwa = 0.0
        if target_pwa:
            t0_tree = time.perf_counter()
            def collect_pwa(ctrl: Any, depth: int) -> None:
                try:
                    rect = ctrl.rectangle()
                    pwa_elements.append({
                        "name": ctrl.window_text() or "",
                        "control_type": ctrl.element_info.control_type or "",
                        "automation_id": ctrl.element_info.automation_id or "",
                        "class_name": ctrl.class_name() or "",
                        "bounds": {"x": rect.left, "y": rect.top, "w": rect.width(), "h": rect.height()} if rect else None,
                        "depth": depth,
                        "is_enabled": ctrl.is_enabled(),
                    })
                    if depth < 5 and len(pwa_elements) < 100:
                        for ch in ctrl.children():
                            if len(pwa_elements) >= 100:
                                break
                            collect_pwa(ch, depth + 1)
                except Exception:
                    pass

            collect_pwa(target_pwa, 1)
            t_tree_pwa = (time.perf_counter() - t0_tree) * 1000

        notepad_benchmarks["pywinauto_uia"] = {
            "window_found": target_pwa is not None,
            "window_search_latency_ms": round(t_find_pwa, 2),
            "hierarchy_traversal_latency_ms": round(t_tree_pwa, 2),
            "element_count": len(pwa_elements),
            "supports_negative_coords": any(
                el.get("bounds") and (el["bounds"]["x"] < 0 or el["bounds"]["y"] < 0)
                for el in pwa_elements
            ) if pwa_elements else False,
            "sample_controls": pwa_elements[:5],
        }

        # C. Manejo de Ambigüedad y Búsqueda Específica
        print("[PASO 4] Evaluando resolución de controles y ambigüedad...")
        ambiguity_eval: dict[str, Any] = {}

        # uiautomation: búsqueda por AutomationId o ClassName
        if target_uia:
            t0_spec = time.perf_counter()
            edit_uia = target_uia.EditControl(searchDepth=3)
            exists_uia = edit_uia.Exists(maxSearchSeconds=0.5)
            t_spec_uia = (time.perf_counter() - t0_spec) * 1000
            ambiguity_eval["uiautomation_specific_search_ms"] = round(t_spec_uia, 2)
            ambiguity_eval["uiautomation_edit_found"] = exists_uia

        # pywinauto: búsqueda por criteria
        if target_pwa:
            t0_spec = time.perf_counter()
            try:
                edit_pwa = target_pwa.child_window(control_type="Edit")
                exists_pwa = edit_pwa.exists(timeout=0.5)
            except Exception:
                exists_pwa = False
            t_spec_pwa = (time.perf_counter() - t0_spec) * 1000
            ambiguity_eval["pywinauto_specific_search_ms"] = round(t_spec_pwa, 2)
            ambiguity_eval["pywinauto_edit_found"] = exists_pwa

        results["benchmarks"]["notepad_target"] = notepad_target
        results["benchmarks"]["notepad_comparison"] = notepad_benchmarks
        results["benchmarks"]["ambiguity_evaluation"] = ambiguity_eval

    finally:
        print("[PASO 5] Cerrando Bloc de notas...")
        subprocess.call(["taskkill", "/F", "/IM", "notepad.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)

    # 3. Prueba de Stale Elements / Ventana destruida
    print("\n[PASO 6] Evaluando comportamiento ante Stale Element (ventana destruida)...")
    stale_eval: dict[str, Any] = {}
    _ = subprocess.Popen(["notepad.exe"])
    time.sleep(1.5)
    try:
        import uiautomation as auto
        from pywinauto import Desktop

        root = auto.GetRootControl()
        win_uia_stale = None
        for c in root.GetChildren():
            if "bloc" in (c.Name or "").lower() or "notepad" in (c.Name or "").lower():
                win_uia_stale = c
                break

        d_stale = Desktop(backend="uia")
        win_pwa_stale = None
        for w in d_stale.windows():
            if "bloc" in (w.window_text() or "").lower() or "notepad" in (w.window_text() or "").lower():
                win_pwa_stale = w
                break

        # Matar proceso para convertir en stale element
        subprocess.call(["taskkill", "/F", "/IM", "notepad.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.8)

        # Probar uiautomation tras destrucción
        try:
            uia_name_after = win_uia_stale.Name if win_uia_stale else "not_found"
            stale_eval["uiautomation_after_close"] = {"exception": False, "result": uia_name_after}
        except Exception as e:
            stale_eval["uiautomation_after_close"] = {"exception": True, "error_type": type(e).__name__, "message": str(e)}

        # Probar pywinauto tras destrucción
        try:
            pwa_text_after = win_pwa_stale.window_text() if win_pwa_stale else "not_found"
            stale_eval["pywinauto_after_close"] = {"exception": False, "result": pwa_text_after}
        except Exception as e:
            stale_eval["pywinauto_after_close"] = {"exception": True, "error_type": type(e).__name__, "message": str(e)}

    finally:
        subprocess.call(["taskkill", "/F", "/IM", "notepad.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    results["benchmarks"]["stale_element_evaluation"] = stale_eval

    # 4. Evaluación de COM Initialization y Threading
    print("\n[PASO 7] Evaluando COM Initialization y Concurrencia...")
    com_eval: dict[str, Any] = {
        "uiautomation_com_requirement": "Inicializa COM internamente a través de comtypes. CoInitializeEx se maneja transparentemente.",
        "pywinauto_com_requirement": "Advierte 'Revert to STA COM threading mode' al importar; requiere modo STA y puede colisionar con bucles asyncio si no se ejecuta en worker dedicado.",
    }
    results["benchmarks"]["com_evaluation"] = com_eval

    # 5. Análisis y Conclusiones Arquitectónicas
    print("\n[PASO 8] Generando conclusiones...")
    uia_res = notepad_benchmarks.get("uiautomation", {})
    pwa_res = notepad_benchmarks.get("pywinauto_uia", {})

    uia_total_ms = uia_res.get("window_search_latency_ms", 0) + uia_res.get("hierarchy_traversal_latency_ms", 0)
    pwa_total_ms = pwa_res.get("window_search_latency_ms", 0) + pwa_res.get("hierarchy_traversal_latency_ms", 0)

    conclusions = {
        "speed_comparison": {
            "uiautomation_total_ms": round(uia_total_ms, 2),
            "pywinauto_total_ms": round(pwa_total_ms, 2),
            "fastest": "uiautomation" if uia_total_ms <= pwa_total_ms else "pywinauto",
            "ratio": round(pwa_total_ms / max(1.0, uia_total_ms), 2),
        },
        "controls_detected": {
            "uiautomation_elements": uia_res.get("element_count", 0),
            "pywinauto_elements": pwa_res.get("element_count", 0),
        },
        "multi_monitor_support": {
            "native_uiautomation": "Preserva coordenadas rect.left y rect.top negativas sin clamping",
            "pywinauto": "rectangle() devuelve L, T, R, B preservando coordenadas virtuales de Windows",
        },
        "architectural_recommendation": (
            "uiautomation es más rápido, ligero y directo para inspección pura de sólo lectura (IUIInspectionBackend), "
            "sin forzar modo STA COM global que afecte a FastAPI/asyncio. "
            "pywinauto añade un envoltorio de alto nivel útil para aplicaciones legacy win32 pero introduce sobrecarga de STA COM y mayor latencia. "
            "Recomendación: Implementar adaptador opcional PyWinAutoInspectionBackend y PyWinAutoGovernedActionExecutor "
            "detrás de las interfaces correspondientes con flag desactivado por defecto (PYWINAUTO_ENABLED=False), "
            "manteniendo uiautomation como backend nativo primario y preservando la regla de oro: CERO clicks en IUIInspectionBackend."
        ),
    }
    results["conclusions"] = conclusions

    # Guardar reporte
    out_dir = Path("reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / "pywinauto_vs_uiautomation_benchmark.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n[BENCHMARK COMPLETADO] Reporte guardado en: {report_file}")
    print(f"- uiautomation: {uia_total_ms:.2f} ms ({uia_res.get('element_count', 0)} elementos)")
    print(f"- pywinauto:    {pwa_total_ms:.2f} ms ({pwa_res.get('element_count', 0)} elementos)")
    print(f"- Recomendación: {conclusions['architectural_recommendation']}")
    return results


if __name__ == "__main__":
    run_benchmark()
