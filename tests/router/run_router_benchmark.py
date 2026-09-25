"""Script de evaluación cuantitativa del Benchmark de Routing (tests/router/run_router_benchmark.py).

Ejecuta los 50 casos del benchmark comparando:
- Modo STATIC (fijo en gemma4:e4b)
- Modo SHADOW (recomendación registrada, ejecución fija)
- Modo EXPERIMENTAL (enrutamiento inteligente activado)

Calcula:
- Routing accuracy por categoría.
- Distribución de confianza (media, mín, máx).
- Latencia del proceso de decisión del router.
- Falsos enrutamientos (false routings).
- Tasas de selección de modelos por categoría.
- Verificación de exclusión de Nemotron cuando está desactivado.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.llm.experimental_router import (
    ExperimentalRouter,
    RouterDecision,
    RouterMode,
    ShadowLogger,
    TaskCategory,
)
from tests.router.test_cases import ROUTER_BENCHMARK_CASES, RouterTestCase


def run_benchmark_evaluation() -> dict[str, Any]:
    log_file = Path("logs/router_benchmark_run.jsonl")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if log_file.exists():
        log_file.unlink()

    shadow_logger = ShadowLogger(log_path=log_file)

    # 1. Ejecución con Nemotron habilitado (condición de prueba para evaluar discriminación)
    os.environ["NEMOTRON_ENABLED"] = "true"
    router_exp = ExperimentalRouter(mode=RouterMode.EXPERIMENTAL, shadow_logger=shadow_logger)

    results: list[dict[str, Any]] = []
    category_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "total": 0,
        "correct_category": 0,
        "acceptable_model": 0,
        "confidences": [],
        "routing_latencies_ms": [],
        "models_selected": defaultdict(int),
    })

    for case in ROUTER_BENCHMARK_CASES:
        t0 = time.perf_counter()
        exec_model, decision = router_exp.route_execution(
            user_text=case.prompt,
            current_model="gemma4:e4b",
            is_voice=case.is_voice,
            is_offline=case.is_offline,
            request_id=f"bench_{case.test_id}",
        )
        lat_ms = (time.perf_counter() - t0) * 1000.0

        is_cat_correct = (decision.task_type == case.expected_task_type)
        is_model_acceptable = (decision.recommended_model in case.acceptable_models)
        cat_key = case.category.value

        stats = category_stats[cat_key]
        stats["total"] += 1
        if is_cat_correct:
            stats["correct_category"] += 1
        if is_model_acceptable:
            stats["acceptable_model"] += 1
        stats["confidences"].append(decision.confidence)
        stats["routing_latencies_ms"].append(lat_ms)
        stats["models_selected"][decision.recommended_model] += 1

        results.append({
            "test_id": case.test_id,
            "category": cat_key,
            "prompt": case.prompt,
            "task_type_classified": decision.task_type.value,
            "is_cat_correct": is_cat_correct,
            "recommended_model": decision.recommended_model,
            "is_model_acceptable": is_model_acceptable,
            "confidence": decision.confidence,
            "latency_ms": lat_ms,
            "reason": decision.reason,
        })

    # 2. Evaluación de seguridad: NEMOTRON_ENABLED=false
    os.environ["NEMOTRON_ENABLED"] = "false"
    router_disabled = ExperimentalRouter(mode=RouterMode.EXPERIMENTAL, shadow_logger=shadow_logger)
    disabled_nemotron_leaks = 0

    for case in ROUTER_BENCHMARK_CASES:
        _, decision = router_disabled.route_execution(
            user_text=case.prompt,
            current_model="gemma4:e4b",
            is_voice=case.is_voice,
            is_offline=case.is_offline,
        )
        if "nemotron" in decision.recommended_model.lower():
            disabled_nemotron_leaks += 1

    # Restaurar protección por defecto
    os.environ["NEMOTRON_ENABLED"] = "false"

    # Resumen cuantitativo
    total_cases = len(ROUTER_BENCHMARK_CASES)
    total_acceptable = sum(s["acceptable_model"] for s in category_stats.values())
    all_latencies = [r["latency_ms"] for r in results]
    all_confidences = [r["confidence"] for r in results]

    summary = {
        "total_cases": total_cases,
        "overall_routing_accuracy_pct": round((total_acceptable / total_cases) * 100.0, 2),
        "false_routings_count": total_cases - total_acceptable,
        "avg_routing_overhead_ms": round(sum(all_latencies) / len(all_latencies), 3),
        "max_routing_overhead_ms": round(max(all_latencies), 3),
        "min_confidence": round(min(all_confidences), 4),
        "avg_confidence": round(sum(all_confidences) / len(all_confidences), 4),
        "max_confidence": round(max(all_confidences), 4),
        "disabled_nemotron_leaks": disabled_nemotron_leaks,
        "category_breakdown": {
            k: {
                "total": v["total"],
                "accuracy_pct": round((v["acceptable_model"] / v["total"]) * 100.0, 2),
                "avg_confidence": round(sum(v["confidences"]) / len(v["confidences"]), 3),
                "avg_latency_ms": round(sum(v["routing_latencies_ms"]) / len(v["routing_latencies_ms"]), 3),
                "models_selected": dict(v["models_selected"]),
            }
            for k, v in category_stats.items()
        },
    }

    print("\n" + "=" * 60)
    print("BENCHMARK ROUTER EXPERIMENTAL — RESULTADOS CUANTITATIVOS")
    print("=" * 60)
    print(f"Total casos evaluados:          {summary['total_cases']}")
    print(f"Routing Accuracy Global:        {summary['overall_routing_accuracy_pct']}%")
    print(f"Falsos enrutamientos (errores): {summary['false_routings_count']}")
    print(f"Overhead medio de decisión:     {summary['avg_routing_overhead_ms']} ms")
    print(f"Overhead máx de decisión:       {summary['max_routing_overhead_ms']} ms")
    print(f"Confianza media del router:     {summary['avg_confidence']}")
    print(f"Fugas con Nemotron deshab.:     {summary['disabled_nemotron_leaks']}")
    print("-" * 60)
    print("Desglose por Categoría:")
    for cat, data in summary["category_breakdown"].items():
        print(f"  • {cat.upper()}: {data['accuracy_pct']}% exactitud | Conf: {data['avg_confidence']} | Lat: {data['avg_latency_ms']} ms | Modelos: {data['models_selected']}")
    print("=" * 60 + "\n")

    return summary


if __name__ == "__main__":
    run_benchmark_evaluation()
