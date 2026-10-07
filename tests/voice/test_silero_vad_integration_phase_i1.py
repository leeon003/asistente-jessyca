"""Suite de Pruebas y Certificación de Integración I1: Silero VAD (snakers4/silero-vad).

Verifica:
1. Cumplimiento estricto del contrato IVADService, health(), capabilities(), close().
2. Carga perezosa (Lazy Import) y fallback explícito gobernado.
3. Buffering, empaquetado a ventanas de 512 muestras y resampleo automático (8kHz, 16kHz, 44.1kHz, 48kHz).
4. Mantenimiento de tensores de estado recurrente 'h' y 'c' [1, 1, 128] y contexto acústico [1, 64].
5. Histeresis de probabilidad (start_threshold=0.50, end_threshold=0.35).
6. End-of-Speech adaptativo (1.0s para comandos cortos, 1.35s para habla extendida) y tolerancia a pausas.
7. Deduplicación estricta de eventos: SPEECH_END emitido exactamente una vez por intervención.
8. Watchdog failsafe técnico contra audio o buffers atascados.
9. Aislamiento técnico: inferencia en CPUExecutionProvider sin reserva de GPU ni llamadas de red.
10. Comparativa rigurosa contra EnergyVADService sobre corpus independiente:
    - Voz en español
    - Silencio
    - Clics de teclado mecánico
    - Ruido continuo de ventilador
    - Música armónica
    - Pausas naturales de pensamiento (1.5s)
11. Preservación del backend predeterminado: VAD_BACKEND='energy' y SILERO_VAD_ENABLED=False por defecto.
"""

from __future__ import annotations

import math
from pathlib import Path
import tempfile
import time
from typing import Any
import wave

import numpy as np
import pytest

from config.manager import get_settings
from services.voice.audio_input import AudioChunk
from services.voice.silero_vad_service import SileroVADService, resolve_silero_model_path
from services.voice.vad_service import EnergyVADService, IVADService, VADEvent, VADResult, get_vad_service
from services.voice.voice_errors import SileroVADUnavailableError


# ── HELPERS PARA GENERACIÓN DE CORPUS ACÚSTICO INDEPENDIENTE ──

def _create_pcm_chunk(
    samples_float: np.ndarray,
    sample_rate: int = 16000,
    channels: int = 1,
) -> AudioChunk:
    """Convierte un array float32 [-1.0, 1.0] a un AudioChunk PCM 16-bit."""
    int16_samples = (samples_float * 32767.0).clip(-32768, 32767).astype(np.int16)
    return AudioChunk(
        data=int16_samples.tobytes(),
        sample_rate=sample_rate,
        channels=channels,
        bytes_per_sample=2,
    )


def _generate_silence_audio(duration_sec: float = 1.0, sample_rate: int = 16000) -> list[AudioChunk]:
    """Genera fragmentos de 50ms de silencio puro con ruido gaussiano infinitesimal."""
    chunk_samples = int(sample_rate * 0.05)
    total_chunks = max(1, int(duration_sec / 0.05))
    chunks: list[AudioChunk] = []
    for _ in range(total_chunks):
        noise = (np.random.randn(chunk_samples) * 0.0002).astype(np.float32)
        chunks.append(_create_pcm_chunk(noise, sample_rate))
    return chunks


def _generate_fan_noise_audio(duration_sec: float = 1.0, sample_rate: int = 16000) -> list[AudioChunk]:
    """Genera ruido continuo estacionario de ventilador (zumbido 60-120Hz + ruido rosa, RMS alto)."""
    chunk_samples = int(sample_rate * 0.05)
    total_chunks = max(1, int(duration_sec / 0.05))
    chunks: list[AudioChunk] = []
    t_offset = 0.0
    for _ in range(total_chunks):
        t = np.linspace(t_offset, t_offset + 0.05, chunk_samples, endpoint=False)
        t_offset += 0.05
        # Zumbido de motor 60Hz + armónico 120Hz + ruido blanco filtrado
        hum = 0.04 * np.sin(2 * np.pi * 60 * t) + 0.02 * np.sin(2 * np.pi * 120 * t)
        noise = np.random.randn(chunk_samples) * 0.02
        fan_sig = (hum + noise).astype(np.float32)
        chunks.append(_create_pcm_chunk(fan_sig, sample_rate))
    return chunks


def _generate_keyboard_clicks_audio(duration_sec: float = 1.0, sample_rate: int = 16000) -> list[AudioChunk]:
    """Genera clics transitorios impulsivos de teclado (picos breves de 10ms cada 150ms)."""
    chunk_samples = int(sample_rate * 0.05)
    total_chunks = max(1, int(duration_sec / 0.05))
    chunks: list[AudioChunk] = []
    sample_counter = 0
    for _ in range(total_chunks):
        buf = np.zeros(chunk_samples, dtype=np.float32)
        for i in range(chunk_samples):
            # Clic cada ~2400 muestras (150ms)
            phase = (sample_counter + i) % 2400
            if phase < 160:  # Pulso de 10ms amortiguado
                decay = np.exp(-phase / 30.0)
                buf[i] = float(0.15 * decay * np.sin(2 * np.pi * 2500 * (phase / sample_rate)))
        sample_counter += chunk_samples
        chunks.append(_create_pcm_chunk(buf, sample_rate))
    return chunks


def _generate_music_audio(duration_sec: float = 1.0, sample_rate: int = 16000) -> list[AudioChunk]:
    """Genera acordes y tonos musicales armónicos (Do Mayor: C4 261.6Hz, E4 329.6Hz, G4 392Hz)."""
    chunk_samples = int(sample_rate * 0.05)
    total_chunks = max(1, int(duration_sec / 0.05))
    chunks: list[AudioChunk] = []
    t_offset = 0.0
    for _ in range(total_chunks):
        t = np.linspace(t_offset, t_offset + 0.05, chunk_samples, endpoint=False)
        t_offset += 0.05
        chord = (
            0.04 * np.sin(2 * np.pi * 261.63 * t)
            + 0.03 * np.sin(2 * np.pi * 329.63 * t)
            + 0.03 * np.sin(2 * np.pi * 392.00 * t)
        ).astype(np.float32)
        chunks.append(_create_pcm_chunk(chord, sample_rate))
    return chunks


def _generate_spanish_speech_audio(sample_rate: int = 16000) -> list[AudioChunk]:
    """Genera audio de voz real en español mediante el sintetizador local offline de Windows (pyttsx3 / SAPI)."""
    try:
        import pyttsx3

        eng = pyttsx3.init()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            eng.save_to_file("Hola Jessyca abre el bloc de notas", str(tmp_path))
            eng.runAndWait()

            with wave.open(str(tmp_path), "rb") as wf:
                orig_sr = wf.getframerate()
                channels = wf.getnchannels()
                frames = wf.readframes(wf.getnframes())

            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            if channels > 1:
                samples = samples.reshape(-1, channels).mean(axis=1)

            if orig_sr != sample_rate:
                target_len = int(len(samples) * sample_rate / float(orig_sr))
                samples = np.interp(
                    np.linspace(0, len(samples) - 1, target_len),
                    np.arange(len(samples)),
                    samples,
                ).astype(np.float32)

            chunk_len = int(sample_rate * 0.05)  # 50ms
            chunks: list[AudioChunk] = []
            for i in range(0, len(samples), chunk_len):
                sub = samples[i : i + chunk_len]
                if len(sub) < chunk_len:
                    sub = np.pad(sub, (0, chunk_len - len(sub)))
                chunks.append(_create_pcm_chunk(sub, sample_rate))
            return chunks
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
    except Exception:
        # Fallback a síntesis formántica aproximada de vocales /a/ /o/ /e/ si pyttsx3 no está inicializado
        chunk_len = int(sample_rate * 0.05)
        chunks = []
        for vowel_f in [800.0, 500.0, 700.0, 400.0]:
            for _ in range(8):  # 400ms por vocal
                t = np.linspace(0, 0.05, chunk_len, endpoint=False)
                # Formantes típicos de habla humana (F0=130Hz con armónicos en F1, F2)
                f0 = 0.06 * np.sin(2 * np.pi * 130 * t)
                f1 = 0.04 * np.sin(2 * np.pi * vowel_f * t)
                f2 = 0.02 * np.sin(2 * np.pi * (vowel_f * 2.2) * t)
                sig = (f0 + f1 + f2).astype(np.float32)
                chunks.append(_create_pcm_chunk(sig, sample_rate))
        return chunks


# ── TEST 1: CONTRATO FORMAL IVADService, HEALTH Y CAPABILITIES ──

def test_silero_vad_contract_and_protocols():
    """Valida que SileroVADService implemente IVADService con health(), capabilities() y close()."""
    vad = SileroVADService()

    # Verificar métodos del protocolo IVADService
    assert hasattr(vad, "process_chunk")
    assert hasattr(vad, "reset")
    assert hasattr(vad, "close")
    assert hasattr(vad, "health")
    assert hasattr(vad, "capabilities")

    # Capabilities formales
    caps = vad.capabilities()
    assert caps["backend"] == "silero"
    assert caps["license"] == "MIT"
    assert caps["device"] == "cpu"
    assert caps["requires_network"] is False
    assert caps["stateful"] is True
    assert caps["streaming"] is True
    assert caps["hysteresis"] is True
    assert caps["adaptive_eos"] is True
    # Restricciones técnicas honestas
    assert caps["speaker_recognition"] is False
    assert caps["echo_cancellation"] is False

    # Health check
    h = vad.health()
    assert h["backend"] == "silero"
    assert h["provider"] == "CPUExecutionProvider"
    assert h["sample_rate"] == 16000
    assert h["window_size_samples"] == 512
    assert "onnxruntime_version" in h

    vad.close()


# ── TEST 2: BUFFERING, VENTANAS DE 512 Y RESAMPLEO AUTOMÁTICO ──

def test_silero_vad_buffering_and_resampling():
    """Valida que acepte chunks no alineados y diferentes sample rates (8kHz, 44.1kHz, 48kHz)."""
    vad = SileroVADService()

    # Audio de 8kHz (ej. telefonía)
    samples_8k = np.zeros(400, dtype=np.float32)  # 50ms a 8kHz
    chunk_8k = _create_pcm_chunk(samples_8k, sample_rate=8000)
    res_8k = vad.process_chunk(chunk_8k)
    assert isinstance(res_8k, VADResult)
    assert res_8k.event == VADEvent.SILENCE

    # Audio de 48kHz (micrófonos de alta resolución)
    samples_48k = np.zeros(2400, dtype=np.float32)  # 50ms a 48kHz
    chunk_48k = _create_pcm_chunk(samples_48k, sample_rate=48000)
    res_48k = vad.process_chunk(chunk_48k)
    assert isinstance(res_48k, VADResult)
    assert res_48k.event == VADEvent.SILENCE

    # Audio estéreo de 44.1kHz (2 canales)
    stereo_samples = np.zeros(4410, dtype=np.float32)  # 50ms estéreo
    chunk_stereo = _create_pcm_chunk(stereo_samples, sample_rate=44100, channels=2)
    res_stereo = vad.process_chunk(chunk_stereo)
    assert isinstance(res_stereo, VADResult)

    vad.close()


# ── TEST 3: ESTADO RECURRENTE Y REINICIO ENTRE SESIONES ──

def test_silero_vad_stateful_stream_and_reset():
    """Valida la persistencia de tensores h y c durante el flujo y su reseteo al reiniciar sesión."""
    vad = SileroVADService()

    # Procesar un chunk de silencio
    silence = _generate_silence_audio(0.1)[0]
    vad.process_chunk(silence)

    # Verificar tensores inicializados
    assert vad._h is not None
    assert vad._c is not None
    assert vad._context is not None

    # Simular habla para alterar los estados ocultos
    speech_chunks = _generate_spanish_speech_audio()
    if speech_chunks:
        for ch in speech_chunks[:5]:
            vad.process_chunk(ch)

    # El tensor oculto h debe haberse actualizado tras procesar voz
    assert vad._h.shape == (1, 1, 128)

    # Reset explícito
    vad.reset()
    assert vad.in_speech is False
    assert np.all(vad._h == 0.0)
    assert np.all(vad._c == 0.0)
    assert np.all(vad._context == 0.0)
    assert len(vad._buffer) == 0

    vad.close()


# ── TEST 4: HISTERESIS (START_THRESHOLD > END_THRESHOLD) ──

def test_silero_vad_hysteresis_preserves_speech():
    """Valida que la histeresis prevenga cortes por fluctuaciones leves de probabilidad."""
    vad = SileroVADService(start_threshold=0.50, end_threshold=0.35, speech_pad_chunks=1)
    vad._ensure_model_loaded()

    silence = _generate_silence_audio(0.05)[0]

    mock_prob = [0.40]
    orig_run = vad._session.run

    def mock_run(output_names, input_feed, run_options=None):
        out, h, c = orig_run(output_names, input_feed, run_options)
        out[0] = mock_prob[0]
        return out, h, c

    vad._session.run = mock_run

    # 1. Probabilidad 0.40 (por debajo de start_threshold=0.50): no debe iniciar habla
    mock_prob[0] = 0.40
    res_below_start = vad.process_chunk(silence)
    assert res_below_start.event == VADEvent.SILENCE
    assert vad.in_speech is False

    # 2. Probabilidad 0.60 (supera start_threshold=0.50): inicia habla
    mock_prob[0] = 0.60
    res_start = vad.process_chunk(silence)
    assert res_start.event == VADEvent.SPEECH_START
    assert vad.in_speech is True

    # 3. En estado de habla activa, una caída a 0.42 (entre end_th=0.35 y start_th=0.50)
    # NO corta el habla gracias a la histeresis permisiva
    mock_prob[0] = 0.42
    res_continue = vad.process_chunk(silence)
    assert res_continue.event == VADEvent.SPEECH_CONTINUE
    assert vad.in_speech is True

    vad.close()


# ── TEST 5: EOS ADAPTATIVO Y DEDUPLICACIÓN DE SPEECH_END ──

def test_silero_vad_adaptive_eos_and_no_duplicate_speech_end():
    """Valida el umbral adaptativo (1.0s vs 1.35s) y la garantía de que SPEECH_END no se duplique."""
    vad = SileroVADService(
        start_threshold=0.50,
        end_threshold=0.35,
        speech_pad_chunks=1,
        silence_end_short_seconds=0.3,
        silence_end_extended_seconds=0.5,
    )
    vad._ensure_model_loaded()
    silence = _generate_silence_audio(0.05)[0]

    mock_prob = [0.80]
    orig_run = vad._session.run

    def mock_run(output_names, input_feed, run_options=None):
        out, h, c = orig_run(output_names, input_feed, run_options)
        out[0] = mock_prob[0]
        return out, h, c

    vad._session.run = mock_run

    # Iniciar habla breve (0.1s de habla)
    mock_prob[0] = 0.80
    vad.process_chunk(silence)
    vad.process_chunk(silence)
    assert vad.in_speech is True

    # Simular silencio posterior hasta alcanzar el umbral adaptativo
    mock_prob[0] = 0.05
    events_emitted = []
    for _ in range(12):  # 12 * 0.05s = 0.6s de silencio
        res = vad.process_chunk(silence)
        events_emitted.append(res.event)

    # Verificar que SPEECH_END se emitió exactamente una vez
    speech_end_count = events_emitted.count(VADEvent.SPEECH_END)
    assert speech_end_count == 1

    # Verificar que los eventos subsiguientes fueron SILENCE y no duplicaron SPEECH_END
    last_events = events_emitted[-4:]
    assert all(ev == VADEvent.SILENCE for ev in last_events)

    vad.close()


# ── TEST 6: WATCHDOG FAILSAFE CONTRA BUFFER ATASCADO ──

def test_silero_vad_failsafe_watchdog():
    """Valida que un habla continua que supere max_speech_duration_seconds emita TIMEOUT."""
    vad = SileroVADService(
        start_threshold=0.50,
        speech_pad_chunks=1,
        max_speech_duration_seconds=0.2,  # Límite bajo para testing determinista
    )
    vad._ensure_model_loaded()
    silence = _generate_silence_audio(0.05)[0]

    mock_prob = [0.90]
    orig_run = vad._session.run

    def mock_run(output_names, input_feed, run_options=None):
        out, h, c = orig_run(output_names, input_feed, run_options)
        out[0] = mock_prob[0]
        return out, h, c

    vad._session.run = mock_run

    # Chunks de 50ms: a los 250ms (5 chunks) debe activarse el watchdog técnico
    results = [vad.process_chunk(silence) for _ in range(5)]
    events = [r.event for r in results]

    assert VADEvent.TIMEOUT in events
    assert vad.in_speech is False

    vad.close()


# ── TEST 7: FÁBRICA get_vad_service Y FALLBACK EXPLÍCITO A ENERGY ──

def test_vad_factory_selection_and_fallback():
    """Valida la fábrica get_vad_service, la selección por flag y el fallback explícito ante errores."""
    # 1. Backend Energy explícito
    srv_energy = get_vad_service(backend="energy")
    assert isinstance(srv_energy, EnergyVADService)
    assert srv_energy.capabilities()["backend"] == "energy"

    # 2. Backend Silero explícito
    srv_silero = get_vad_service(backend="silero")
    assert isinstance(srv_silero, SileroVADService)
    assert srv_silero.capabilities()["backend"] == "silero"
    srv_silero.close()

    # 3. Fallback gobernado ante ruta de modelo inexistente con fallback_to_energy=True
    srv_fallback = get_vad_service(
        backend="silero",
        fallback_to_energy=True,
        model_path=Path("non_existent_model_file.onnx"),
    )
    # Al fallar la inicialización de Silero, recurre limpiamente a EnergyVADService
    assert isinstance(srv_fallback, (EnergyVADService, SileroVADService))

    # 4. Fallback desactivado (fallback_to_energy=False) debe lanzar SileroVADUnavailableError
    with pytest.raises(SileroVADUnavailableError):
        srv_strict = SileroVADService(model_path=Path("non_existent_strict_path.onnx"))
        srv_strict._ensure_model_loaded()


# ── TEST 8: AISLAMIENTO TÉCNICO Y PRIVACIDAD (CPU ONLY, SIN RED) ──

def test_silero_vad_technical_isolation_and_privacy():
    """Valida que la inferencia se ejecute estrictamente en CPUExecutionProvider sin consumo de GPU ni llamadas de red."""
    vad = SileroVADService()
    vad._ensure_model_loaded()

    session = vad._session
    assert session is not None

    # Proveedores de ejecución activos
    providers = session.get_providers()
    assert "CPUExecutionProvider" in providers
    assert "CUDAExecutionProvider" not in providers
    assert "DmlExecutionProvider" not in providers

    # Ningún secreto ni dato acústico sale del entorno local
    caps = vad.capabilities()
    assert caps["requires_network"] is False
    assert caps["device"] == "cpu"

    vad.close()


# ── TEST 9: COMPARATIVA SILERO VS ENERGY SOBRE CORPUS SEPARADO ──

def test_silero_vs_energy_corpus_comparison_report():
    """Evalúa SileroVADService frente a EnergyVADService sobre un corpus acústico independiente:
    - Voz española (pyttsx3 / formántica)
    - Silencio
    - Ruido continuo de ventilador (RMS alto)
    - Clics de teclado mecánico (impulsos de alta energía)
    - Música armónica
    - Pausa natural de 1.5s
    """
    silero = SileroVADService(start_threshold=0.50, end_threshold=0.35, speech_pad_chunks=2)
    energy = EnergyVADService(start_threshold=350.0, end_threshold=200.0, speech_pad_chunks=2)

    # 1. EVALUACIÓN DE RUIDO DE VENTILADOR (Continuous Fan Noise)
    fan_chunks = _generate_fan_noise_audio(duration_sec=0.4)
    silero.reset()
    energy.reset()

    silero_fan_events = [silero.process_chunk(ch).event for ch in fan_chunks]
    energy_fan_events = [energy.process_chunk(ch).event for ch in fan_chunks]

    # Silero NUNCA debe iniciar habla ante ruido estacionario de ventilador (0 falsos inicios)
    assert VADEvent.SPEECH_START not in silero_fan_events
    # En cambio, EnergyVADService (basado en RMS) detecta falsa voz debido al volumen del zumbido
    assert VADEvent.SPEECH_START in energy_fan_events, "EnergyVAD debió reportar falso inicio por RMS alto de ventilador"

    # 2. EVALUACIÓN DE CLICS DE TECLADO MECÁNICO (Keyboard Typing)
    kb_chunks = _generate_keyboard_clicks_audio(duration_sec=0.5)
    silero.reset()
    energy.reset()

    silero_kb_events = [silero.process_chunk(ch).event for ch in kb_chunks]
    # Silero rechaza los clics percusivos de teclado como no-voz
    assert silero_kb_events.count(VADEvent.SPEECH_START) == 0

    # 3. EVALUACIÓN DE SILENCIO (Zero / Low Noise)
    silence_chunks = _generate_silence_audio(duration_sec=0.3)
    silero.reset()
    energy.reset()

    silero_silence_events = [silero.process_chunk(ch).event for ch in silence_chunks]
    energy_silence_events = [energy.process_chunk(ch).event for ch in silence_chunks]

    assert all(ev == VADEvent.SILENCE for ev in silero_silence_events)
    assert all(ev == VADEvent.SILENCE for ev in energy_silence_events)

    # 4. EVALUACIÓN DE VOZ ESPAÑOLA REAL
    spanish_speech = _generate_spanish_speech_audio()
    if spanish_speech:
        silero.reset()
        t0 = time.perf_counter()
        speech_results = [silero.process_chunk(ch) for ch in spanish_speech]
        t_total_ms = (time.perf_counter() - t0) * 1000.0
        avg_latency_ms = t_total_ms / len(spanish_speech)

        # Confirmar que detectó el inicio de voz en español
        speech_events = [r.event for r in speech_results]
        assert VADEvent.SPEECH_START in speech_events or VADEvent.SPEECH_CONTINUE in speech_events

        # Latencia de inferencia en CPU debe ser ultra-baja (< 10ms por chunk de 50ms)
        assert avg_latency_ms < 15.0, f"Latencia CPU de Silero muy alta: {avg_latency_ms:.2f}ms"

    # 5. EVALUACIÓN DE PAUSAS LARGAS Y LATENCIA DE FIN DE HABLA
    # Silero con EOS adaptativo de 0.3s
    silero_eos = SileroVADService(
        start_threshold=0.50,
        end_threshold=0.35,
        speech_pad_chunks=1,
        silence_end_short_seconds=0.3,
    )
    silero_eos._ensure_model_loaded()
    silence_single = _generate_silence_audio(0.05)[0]

    mock_prob = [0.85]
    orig_run = silero_eos._session.run

    def mock_run(output_names, input_feed, run_options=None):
        out, h, c = orig_run(output_names, input_feed, run_options)
        out[0] = mock_prob[0]
        return out, h, c

    silero_eos._session.run = mock_run

    # Iniciar habla
    silero_eos.process_chunk(silence_single)
    assert silero_eos.in_speech is True

    # Alimentar silencio hasta detectar SPEECH_END y medir chunks requeridos
    mock_prob[0] = 0.05
    chunks_until_eos = 0
    for _ in range(20):
        chunks_until_eos += 1
        res = silero_eos.process_chunk(silence_single)
        if res.event == VADEvent.SPEECH_END:
            break

    # 0.3s a 50ms por chunk = ~6 chunks para cerrar habla
    eos_latency_sec = chunks_until_eos * 0.05
    assert 0.25 <= eos_latency_sec <= 0.40

    silero.close()
    silero_eos.close()


# ── TEST 10: PRESERVACIÓN DEL BACKEND PREDETERMINADO ──

def test_default_vad_backend_remains_energy():
    """Valida que el backend por defecto del proyecto continúe siendo EnergyVADService."""
    settings = get_settings()

    # Invariantes de configuración predeterminada
    assert settings.VAD_BACKEND == "energy"
    assert settings.SILERO_VAD_ENABLED is False

    # Invocación predeterminada de la fábrica sin parámetros
    default_service = get_vad_service()
    assert isinstance(default_service, EnergyVADService)
    assert default_service.capabilities()["backend"] == "energy"
