"""Benchmark de segmentación y detección de turnos para JESSYCA VOICE REALTIME (Fase 1).

Evalúa empíricamente diferentes umbrales de silencio de fin de turno:
- Frases cortas directas
- Frases largas complejas
- Pausas naturales intra-oración (300ms, 500ms, 700ms, 900ms)
Mide:
- Tasa de error de segmentación (corte prematuro antes de que el usuario termine)
- Latencia de detección de fin de turno (EOS latency)
"""
import math
import struct
import time
from typing import Any
from services.voice.audio_capture import CalibratedVoiceCaptureEngine
from services.voice.vad_service import get_vad_service


def load_real_speech_bytes() -> bytes:
    """Carga el audio real de muestra 'sample_es_hola_jessica.wav' y retorna samples PCM 16kHz."""
    import wave
    from pathlib import Path
    
    p = Path("tests/voice/fixtures/sample_es_hola_jessica.wav")
    if not p.exists():
        p = Path(__file__).parent / "fixtures" / "sample_es_hola_jessica.wav"
        
    with wave.open(str(p), "rb") as wf:
        return wf.readframes(wf.getnframes())


def generate_speech_audio(
    segments: list[tuple[str, float]], sample_rate: int = 16000
) -> list[bytes]:
    """Genera chunks PCM a partir de audio real para voz y silencio digital para pausas."""
    real_speech = load_real_speech_bytes()
    chunk_ms = 50
    chunk_bytes_len = int(sample_rate * 2 * (chunk_ms / 1000.0))
    silence_chunk = b"\x00" * chunk_bytes_len
    all_chunks: list[bytes] = []

    speech_offset = 0
    for seg_type, duration_sec in segments:
        num_chunks = int(duration_sec / (chunk_ms / 1000.0))
        for _ in range(num_chunks):
            if seg_type == "speech":
                if speech_offset + chunk_bytes_len > len(real_speech):
                    speech_offset = 0
                chunk = real_speech[speech_offset : speech_offset + chunk_bytes_len]
                speech_offset += chunk_bytes_len
                all_chunks.append(chunk)
            else:
                all_chunks.append(silence_chunk)

    return all_chunks


def run_benchmark_for_config(
    backend: str,
    silence_short: float,
    silence_extended: float,
    test_cases: dict[str, list[tuple[str, float]]],
) -> dict[str, Any]:
    """Ejecuta los casos de prueba para una configuración específica de VAD y umbrales."""
    vad = get_vad_service(
        backend=backend,
        silence_end_short_seconds=silence_short,
        silence_end_extended_seconds=silence_extended,
        adaptive_eos_enabled=True,
    )

    engine = CalibratedVoiceCaptureEngine(
        sample_rate=16000,
        channels=1,
        pre_roll_ms=200,
        post_roll_ms=250,
        vad_service=vad,
        adaptive_eos_enabled=True,
    )

    results: dict[str, Any] = {}

    for case_name, segments in test_cases.items():
        # Calcular duración esperada total del habla (hasta el final de la última palabra)
        last_speech_idx = max(i for i, (t, _) in enumerate(segments) if t == "speech")
        expected_speech_end_sec = sum(dur for i, (_, dur) in enumerate(segments[: last_speech_idx + 1]))

        audio_chunks = generate_speech_audio(segments)
        vad.reset()

        try:
            audio_bytes, meta = engine.evaluate_adaptive_stream(
                chunk_stream=audio_chunks,
                sample_rate=16000,
                sample_width=2,
                timeout=5.0,
            )
            captured_audio_sec = len(audio_bytes) / (16000 * 2)

            # Si el audio capturado es menor que la última palabra esperada menos tolerancia
            # se considera corte prematuro (segmentation error)
            is_premature_cut = captured_audio_sec < (expected_speech_end_sec - 0.15)
            eos_latency = meta.get("silence_sec", 0.0)

            results[case_name] = {
                "premature_cut": is_premature_cut,
                "captured_audio_sec": round(captured_audio_sec, 2),
                "expected_speech_sec": round(expected_speech_end_sec, 2),
                "eos_silence_latency_sec": round(eos_latency, 2),
                "total_speech_detected_sec": round(meta.get("total_speech_sec", 0.0), 2),
                "end_reason": meta.get("end_reason"),
            }
        except Exception as e:
            results[case_name] = {
                "error": str(e),
                "premature_cut": True,
            }

    return results


def main() -> None:
    test_cases = {
        # 1. Comando corto directo: 0.8s voz + 2.0s silencio final
        "short_command": [
            ("speech", 0.8),
            ("silence", 2.0),
        ],
        # 2. Pregunta larga fluida: 4.5s voz continua + 2.0s silencio final
        "long_fluent": [
            ("speech", 4.5),
            ("silence", 2.0),
        ],
        # 3. Frase con pausa reflexiva breve (350ms): 1.2s voz + 0.35s pausa + 1.5s voz + 2.0s silencio
        "pause_350ms": [
            ("speech", 1.2),
            ("silence", 0.35),
            ("speech", 1.5),
            ("silence", 2.0),
        ],
        # 4. Frase con pausa natural media (550ms): 1.5s voz + 0.55s pausa + 1.8s voz + 2.0s silencio
        "pause_550ms": [
            ("speech", 1.5),
            ("silence", 0.55),
            ("speech", 1.8),
            ("silence", 2.0),
        ],
        # 5. Frase con pausa natural reflexiva larga (750ms): 2.0s voz + 0.75s pausa + 2.0s voz + 2.0s silencio
        "pause_750ms": [
            ("speech", 2.0),
            ("silence", 0.75),
            ("speech", 2.0),
            ("silence", 2.0),
        ],
    }

    test_thresholds = [
        {"name": "Ultra-agresivo (400ms / 400ms)", "short": 0.40, "ext": 0.40},
        {"name": "Agresivo (500ms / 650ms)", "short": 0.50, "ext": 0.65},
        {"name": "Balanceado adaptativo (600ms / 850ms)", "short": 0.60, "ext": 0.85},
        {"name": "Conservador previo (1000ms / 1350ms)", "short": 1.00, "ext": 1.35},
    ]

    for backend in ["energy", "silero"]:
        print(f"\n{'='*70}\nEVALUACIÓN DE DETECCIÓN DE TURNOS — BACKEND: {backend.upper()}\n{'='*70}")
        for th in test_thresholds:
            res = run_benchmark_for_config(
                backend=backend,
                silence_short=th["short"],
                silence_extended=th["ext"],
                test_cases=test_cases,
            )
            premature_cuts = sum(1 for v in res.values() if v.get("premature_cut"))
            total_cases = len(test_cases)
            error_rate = (premature_cuts / total_cases) * 100.0
            avg_short_latency = res["short_command"].get("eos_silence_latency_sec", 0.0)
            avg_long_latency = res["long_fluent"].get("eos_silence_latency_sec", 0.0)

            print(f"\nConfiguración: {th['name']}")
            print(f"  Short EOS: {th['short']}s | Extended EOS: {th['ext']}s")
            print(f"  Tasa de error por corte prematuro: {error_rate:.1f}% ({premature_cuts}/{total_cases})")
            print(f"  Latencia de turno (comando corto): {avg_short_latency:.2f}s")
            print(f"  Latencia de turno (pregunta larga): {avg_long_latency:.2f}s")
            for c_name, c_res in res.items():
                status = "CORTE PREMATURO [ERROR]" if c_res.get("premature_cut") else "OK [Completa]"
                print(f"    - {c_name:15}: {status} (audio={c_res.get('captured_audio_sec')}s / exp={c_res.get('expected_speech_sec')}s)")


if __name__ == "__main__":
    main()
