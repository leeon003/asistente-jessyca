"""Panel de Inspección CLI y Métricas del Shadow Mode (tools/router_shadow_dashboard.py).

Permite visualizar rápidamente:
- Las últimas N decisiones del Router Inteligente en modo Shadow.
- Estadísticas acumuladas (volumen, distribución de tipos de tarea, modelos recomendados, confianza, latencia).
- Marcado de evaluación posterior ('appropriate', 'questionable', 'inappropriate').
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.llm.experimental_router import ShadowLogger


def load_shadow_entries(log_path: Path) -> list[dict[str, Any]]:
    """Carga todas las entradas registradas en el archivo JSONL de shadow mode."""
    if not log_path.exists():
        return []
    entries = []
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                entries.append(json.loads(line_str))
            except Exception:
                pass
    return entries


def format_table(entries: list[dict[str, Any]], limit: int = 20) -> str:
    """Genera una tabla ASCII / texto legible con las últimas decisiones."""
    recent = list(reversed(entries[-limit:]))
    if not recent:
        return "No hay registros disponibles en el log shadow."

    lines = []
    header = (
        f"{'HORA':<19} | {'ORDEN':<35} | {'TIPO':<17} | "
        f"{'MODELO REC.':<15} | {'CONF.':<6} | {'MODELO EJEC.':<14} | {'LATENCIA':<8}"
    )
    separator = "-" * len(header)
    lines.append(separator)
    lines.append(header)
    lines.append(separator)

    for e in recent:
        ts = e.get("timestamp")
        if ts:
            try:
                hora = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                hora = str(e.get("iso_time", ""))[:19]
        else:
            hora = str(e.get("iso_time", ""))[:19]

        user_text = str(e.get("user_text", "")).replace("\n", " ")
        if len(user_text) > 33:
            user_text = user_text[:30] + "..."

        task_type = str(e.get("task_type", ""))[:17]
        rec_model = str(e.get("recommended_model", "")).replace("nvidia/", "").replace(":e4b", "").replace(":8b", "")[:15]
        conf = f"{float(e.get('confidence', 0.0)):.2f}"
        exec_model = str(e.get("execution_model", "")).replace(":e4b", "")[:14]
        lat = f"{float(e.get('router_decision_latency_ms', e.get('latency_ms', 0.0))):.2f}ms"

        row = (
            f"{hora:<19} | {user_text:<35} | {task_type:<17} | "
            f"{rec_model:<15} | {conf:<6} | {exec_model:<14} | {lat:<8}"
        )
        lines.append(row)

    lines.append(separator)
    return "\n".join(lines)


def calculate_metrics(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcula el resumen analítico y métricas operativas del router."""
    total = len(entries)
    if total == 0:
        return {"total": 0}

    task_types: dict[str, int] = {}
    recommended_models: dict[str, int] = {}
    confidences: list[float] = []
    latencies: list[float] = []
    low_confidence_cases = 0
    questionable_cases = 0
    nemotron_recommended = 0
    qwen_recommended = 0
    gemma_recommended = 0

    for e in entries:
        t_type = e.get("task_type", "other")
        task_types[t_type] = task_types.get(t_type, 0) + 1

        rec = e.get("recommended_model", "gemma4:e4b")
        recommended_models[rec] = recommended_models.get(rec, 0) + 1

        if "nemotron" in rec.lower():
            nemotron_recommended += 1
        elif "qwen" in rec.lower():
            qwen_recommended += 1
        else:
            gemma_recommended += 1

        conf = float(e.get("confidence", 0.0))
        confidences.append(conf)
        if conf < 0.80:
            low_confidence_cases += 1

        eval_val = str(e.get("evaluation", "")).lower()
        if eval_val in ("questionable", "inappropriate"):
            questionable_cases += 1

        lat = float(e.get("router_decision_latency_ms", e.get("latency_ms", 0.0)))
        latencies.append(lat)

    avg_conf = sum(confidences) / total if confidences else 0.0
    min_conf = min(confidences) if confidences else 0.0
    avg_lat = sum(latencies) / total if latencies else 0.0

    return {
        "total": total,
        "task_types": task_types,
        "recommended_models": recommended_models,
        "gemma_recommended": gemma_recommended,
        "qwen_recommended": qwen_recommended,
        "nemotron_recommended": nemotron_recommended,
        "avg_confidence": round(avg_conf, 4),
        "min_confidence": round(min_conf, 4),
        "low_confidence_cases": low_confidence_cases,
        "questionable_cases": questionable_cases,
        "avg_overhead_ms": round(avg_lat, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="JESSYCA Shadow Mode Inspector & Metrics Dashboard")
    parser.add_argument("--limit", type=int, default=20, help="Número de decisiones recientes a mostrar (default: 20)")
    parser.add_argument("--log-path", type=str, default="logs/router_shadow.jsonl", help="Ruta al archivo JSONL shadow")
    parser.add_argument("--summary", action="store_true", help="Muestra el resumen consolidado de métricas")
    parser.add_argument("--evaluate", nargs=2, metavar=("REQUEST_ID", "VERDICT"), help="Evalúa una decisión: <REQUEST_ID> <appropriate|questionable|inappropriate>")
    parser.add_argument("--notes", type=str, default="", help="Notas explicativas de la evaluación")

    args = parser.parse_args()
    log_path = Path(args.log_path)

    # Manejo de evaluación
    if args.evaluate:
        req_id, verdict = args.evaluate
        logger = ShadowLogger(log_path=log_path)
        try:
            ok = logger.update_evaluation(request_id=req_id, evaluation=verdict, notes=args.notes)
            if ok:
                print(f"[OK] Decisión '{req_id}' evaluada como '{verdict}'.")
                return 0
            else:
                print(f"[ERROR] No se encontró el request_id '{req_id}' en {log_path}.")
                return 1
        except Exception as e:
            print(f"[ERROR] Error evaluando decisión: {e}")
            return 1

    entries = load_shadow_entries(log_path)
    metrics = calculate_metrics(entries)

    print("\n" + "=" * 80)
    print(" JESSYCA PC — SHADOW ROUTER INSPECTOR (FASE 4)")
    print("=" * 80)
    print(f"Archivo de logs: {log_path.resolve()}")
    print(f"Total de órdenes registradas: {metrics.get('total', 0)}")
    print(f"Overhead medio del Router: {metrics.get('avg_overhead_ms', 0.0):.3f} ms")
    print(f"Confianza media: {metrics.get('avg_confidence', 0.0):.2f} (Mínima: {metrics.get('min_confidence', 0.0):.2f})")
    print("-" * 80)

    print(format_table(entries, limit=args.limit))

    if args.summary or len(entries) > 0:
        print("\nRESUMEN DE DISTRIBUCIÓN:")
        print(f"  • Fast Interaction  : {metrics.get('task_types', {}).get('fast_interaction', 0)}")
        print(f"  • Technical         : {metrics.get('task_types', {}).get('technical', 0)}")
        print(f"  • Complex Reasoning : {metrics.get('task_types', {}).get('complex_reasoning', 0)}")
        print(f"  • Agent Planning    : {metrics.get('task_types', {}).get('agent_planning', 0)}")
        print(f"  • Ambiguous         : {metrics.get('task_types', {}).get('ambiguous', 0)}")
        print(f"  • Conversation      : {metrics.get('task_types', {}).get('conversation', 0)}")
        print(f"  • Other             : {metrics.get('task_types', {}).get('other', 0)}")
        print("\nMODELOS RECOMENDADOS:")
        print(f"  • Gemma 4 e4b       : {metrics.get('gemma_recommended', 0)}")
        print(f"  • Qwen3 8B          : {metrics.get('qwen_recommended', 0)}")
        print(f"  • Nemotron 3 Ultra  : {metrics.get('nemotron_recommended', 0)}")
        print("=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
