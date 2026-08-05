"""
Script de prueba manual para el Cerebro (brain.py).
Llama a Ollama REAL en localhost:11434 con la orden "abre el bloc de notas".
Ejecutar con:
    venv\Scripts\python.exe test_brain_manual.py
"""
import json
from skills import SKILLS_DISPONIBLES
from core.brain import procesar_orden

ORDEN = "abre el bloc de notas"

print(f"\n{'='*55}")
print(f"  Test manual del Cerebro (Ollama real)")
print(f"{'='*55}")
print(f"  Orden enviada: \"{ORDEN}\"")
print(f"{'='*55}\n")

resultado = procesar_orden(ORDEN, SKILLS_DISPONIBLES)

print("  Resultado completo:")
print(json.dumps(resultado, ensure_ascii=False, indent=2))

print(f"\n  Respuesta hablada : {resultado.get('respuesta_hablada')}")
print(f"  Skill detectada   : {resultado.get('skill')}")
print(f"  Parámetros        : {resultado.get('parametros')}")
if resultado.get("error"):
    print(f"\n  ⚠ Error           : {resultado.get('error')}")
print()
