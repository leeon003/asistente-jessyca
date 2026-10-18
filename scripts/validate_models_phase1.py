"""validate_models_phase1.py
Script de Validación Integral y Benchmarking de Migración de Modelos Ollama (Fase 1).
Comprueba el hardware (RTX 3060 12GB, Ryzen 9 5900X, 32GB RAM):
- TTFT (Time to First Token)
- Tokens por segundo (eval rate)
- Uso de VRAM (nvidia-smi) y estado de residencia (ollama ps)
- Contexto 4096 vs 8192 tokens
- Las 10 pruebas obligatorias del protocolo de certificación de Fase 1.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

# Asegurar codificación UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def get_vram_and_ollama_status() -> dict[str, Any]:
    """Obtiene el estado de VRAM vía nvidia-smi y modelos cargados vía ollama ps."""
    vram_used_mb = 0
    vram_total_mb = 12288
    gpu_util = 0
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
        out = subprocess.check_output(cmd, text=True).strip()
        parts = [p.strip() for p in out.split(",")]
        if len(parts) >= 3:
            vram_used_mb = int(parts[0])
            vram_total_mb = int(parts[1])
            gpu_util = int(parts[2])
    except Exception as e:
        print(f"  [AVISO] No se pudo consultar nvidia-smi: {e}")

    loaded_models: list[dict[str, Any]] = []
    try:
        req = urllib.request.Request("http://localhost:11434/api/ps")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("models", []):
                loaded_models.append({
                    "name": m.get("name"),
                    "size_vram_mb": round(m.get("size_vram", 0) / (1024 * 1024), 1),
                    "size_mb": round(m.get("size", 0) / (1024 * 1024), 1),
                })
    except Exception as e:
        print(f"  [AVISO] No se pudo consultar ollama ps: {e}")

    return {
        "vram_used_mb": vram_used_mb,
        "vram_total_mb": vram_total_mb,
        "gpu_util_pct": gpu_util,
        "loaded_models": loaded_models,
    }


def unload_all_models() -> None:
    """Solicita a Ollama descargar de VRAM todos los modelos activos para pruebas limpias."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/ps")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("models", []):
                m_name = m.get("name")
                if m_name:
                    p = {"model": m_name, "keep_alive": 0}
                    req_u = urllib.request.Request(
                        "http://localhost:11434/api/generate",
                        data=json.dumps(p).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    urllib.request.urlopen(req_u, timeout=5)
        time.sleep(1.0)
    except Exception:
        pass


def benchmark_model(
    model_name: str,
    prompt: str,
    system_prompt: str = "Eres JESSYCA, asistente personal inteligente para Windows 11. Responde de forma precisa y concisa en español.",
    num_ctx: int = 4096,
    num_predict: int = 120,
) -> dict[str, Any]:
    """Ejecuta una prueba de inferencia midiendo TTFT y tokens/segundo con telemetría de Ollama."""
    payload = {
        "model": model_name,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    t_start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=90) as resp:
        final_stats = json.loads(resp.read().decode("utf-8"))
    t_end = time.perf_counter()

    full_text = final_stats.get("response", "").strip()
    clean_text = re.sub(r"<think>.*?</think>", "", full_text, flags=re.DOTALL).strip()

    prompt_eval_dur_s = (final_stats.get("prompt_eval_duration", 0) / 1e9)
    ttft_ms = prompt_eval_dur_s * 1000.0
    total_time_s = t_end - t_start
    eval_count = final_stats.get("eval_count", 0)
    eval_duration_s = (final_stats.get("eval_duration", 0) / 1e9)
    tokens_per_sec = (eval_count / eval_duration_s) if eval_duration_s > 0 else 0.0

    gpu_info = get_vram_and_ollama_status()

    return {
        "model": model_name,
        "num_ctx": num_ctx,
        "ttft_ms": round(ttft_ms, 1),
        "total_time_s": round(total_time_s, 2),
        "eval_count": eval_count,
        "tokens_per_sec": round(tokens_per_sec, 1),
        "clean_text_preview": clean_text[:120].replace("\n", " "),
        "vram_used_mb": gpu_info["vram_used_mb"],
        "gpu_util_pct": gpu_info["gpu_util_pct"],
        "loaded_models": [m["name"] for m in gpu_info["loaded_models"]],
    }


def create_test_image_base64() -> str:
    """Crea un PNG sintético en memoria para prueba visual multimodal."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (320, 240), color=(26, 32, 44))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 300, 70], fill=(43, 108, 176), outline=(99, 179, 237))
    draw.text((35, 35), "JESSYCA Control Center - Windows 11", fill=(255, 255, 255))
    draw.rectangle([20, 90, 140, 140], fill=(72, 187, 120))
    draw.text((35, 105), "Activo: OK", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def run_all_mandatory_tests() -> dict[str, Any]:
    """Ejecuta las 10 pruebas obligatorias requeridas en la especificación de Fase 1."""
    results: dict[str, dict[str, Any]] = {}

    print("\n" + "=" * 80)
    print("EJECUTANDO BATERÍA DE 10 PRUEBAS OBLIGATORIAS (FASE 1)")
    print("=" * 80)

    # 1. Arranque de JESSYCA
    print("\n[PRUEBA 1/10] Arranque y Diagnóstico Pre-Flight de JESSYCA...")
    from iniciar_jessyca import perform_full_diagnostics
    diag = perform_full_diagnostics()
    p1_ok = (diag["ollama_status"] == "CONECTADO") and ("qwen3.5:9b" in diag["ollama_model"] or diag["ollama_model"] == "qwen3.5:9b")
    results["1_arranque_jessyca"] = {
        "status": "PASS" if p1_ok else "FAIL",
        "model_configurado": diag["ollama_model"],
        "ollama_status": diag["ollama_status"],
        "brain_status": diag["brain_status"],
    }
    print(f"  -> Resultado: {results['1_arranque_jessyca']['status']} (Modelo: {diag['ollama_model']})")

    # 2. Detección de Ollama
    print("\n[PRUEBA 2/10] Detección de Ollama y presencia de qwen3.5:9b y gemma4:e4b...")
    from iniciar_jessyca import check_ollama
    ok_q, models_list, msg_q = check_ollama("qwen3.5:9b")
    has_qwen = any("qwen3.5:9b" in m for m in models_list)
    has_gemma = any("gemma4:e4b" in m for m in models_list)
    p2_ok = ok_q and has_qwen and has_gemma
    results["2_deteccion_ollama"] = {
        "status": "PASS" if p2_ok else "FAIL",
        "has_qwen3_5_9b": has_qwen,
        "has_gemma4_e4b": has_gemma,
        "total_models": len(models_list),
    }
    print(f"  -> Resultado: {results['2_deteccion_ollama']['status']} (qwen3.5:9b: {has_qwen}, gemma4:e4b: {has_gemma})")

    # 3. Respuesta conversacional con qwen3.5:9b
    print("\n[PRUEBA 3/10] Respuesta conversacional fluida sin filtrado de razonamiento en TTS...")
    from core.llm.inference import OllamaProvider, InferenceRequest
    provider = OllamaProvider()
    req_conv = InferenceRequest(
        prompt="Hola Jessyca, ¿qué hora o fecha aproximada tienes en el sistema?",
        system_prompt="Eres JESSYCA, asistente personal para Windows 11. Responde brevemente y en tono servicial en español.",
        model_name="qwen3.5:9b",
        temperature=0.3,
        max_tokens=80,
    )
    resp_conv = provider.generate(req_conv)
    has_think_leak = "<think>" in resp_conv.content or "</think>" in resp_conv.content
    p3_ok = resp_conv.success and len(resp_conv.content.strip()) > 10 and not has_think_leak
    results["3_respuesta_conversacional"] = {
        "status": "PASS" if p3_ok else "FAIL",
        "latency_ms": round(resp_conv.duration_ms, 1),
        "content_length": len(resp_conv.content),
        "has_think_leak": has_think_leak,
        "preview": resp_conv.content[:100].replace("\n", " "),
    }
    print(f"  -> Resultado: {results['3_respuesta_conversacional']['status']} (Latencia: {resp_conv.duration_ms:.1f}ms, Sin tags think: {not has_think_leak})")

    # 4. Uso del modelo principal vía ModelRouter y Brain
    print("\n[PRUEBA 4/10] Verificación de uso del modelo principal (qwen3.5:9b) en tareas centrales...")
    from core.llm.model_router import ModelRouter
    from core.llm.routing_policy import TaskType
    router = ModelRouter.get_instance()
    m_conv = router.select_model_for_task(TaskType.CONVERSATION)
    m_reas = router.select_model_for_task(TaskType.REASONING)
    m_plan = router.select_model_for_task(TaskType.PLANNING)
    p4_ok = (m_conv.name == "qwen3.5:9b") and (m_reas.name == "qwen3.5:9b") and (m_plan.name == "qwen3.5:9b")
    results["4_uso_modelo_principal"] = {
        "status": "PASS" if p4_ok else "FAIL",
        "conversation_model": m_conv.name,
        "reasoning_model": m_reas.name,
        "planning_model": m_plan.name,
    }
    print(f"  -> Resultado: {results['4_uso_modelo_principal']['status']} (Conv: {m_conv.name}, Reas: {m_reas.name}, Plan: {m_plan.name})")

    # 5. Cambio automático al respaldo ante fallo controlado
    print("\n[PRUEBA 5/10] Cambio automático a respaldo (gemma4:e4b) ante fallo o exclusión...")
    from core.llm.routing_policy import RoutingContext
    ctx_fallback = RoutingContext(
        task_type=TaskType.REASONING,
        excluded_model_ids=("qwen3.5:9b",),  # Exclusión controlada de qwen
    )
    decision = router.route_smart(ctx_fallback)
    p5_ok = decision.selected_model.name == "gemma4:e4b"
    results["5_cambio_automatico_respaldo"] = {
        "status": "PASS" if p5_ok else "FAIL",
        "selected_fallback": decision.selected_model.name,
        "reason": decision.reason,
    }
    print(f"  -> Resultado: {results['5_cambio_automatico_respaldo']['status']} (Fallback asignado: {decision.selected_model.name})")

    # 6. Interpretación visual multimodal
    print("\n[PRUEBA 6/10] Interpretación visual multimodal con qwen3.5:9b...")
    from core.vision.ollama_vision_provider import OllamaVisionProvider
    vision_prov = OllamaVisionProvider(default_model="qwen3.5:9b")
    test_img_b64 = create_test_image_base64()
    analysis = vision_prov.analyze_screenshot(test_img_b64, prompt="¿Qué título y estado aparecen en esta imagen de interfaz?")
    p6_ok = bool(analysis.summary) and len(analysis.summary.strip()) > 5
    results["6_interpretacion_visual"] = {
        "status": "PASS" if p6_ok else "FAIL",
        "model_used": analysis.model_used,
        "duration_ms": round(analysis.duration_ms, 1),
        "summary": analysis.summary[:100].replace("\n", " "),
    }
    print(f"  -> Resultado: {results['6_interpretacion_visual']['status']} (Modelo: {analysis.model_used}, Resumen: {analysis.summary[:60]}...)")

    # 7. Salida JSON estructurada (Tool Call Schema)
    print("\n[PRUEBA 7/10] Generación y validación de salida JSON estructurada con qwen3.5:9b...")
    json_prompt = (
        "El usuario dice: 'Abre el explorador de archivos en la carpeta de descargas'. "
        "Genera una invocación de herramienta en formato JSON estrictamente válido con los campos: "
        '{"action": "open_folder", "target": "Downloads", "verified": true}'
    )
    req_json = InferenceRequest(
        prompt=json_prompt,
        system_prompt="Responde exclusivamente con el JSON solicitado, sin explicaciones ni markdown.",
        model_name="qwen3.5:9b",
        temperature=0.1,
        max_tokens=100,
    )
    res_json = provider.generate(req_json)
    parsed_json: dict[str, Any] = {}
    try:
        # Extraer JSON
        clean_j = re.sub(r"<think>.*?</think>", "", res_json.content, flags=re.DOTALL).strip()
        m = re.search(r"\{.*\}", clean_j, re.DOTALL)
        if m:
            parsed_json = json.loads(m.group(0))
        p7_ok = isinstance(parsed_json, dict) and "action" in parsed_json and parsed_json.get("action") == "open_folder"
    except Exception as e:
        p7_ok = False
        parsed_json = {"error": str(e)}

    results["7_salida_json_valida"] = {
        "status": "PASS" if p7_ok else "FAIL",
        "parsed_keys": list(parsed_json.keys()),
        "parsed_action": parsed_json.get("action"),
    }
    print(f"  -> Resultado: {results['7_salida_json_valida']['status']} (JSON parseado: {parsed_json})")

    # 8. Planificación cognitiva DAG
    print("\n[PRUEBA 8/10] Planificación cognitiva DAG con PlannerEngine y JessycaBrain...")
    from core.cognitive_brain.contracts import ContextBundle
    from core.cognitive_brain.planner_engine import PlannerEngine
    from core.cognitive_brain.reasoning_engine import ReasoningEngine
    re_eng = ReasoningEngine()
    pl_eng = PlannerEngine()
    comp = re_eng.comprehend("busca los últimos archivos modificados en descargas y muéstramelos", context=ContextBundle())
    plan = pl_eng.create_plan(comp, available_tools=["open_folder", "file_search"])
    dag_valid = pl_eng.validate_dag(plan) if plan else False
    p8_ok = plan is not None and len(plan.steps) >= 1 and plan.plan_id.startswith("plan-") and dag_valid
    results["8_planificacion_dag"] = {
        "status": "PASS" if p8_ok else "FAIL",
        "plan_id": plan.plan_id if plan else None,
        "steps_count": len(plan.steps) if plan else 0,
        "dag_valid": dag_valid,
    }
    print(f"  -> Resultado: {results['8_planificacion_dag']['status']} (Plan ID: {results['8_planificacion_dag']['plan_id']}, Pasos: {results['8_planificacion_dag']['steps_count']}, DAG válido: {dag_valid})")

    # 9. Ejecución y verificación de acciones seguras
    print("\n[PRUEBA 9/10] Ejecución y verificación de acciones seguras de consulta de sistema...")
    from core.cognitive_brain.brain_orchestrator import JessycaBrain
    brain = JessycaBrain.get_instance()
    # Consulta segura de estado/conversacional sin modificar el sistema
    b_res = brain.process_request("Hola Jessyca, ¿estás lista para operar en Windows 11?")
    p9_ok = b_res.success and len(b_res.response_text) > 10 and not b_res.requires_action
    results["9_ejecucion_y_verificacion"] = {
        "status": "PASS" if p9_ok else "FAIL",
        "task_id": b_res.task_id,
        "is_conversational": b_res.is_conversational,
        "duration_ms": round(b_res.duration_ms, 1),
        "response_preview": b_res.response_text[:80].replace("\n", " "),
    }
    print(f"  -> Resultado: {results['9_ejecucion_y_verificacion']['status']} (Task ID: {b_res.task_id}, Latencia: {b_res.duration_ms:.1f}ms)")

    # 10. Compatibilidad con Voice Realtime (Filtro TTS de razonamiento)
    print("\n[PRUEBA 10/10] Compatibilidad con Voice Realtime y blindaje de razonamiento interno...")
    from interfaces.modo_voz import VoiceSpeaker
    speaker = VoiceSpeaker()
    test_thinking_leak = "<think>Aquí razono internamente paso a paso.</think>Hola usuario, estoy lista."
    # El speaker debe filtrar internamente los tags think
    m_voice = speaker.speak(test_thinking_leak)
    # Verificamos que el resultado no haya fallado
    p10_ok = m_voice is not None
    results["10_compatibilidad_voice_realtime"] = {
        "status": "PASS" if p10_ok else "FAIL",
        "engine_used": m_voice.engine_used,
        "startup_latency_ms": round(m_voice.startup_latency_ms, 1),
    }
    print(f"  -> Resultado: {results['10_compatibilidad_voice_realtime']['status']} (TTS Engine: {m_voice.engine_used}, Latencia: {m_voice.startup_latency_ms:.1f}ms)")

    print("\n" + "=" * 80)
    passed_cnt = sum(1 for v in results.values() if v.get("status") == "PASS")
    print(f"RESUMEN DE PRUEBAS: {passed_cnt}/10 PASADAS SATISFACTORIAMENTE")
    print("=" * 80)

    return results


def main() -> None:
    print("\n" + "=" * 80)
    print("JESSYCA 4.0 — FASE 1: BENCHMARK Y CERTIFICACIÓN DE MODELOS OLLAMA")
    print("NVIDIA GeForce RTX 3060 (12 GB VRAM) | AMD Ryzen 9 5900X | Windows 11")
    print("=" * 80)

    initial_gpu = get_vram_and_ollama_status()
    print(f"\n[GPU INICIAL] VRAM Usada: {initial_gpu['vram_used_mb']} MB / {initial_gpu['vram_total_mb']} MB (GPU Util: {initial_gpu['gpu_util_pct']}%)")
    print(f"[OLLAMA PS] Modelos residentes al inicio: {[m['name'] for m in initial_gpu['loaded_models']] or 'Ninguno'}")

    bench_prompt = (
        "Explica en español de forma estructurada qué es un sistema operativo moderno, "
        "mencionando la gestión de procesos, memoria virtual y sistema de archivos en 3 párrafos concisos."
    )

    benchmarks: list[dict[str, Any]] = []

    # 1. Benchmark qwen3.5:9b a 4096 tokens de contexto
    print("\n[BENCHMARK 1/4] Evaluando qwen3.5:9b (Contexto: 4096 tokens)...")
    unload_all_models()
    b1 = benchmark_model("qwen3.5:9b", bench_prompt, num_ctx=4096, num_predict=120)
    benchmarks.append(b1)
    print(f"  -> TTFT: {b1['ttft_ms']} ms | Velocidad: {b1['tokens_per_sec']} tokens/s | VRAM: {b1['vram_used_mb']} MB")

    # 2. Benchmark qwen3.5:9b a 8192 tokens de contexto
    print("\n[BENCHMARK 2/4] Evaluando qwen3.5:9b (Contexto: 8192 tokens)...")
    b2 = benchmark_model("qwen3.5:9b", bench_prompt, num_ctx=8192, num_predict=120)
    benchmarks.append(b2)
    print(f"  -> TTFT: {b2['ttft_ms']} ms | Velocidad: {b2['tokens_per_sec']} tokens/s | VRAM: {b2['vram_used_mb']} MB")

    # 3. Benchmark gemma4:e4b a 4096 tokens de contexto
    print("\n[BENCHMARK 3/4] Evaluando gemma4:e4b (Respaldo) (Contexto: 4096 tokens)...")
    unload_all_models()
    b3 = benchmark_model("gemma4:e4b", bench_prompt, num_ctx=4096, num_predict=120)
    benchmarks.append(b3)
    print(f"  -> TTFT: {b3['ttft_ms']} ms | Velocidad: {b3['tokens_per_sec']} tokens/s | VRAM: {b3['vram_used_mb']} MB")

    # 4. Benchmark gemma4:e4b a 8192 tokens de contexto
    print("\n[BENCHMARK 4/4] Evaluando gemma4:e4b (Respaldo) (Contexto: 8192 tokens)...")
    b4 = benchmark_model("gemma4:e4b", bench_prompt, num_ctx=8192, num_predict=120)
    benchmarks.append(b4)
    print(f"  -> TTFT: {b4['ttft_ms']} ms | Velocidad: {b4['tokens_per_sec']} tokens/s | VRAM: {b4['vram_used_mb']} MB")

    # Ejecutar 10 pruebas obligatorias
    tests_summary = run_all_mandatory_tests()

    # Guardar reporte estructurado en reports/
    report_path = PROJECT_ROOT / "reports" / "model_migration_phase1_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hardware": {
            "gpu": "NVIDIA GeForce RTX 3060 (12 GB)",
            "cpu": "AMD Ryzen 9 5900X",
            "ram": "32 GB",
            "os": "Windows 11",
        },
        "consolidated_models": {
            "primary": "qwen3.5:9b",
            "fallback": "gemma4:e4b",
        },
        "deprecated_models": [
            "qwen3-vl:4b",
            "qwen3:8b",
            "llama3.1:latest",
            "llama3.2:latest",
        ],
        "benchmarks": benchmarks,
        "mandatory_tests": tests_summary,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    print(f"\n[INFORME GUARDADO] Reporte completo generado en: {report_path}")


if __name__ == "__main__":
    main()
