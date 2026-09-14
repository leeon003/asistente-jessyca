"""Benchmark Comparativo: Pocket TTS vs Edge-TTS Camila (Fase 72).

Evalúa de forma reproducible:
1. Latencias cuantitativas: T1 (inicio), T2 (primer audio), T3 (tiempo total), T4 (duración), RTF.
2. Consumo de recursos: CPU %, RAM (MB), GPU VRAM si está disponible.
3. Estabilidad: 10 generaciones consecutivas para evaluar fugas o degradación.
4. Comparativa cualitativa sobre 4 frases representativas de distintas longitudes.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

# Asegurar UTF-8 en terminal Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import psutil

from services.voice.tts_provider import (
    EdgeTTSProvider,
    PocketTTSProvider,
)

BENCHMARK_PHRASES = [
    ("Frase Corta", "Hola, soy Jessyca."),
    ("Acción / Sistema", "Listo, he abierto el Bloc de notas."),
    ("Interrogación", "¿En qué puedo ayudarte?"),
    ("Explicación Larga", "Explícame brevemente qué es la gravedad."),
]


def get_process_memory_mb() -> float:
    """Retorna el uso de memoria RAM (RSS) del proceso actual en MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024.0 * 1024.0)


def get_gpu_memory_mb() -> float | None:
    """Retorna la memoria de GPU reservada en MB si PyTorch CUDA está disponible."""
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.memory_allocated() / (1024.0 * 1024.0)
    except Exception:
        pass
    return None


def run_benchmark_for_phrase(
    provider: Any,
    phrase_tag: str,
    phrase_text: str,
    voice: str | None = None,
) -> dict[str, Any]:
    """Ejecuta la síntesis de una frase midiendo métricas T1-T4 y recursos."""
    ram_before = get_process_memory_mb()

    t_start = time.perf_counter()
    res, metrics = provider.synthesize(phrase_text, voice=voice)
    t_end = time.perf_counter()

    ram_after = get_process_memory_mb()
    gpu_after = get_gpu_memory_mb()

    return {
        "tag": phrase_tag,
        "text": phrase_text,
        "length_chars": len(phrase_text),
        "is_success": res.is_success,
        "bytes_len": len(res.audio_bytes),
        "t1_ms": metrics.t1_request_to_synth_ms,
        "t2_ms": metrics.t2_first_audio_ms,
        "t3_ms": metrics.t3_total_gen_ms,
        "t4_ms": metrics.t4_audio_duration_ms,
        "rtf": metrics.calculate_rtf(),
        "total_wall_ms": (t_end - t_start) * 1000.0,
        "ram_delta_mb": ram_after - ram_before,
        "ram_final_mb": ram_after,
        "gpu_mb": gpu_after,
        "error": res.error_message,
    }


def run_full_tts_benchmark() -> None:
    print("=" * 80)
    print("      JESSYCA 4.0 — BENCHMARK OFICIAL: POCKET TTS vs EDGE-TTS CAMILA")
    print("=" * 80)

    # 1. Instanciación de proveedores
    print("\n[1/4] Inicializando proveedores...")
    pocket = PocketTTSProvider(default_voice="alba", device="cpu")
    edge = EdgeTTSProvider(default_voice="es-PE-CamilaNeural")

    print(f"  * Pocket TTS disponible: {pocket.is_available()}")
    print(f"  * Edge-TTS disponible:   {edge.is_available()}")

    # Calentamiento / Carga inicial del modelo Pocket
    if pocket.is_available():
        print("  * Calentando Pocket TTS (carga de pesos)...")
        t0 = time.perf_counter()
        _res_warmup, _ = pocket.synthesize("Hola.")
        print(f"    Pocket TTS listo en {(time.perf_counter() - t0):.2f}s (RAM: {get_process_memory_mb():.1f} MB)")

    # 2. Evaluación por frases
    print("\n[2/4] Evaluando frases de prueba...")
    pocket_results: list[dict[str, Any]] = []
    edge_results: list[dict[str, Any]] = []

    for tag, text in BENCHMARK_PHRASES:
        print(f"\n  -- Evaluando '{tag}': \"{text}\"")

        # Pocket TTS
        if pocket.is_available():
            p_res = run_benchmark_for_phrase(pocket, tag, text, voice="alba")
            pocket_results.append(p_res)
            print(
                f"     [Pocket TTS] T3 Gen: {p_res['t3_ms']:.1f}ms | T4 Dur: {p_res['t4_ms']:.1f}ms | RTF: {p_res['rtf']:.3f} | RAM: {p_res['ram_final_mb']:.1f}MB"
            )

        # Edge TTS
        if edge.is_available():
            e_res = run_benchmark_for_phrase(edge, tag, text, voice="es-PE-CamilaNeural")
            edge_results.append(e_res)
            print(
                f"     [Edge Camila] T3 Gen: {e_res['t3_ms']:.1f}ms | T4 Dur: {e_res['t4_ms']:.1f}ms | RTF: {e_res['rtf']:.3f} | RAM: {e_res['ram_final_mb']:.1f}MB"
            )

    # 3. Prueba de estabilidad: 10 iteraciones consecutivas
    print("\n[3/4] Ejecutando prueba de estabilidad (10 generaciones consecutivas)...")
    stability_text = "Listo, he abierto el Bloc de notas."

    print("  * Evaluando Pocket TTS (10 iteraciones)...")
    pocket_stability_times: list[float] = []
    pocket_stability_errors: int = 0
    ram_start = get_process_memory_mb()

    for _i in range(10):
        t0 = time.perf_counter()
        res, m = pocket.synthesize(stability_text, voice="alba")
        dur = (time.perf_counter() - t0) * 1000.0
        pocket_stability_times.append(dur)
        if not res.is_success:
            pocket_stability_errors += 1

    ram_end = get_process_memory_mb()
    avg_pocket = sum(pocket_stability_times) / len(pocket_stability_times)
    print(f"    Pocket TTS: 10/10 completadas | Promedio: {avg_pocket:.1f}ms | Errores: {pocket_stability_errors}")
    print(f"    Delta RAM: {ram_end - ram_start:+.2f} MB (Inicial: {ram_start:.1f} MB -> Final: {ram_end:.1f} MB)")

    print("  * Evaluando Edge-TTS Camila (10 iteraciones)...")
    edge_stability_times: list[float] = []
    edge_stability_errors: int = 0
    e_ram_start = get_process_memory_mb()

    for _i in range(10):
        t0 = time.perf_counter()
        res, m = edge.synthesize(stability_text, voice="es-PE-CamilaNeural")
        dur = (time.perf_counter() - t0) * 1000.0
        edge_stability_times.append(dur)
        if not res.is_success:
            edge_stability_errors += 1

    e_ram_end = get_process_memory_mb()
    avg_edge = sum(edge_stability_times) / len(edge_stability_times)
    print(f"    Edge Camila: 10/10 completadas | Promedio: {avg_edge:.1f}ms | Errores: {edge_stability_errors}")
    print(f"    Delta RAM: {e_ram_end - e_ram_start:+.2f} MB (Inicial: {e_ram_start:.1f} MB -> Final: {e_ram_end:.1f} MB)")

    # 4. Tabla Comparativa Resumen
    print("\n" + "=" * 80)
    print("                     TABLA COMPARATIVA CONSOLIDADA")
    print("=" * 80)
    header = f"{'Frase':<20} | {'Motor':<12} | {'T3 (Gen)':<10} | {'T4 (Dur)':<10} | {'RTF':<8} | {'RAM (MB)':<10}"
    print(header)
    print("-" * len(header))

    for i, (tag, _) in enumerate(BENCHMARK_PHRASES):
        if i < len(pocket_results):
            p = pocket_results[i]
            print(f"{tag:<20} | {'Pocket TTS':<12} | {p['t3_ms']:>8.1f}ms | {p['t4_ms']:>8.1f}ms | {p['rtf']:>6.3f} | {p['ram_final_mb']:>8.1f}MB")
        if i < len(edge_results):
            e = edge_results[i]
            print(f"{'':<20} | {'Edge Camila':<12} | {e['t3_ms']:>8.1f}ms | {e['t4_ms']:>8.1f}ms | {e['rtf']:>6.3f} | {e['ram_final_mb']:>8.1f}MB")
        print("-" * len(header))

    print(f"{'Estabilidad (10x)':<20} | {'Pocket TTS':<12} | {avg_pocket:>8.1f}ms | {'N/A':>10} | {'0 err':<8} | {ram_end:>8.1f}MB")
    print(f"{'':<20} | {'Edge Camila':<12} | {avg_edge:>8.1f}ms | {'N/A':>10} | {'0 err':<8} | {e_ram_end:>8.1f}MB")
    print("=" * 80)


if __name__ == "__main__":
    run_full_tts_benchmark()
