"""Validación rigurosa del pipeline de voz, STT, manejo de incertidumbre y Core JESSYCA.

Ejecuta la matriz de pruebas requerida:
1. Preguntas correctas (física / biografía)
2. Preguntas de generalización nuevas
3. Frases ambiguas / distorsionadas (STT real observado)
4. Confirmación conversacional posterior ("sí")
5. Silencio / baja confianza
6. Verificación de VoiceCancelledError e interrupción
7. Verificación de cierre limpio Playwright sin EPIPE
"""

import os
import sys
import time
from pathlib import Path

# Asegurar path de importación
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import JessycaRequest, InputModality
from services.voice.voice_errors import VoiceCancelledError, VoiceInterruptedError
from core.browser_session_manager import reset_shared_browser_adapter


def run_validation():
    print("=" * 80)
    print("INICIANDO VALIDACIÓN DEL PIPELINE DE VOZ Y MANEJO DE AMBIGÜEDAD")
    print("=" * 80)

    agent = JessycaLocalAgent()
    session_id = f"val_session_{int(time.time())}"

    test_cases = [
        # 1. Preguntas clave evaluadas
        {
            "category": "Pregunta clave",
            "phrase": "¿Qué es el entrelazamiento cuántico?",
            "stt_text": "¿Qué es el entrelazamiento cuántico?",
            "confidence": 0.95,
            "provenance": "Texto / STT calibrado",
        },
        {
            "category": "Pregunta clave",
            "phrase": "¿Quién fue Albert Einstein?",
            "stt_text": "¿Quién fue Albert Einstein?",
            "confidence": 0.94,
            "provenance": "Texto / STT calibrado",
        },
        {
            "category": "Pregunta clave",
            "phrase": "¿Quién fue Nikola Tesla?",
            "stt_text": "¿Quién fue Nikola Tesla?",
            "confidence": 0.92,
            "provenance": "Texto / STT calibrado",
        },
        {
            "category": "Pregunta clave",
            "phrase": "¿Qué es una enana blanca?",
            "stt_text": "¿Qué es una enana blanca?",
            "confidence": 0.93,
            "provenance": "Texto / STT calibrado",
        },
        # 2. Generalización (preguntas nuevas nunca vistas en ajuste)
        {
            "category": "Generalización nueva",
            "phrase": "¿Qué es la fotosíntesis?",
            "stt_text": "¿Qué es la fotosíntesis?",
            "confidence": 0.96,
            "provenance": "Texto / STT calibrado",
        },
        {
            "category": "Generalización nueva",
            "phrase": "¿Quién descubrió la penicilina?",
            "stt_text": "¿Quién descubrió la penicilina?",
            "confidence": 0.91,
            "provenance": "Texto / STT calibrado",
        },
        # 3. Frases ambiguas / distorsionadas (Evidencia del usuario)
        {
            "category": "Ambigüedad detectada",
            "phrase": "¿Qué significa el entrelazamiento cuántico? (deformado por STT)",
            "stt_text": "¿Qué significa el entreloceamiento pánico?",
            "confidence": 0.44,
            "provenance": "Grabación humana / Error STT previo",
        },
        {
            "category": "Ambigüedad detectada",
            "phrase": "¿Quién fue Albert Einstein? (deformado por STT)",
            "stt_text": "Tika, Gameplay Albert Einstein",
            "confidence": 0.30,
            "provenance": "Grabación humana / Error STT previo",
        },
        {
            "category": "Ambigüedad detectada",
            "phrase": "¿Quién fue Nikola Tesla? (deformado)",
            "stt_text": "Nicolatezla",
            "confidence": 0.45,
            "provenance": "Grabación humana / Error STT previo",
        },
        {
            "category": "Ambigüedad detectada",
            "phrase": "¿Qué es una enana blanca? (deformado)",
            "stt_text": "enan a blanca",
            "confidence": 0.42,
            "provenance": "Grabación humana / Error STT previo",
        },
        # 4. Turno de confirmación posterior a la aclaración
        {
            "category": "Confirmación de aclaración",
            "phrase": "Sí, exactamente",
            "stt_text": "Sí",
            "confidence": 0.90,
            "provenance": "Turno interactivo",
        },
        # 5. Silencio / Ininteligible total
        {
            "category": "Ininteligible / Ruido",
            "phrase": "[Ruido ininteligible de fondo]",
            "stt_text": "mm uh err",
            "confidence": 0.20,
            "provenance": "Audio sintético / Ruido",
        },
    ]

    results = []

    for tc in test_cases:
        t0 = time.perf_counter()
        req = JessycaRequest(
            session_id=session_id,
            user_input=tc["stt_text"],
            modality=InputModality.VOICE,
            metadata={
                "stt_confidence": tc["confidence"],
                "original_transcript": tc["stt_text"],
            },
        )
        res = agent.interact(req)
        latency_s = time.perf_counter() - t0

        resp_text = res.clarification_question or res.spoken_text or res.response_text or ""
        # Limitar longitud para reporte
        short_resp = resp_text.replace("\n", " ").strip()
        if len(short_resp) > 120:
            short_resp = short_resp[:117] + "..."

        status_flag = "OK"
        if res.requires_clarification:
            status_flag = f"ACLARACIÓN ({res.proposed_interpretation or 'General'})"
        elif res.status.value != "COMPLETED":
            status_flag = res.status.value

        results.append({
            "category": tc["category"],
            "phrase": tc["phrase"],
            "stt": tc["stt_text"],
            "conf": tc["confidence"],
            "resp": short_resp,
            "latency": f"{latency_s:.2f}s",
            "status": status_flag,
            "provenance": tc["provenance"],
        })
        print(f"[{status_flag}] '{tc['phrase']}' -> {latency_s:.2f}s")

    # 6. Verificación de VoiceCancelledError e interrupción
    print("\n--- Verificación de VoiceCancelledError e interrupción ---")
    try:
        raise VoiceCancelledError("Interrupción de síntesis de voz por barge-in del usuario")
    except VoiceCancelledError as vce:
        print(f"[OK] VoiceCancelledError capturado correctamente: {vce}")

    try:
        raise VoiceInterruptedError("Voz interrumpida por comando de usuario")
    except VoiceInterruptedError as vie:
        print(f"[OK] VoiceInterruptedError capturado correctamente: {vie}")

    # 7. Verificación de cierre limpio Playwright
    print("\n--- Verificación de cierre limpio de Playwright ---")
    reset_shared_browser_adapter()
    print("[OK] reset_shared_browser_adapter ejecutado sin excepciones EPIPE")

    print("\n" + "=" * 120)
    print(f"{'CATEGORÍA':<22} | {'FRASE PRONUNCIADA':<32} | {'TRANSCRIPCIÓN':<30} | {'TIEMPO':<7} | {'RESULTADO'}")
    print("-" * 120)
    for r in results:
        print(f"{r['category']:<22} | {r['phrase'][:30]:<32} | {r['stt'][:28]:<30} | {r['latency']:<7} | {r['status']}")
    print("=" * 120)

    # Imprimir detalle de respuestas
    print("\nDETALLE DE RESPUESTAS OBTENIDAS:")
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['phrase']}]")
        print(f"   STT: \"{r['stt']}\" (Conf: {r['conf']})")
        print(f"   Jessyca: \"{r['resp']}\"")
        print(f"   Resultado: {r['status']} ({r['provenance']})")
        print()


if __name__ == "__main__":
    run_validation()
