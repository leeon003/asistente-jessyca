import json
import time
import urllib.request
import os

OLLAMA_URL = "http://localhost:11434/api/generate"

PROMPTS = [
    {
        "id": "conversacion_simple",
        "category": "Conversación y Español",
        "prompt": "¿Quién fue Albert Einstein? Responde en una sola oración concisa en español."
    },
    {
        "id": "razonamiento_matematico",
        "category": "Razonamiento y Lógica",
        "prompt": "Si tengo 3 manzanas y compro 2 bolsas con 4 manzanas cada una, ¿cuántas manzanas tengo en total? Explica brevemente el cálculo paso a paso."
    },
    {
        "id": "plan_estructurado_json",
        "category": "Salida Estructurada JSON",
        "prompt": 'Responde ÚNICAMENTE con un objeto JSON válido con este formato: {"plan_name": "sumar_numeros", "steps": [{"action": "abrir_app", "target": "calc"}, {"action": "escribir", "texto": "5+3"}]}. El plan es: abrir la calculadora y escribir 10+20.'
    },
    {
        "id": "instruccion_compuesta_tools",
        "category": "Instrucción Compuesta y Herramientas",
        "prompt": 'Para la orden: "Investiga sobre el telescopio James Webb y guarda un resumen en notas.txt", enumera en 2 líneas las acciones requeridas y qué herramientas usarías (navegador, bloc de notas, etc.).'
    }
]

MODELS_TO_TEST = ["llama3.2:latest", "qwen3:8b", "qwen3-vl:4b"]

def query_ollama(model: str, prompt: str) -> dict:
    req_data = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 256
        }
    }
    t0 = time.perf_counter()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(req_data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            eval_count = data.get("eval_count", 0)
            eval_duration_ns = data.get("eval_duration", 1)
            tps = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns > 0 else 0.0
            return {
                "success": True,
                "latency_ms": round(elapsed_ms, 2),
                "response": data.get("response", "").strip(),
                "eval_count": eval_count,
                "tokens_per_second": round(tps, 1)
            }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "success": False,
            "latency_ms": round(elapsed_ms, 2),
            "error": str(e)
        }

def run_benchmarks():
    results = {}
    print("=== INICIANDO BENCHMARK REAL DE MODELOS OLLAMA ===")
    for model in MODELS_TO_TEST:
        print(f"\n--- Evaluando Modelo: {model} ---")
        results[model] = []
        for p in PROMPTS:
            print(f"  * Ejecutando: [{p['category']}] ... ", end="", flush=True)
            res = query_ollama(model, p["prompt"])
            if res["success"]:
                print(f"OK ({res['latency_ms']} ms | {res['tokens_per_second']} t/s)")
            else:
                print(f"ERROR: {res.get('error')}")
            results[model].append({
                "prompt_id": p["id"],
                "category": p["category"],
                "result": res
            })

    output_path = "benchmarks/ollama_model_comparison_results.json"
    os.makedirs("benchmarks", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en: {output_path}")

if __name__ == "__main__":
    run_benchmarks()
