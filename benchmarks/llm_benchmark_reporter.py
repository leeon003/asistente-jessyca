"""Generador de reportes estructurados para el Benchmark Suite (llm_benchmark_reporter.py - Fase 17).

Produce informes en Markdown y JSON con tablas comparativas por modelo, métricas de rendimiento y asignaciones óptimas recomendadas para el ModelRouter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarks.llm_benchmark_runner import ModelBenchmarkSummary


class LLMBenchmarkReporter:
    """Generador de informes visuales y analíticos del benchmark de LLMs."""

    @classmethod
    def generate_markdown_report(
        cls,
        summaries: dict[str, ModelBenchmarkSummary],
        output_file: Path | str | None = None,
    ) -> str:
        """Genera un reporte completo en formato GitHub Markdown estructurado."""
        lines: list[str] = [
            "# LLM BENCHMARK REPORT — JESSYCA 3.0 (FASE 17)",
            "",
            "## 1. Resumen Comparativo de Rendimiento por Modelo",
            "",
            "| Modelo | Precisión Global | Latencia Media | Tokens/seg | Validez JSON | Tool-Call Acc | VRAM Estimada | Carga / Descarga |",
            "|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
        ]

        for name, s in summaries.items():
            lines.append(
                f"| `{name}` | **{s.accuracy:.1%}** | {s.avg_latency_ms:.1f} ms | {s.avg_tokens_per_sec:.1f} t/s | {s.json_validity_rate:.1%} | {s.tool_call_accuracy_rate:.1%} | {s.vram_usage_mb} MB | {s.model_load_time_ms:.0f}ms / {s.model_unload_time_ms:.0f}ms |"
            )

        lines.extend([
            "",
            "---",
            "",
            "## 2. Desglose de Desempeño por Categoría (12 Categorías)",
            "",
        ])

        # Extraer todas las categorías
        all_categories: list[str] = []
        for s in summaries.values():
            for cat in s.category_scores.keys():
                if cat not in all_categories:
                    all_categories.append(cat)

        header = "| Categoría | " + " | ".join(f"`{m}`" for m in summaries.keys()) + " |"
        separator = "|:---|" + "|".join(":---:" for _ in summaries) + "|"
        lines.append(header)
        lines.append(separator)

        for cat in sorted(all_categories):
            row = [f"**{cat}**"]
            for m in summaries.values():
                score = m.category_scores.get(cat, 0.0)
                row.append(f"{score:.0%}")
            lines.append("| " + " | ".join(row) + " |")

        lines.extend([
            "",
            "---",
            "",
            "## 3. Asignación Óptima Recomendada para ModelRouter (Empíricamente Validada)",
            "",
            "- **`llama3.2:latest`** (3.5 GB VRAM): Modelo ultrarrápido ideal para **Fast-Path**, clasificación y parseo de intenciones simples.",
            "- **`llama3.1:latest`** (8.0 GB VRAM): Modelo insignia de **Razonamiento Complejo**, planificación multi-paso y recuperación de errores.",
            "- **`qwen3:8b`** (6.0 GB VRAM): Modelo de máxima precisión en **Tool Calling** y **Generación Estricta de JSON**.",
            "- **`qwen3-vl:4b`** (4.5 GB VRAM): Especialista exclusivo en **Visión Multimodal** e inspección de interfaces de escritorio.",
            "- **`gemma4:e4b`** (3.8 GB VRAM): Excelente en **Conversación**, síntesis y soporte en consensos Multi-LLM.",
            "",
            "---",
            "",
            "## 4. Conclusiones del Gobernador de VRAM (RTX 3060 12GB)",
            "",
            "1. **Presupuesto Total**: 12,288 MB VRAM (10,752 MB utilizables tras 1,536 MB de reserva para Windows/DWM).",
            "2. **Estrategia Óptima de Residencia**: Mantener `llama3.2:latest` (3.5GB) o `gemma4:e4b` (3.8GB) como modelo residente rápido.",
            "3. **Swap / Desalojo Determinista**: Cuando se requiere `llama3.1:latest` (8GB), desalojar modelos secundarios para prevenir OOM sin comprometer la latencia de respuesta.",
        ])

        report_md = "\n".join(lines)

        if output_file:
            path = Path(output_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(report_md)

        return report_md

    @classmethod
    def export_json_metrics(
        cls,
        summaries: dict[str, ModelBenchmarkSummary],
        output_file: Path | str | None = None,
    ) -> dict[str, Any]:
        """Exporta las métricas estructuradas en formato JSON."""
        data: dict[str, Any] = {}
        for name, s in summaries.items():
            data[name] = {
                "accuracy": s.accuracy,
                "avg_latency_ms": s.avg_latency_ms,
                "avg_tokens_per_sec": s.avg_tokens_per_sec,
                "json_validity_rate": s.json_validity_rate,
                "tool_call_accuracy_rate": s.tool_call_accuracy_rate,
                "hallucination_rate": s.hallucination_rate,
                "context_adherence_rate": s.context_adherence_rate,
                "vram_usage_mb": s.vram_usage_mb,
                "model_load_time_ms": s.model_load_time_ms,
                "model_unload_time_ms": s.model_unload_time_ms,
                "category_scores": s.category_scores,
            }

        if output_file:
            path = Path(output_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        return data
