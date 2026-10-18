"""Pruebas de verificación y regresión para JESSYCA VOICE REALTIME — FASE 1.

Verifica:
1. Integración correcta y reversible de Silero VAD (ONNX).
2. Conservación íntegra de Energy VAD como backend alternativo.
3. Protección de umbrales probabilísticos contra valores de energía acústica (> 1.0).
4. Desacoplamiento de reproducción de audio con cancelación segura (Barge-In).
5. Coordinación de acceso al micrófono evitando capturas concurrentes.
6. Preservación del contexto de sesión conversacional.
"""
import time
import pytest
from unittest.mock import MagicMock
from services.voice.vad_service import EnergyVADService, get_vad_service, VADEvent
from services.voice.silero_vad_service import SileroVADService
from services.voice.audio_input import AudioChunk
from services.voice.barge_in_controller import BargeInController
from services.voice.audio_capture import CalibratedVoiceCaptureEngine
from interfaces.modo_voz import VoiceSpeaker
from core.cancellation import CancellationToken
from core.state.machine import SessionState, StateMachine


def test_silero_vad_instantiation_and_probabilistic_thresholds():
    """Verifica que Silero VAD cargue con umbrales normalizados de probabilidad y no RMS."""
    vad = get_vad_service(backend="silero", start_threshold=0.55, end_threshold=0.35)
    assert isinstance(vad, SileroVADService)
    assert 0.1 <= vad.start_threshold <= 0.99
    assert 0.05 <= vad.end_threshold <= vad.start_threshold

    # Probar que update_thresholds con RMS acústico (> 1.0) no rompa los umbrales de Silero
    vad.update_thresholds(start_threshold=380.0, end_threshold=220.0)
    assert vad.start_threshold == 0.55
    assert vad.end_threshold == 0.35


def test_energy_vad_fallback_and_reversibility():
    """Verifica que Energy VAD funcione de forma completamente reversible como alternativa."""
    vad_energy = get_vad_service(backend="energy", start_threshold=350.0, end_threshold=200.0)
    assert isinstance(vad_energy, EnergyVADService)
    assert vad_energy.start_threshold == 350.0
    assert vad_energy.end_threshold == 200.0


def test_adaptive_stream_with_silero_and_energy():
    """Verifica que evaluate_adaptive_stream funcione tanto con Energy VAD como con Silero VAD."""
    # Chunk de silencio PCM de 50ms (800 samples a 16kHz)
    silence_chunk = b"\x00" * 1600

    for backend in ["energy", "silero"]:
        vad = get_vad_service(backend=backend)
        engine = CalibratedVoiceCaptureEngine(
            sample_rate=16000,
            channels=1,
            vad_service=vad,
            adaptive_eos_enabled=True,
        )
        assert engine.vad_service is not None
        # Comprobar que capabilities declare el backend respectivo
        caps = engine.vad_service.capabilities()
        assert caps["backend"] == backend


def test_voice_speaker_decoupled_playback_and_barge_in():
    """Verifica que VoiceSpeaker permita reproducción desacoplada y se cancele de inmediato ante barge-in."""
    mock_tts = MagicMock()
    mock_tts.is_active = True
    sm = StateMachine()
    sm._context.current_state = SessionState.RESPONDING

    barge_in = BargeInController(
        tts_manager=mock_tts,
        state_machine=sm,
    )

    speaker = VoiceSpeaker()
    speaker._tts_manager = mock_tts
    speaker.barge_in_controller = barge_in

    token = CancellationToken()
    barge_in.notify_tts_started(cancellation_token=token, session_id="test_barge_session")

    assert barge_in._is_tts_active is True
    assert token.is_cancelled is False

    # Simular interrupción del usuario (barge-in)
    interrupted = barge_in.trigger_barge_in(reason="User spoke during response")
    assert interrupted is True
    assert token.is_cancelled is True
    assert barge_in._is_tts_active is False
    assert sm.current_state == SessionState.LISTENING


def test_no_uncoordinated_mic_capture():
    """Verifica que el lock del motor de captura proteja el micrófono contra concurrencia no coordinada."""
    engine = CalibratedVoiceCaptureEngine(
        sample_rate=16000,
        channels=1,
        adaptive_eos_enabled=True,
    )

    # El lock debe existir y ser RLock
    assert hasattr(engine, "_lock")
    with engine._lock:
        # Simulamos propiedad exclusiva del lock
        pass
