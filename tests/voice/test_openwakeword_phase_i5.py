"""Pruebas de contrato, seguridad y robustez acústica para la integración de openWakeWord (Fase I5).

Verifica:
1. Contrato IWakeWordService estricto.
2. Invariante de seguridad: authorizes_action es SIEMPRE False (detección NO autoriza herramientas).
3. Declaración honesta de disponibilidad: is_acoustic_model_available() es False si no hay modelo entrenado para español.
4. Resampling correcto desde diversas frecuencias (8kHz, 22.05kHz, 44.1kHz, 48kHz) a 16kHz.
5. Buffering y cooldown anti-ráfaga.
6. Separación e independencia del modo manual/Push-to-Talk.
7. Reseteo de sesión y limpieza de buffers de audio.
8. Manejo graceful ante ausencia de dependencia 'openwakeword'.
9. Inferencia acústica exitosa ante modelo válido configurado (mock de predicción).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import numpy as np
import pytest

from services.voice.audio_capture import AudioChunk
from services.voice.openwakeword_service import OpenWakeWordAcousticService
from services.voice.wake_word_service import IWakeWordService


@pytest.fixture
def sample_audio_chunk() -> AudioChunk:
    """Genera un fragmento de audio sintético int16 a 16kHz."""
    samples = np.zeros(1600, dtype=np.int16)  # 100ms a 16kHz
    return AudioChunk(
        data=samples.tobytes(),
        sample_rate=16000,
        channels=1,
        timestamp=time.time(),
    )


# ==============================================================================
# 1. Contrato Formal e Invariante de Seguridad
# ==============================================================================
def test_openwakeword_implements_wake_word_protocol() -> None:
    """Verifica que OpenWakeWordAcousticService satisface el protocolo IWakeWordService."""
    service = OpenWakeWordAcousticService()
    assert isinstance(service, IWakeWordService)
    assert hasattr(service, "process_audio")
    assert hasattr(service, "reset")
    assert hasattr(service, "is_acoustic_model_available")
    assert service.authorizes_action is False


def test_openwakeword_authorizes_action_is_strictly_false(sample_audio_chunk: AudioChunk) -> None:
    """INVARIANTE CRÍTICO: Ningún resultado de wake word puede conceder autorización de acciones."""
    service = OpenWakeWordAcousticService(enabled=True)

    # 1. Sin modelo
    res_unconf = service.process_audio(sample_audio_chunk)
    assert res_unconf.authorizes_action is False

    # 2. Con activación manual
    service.trigger_manually()
    res_manual = service.process_audio(sample_audio_chunk)
    assert res_manual.detected is True
    assert res_manual.authorizes_action is False

    # 3. Desactivado
    service.enabled = False
    res_disabled = service.process_audio(sample_audio_chunk)
    assert res_disabled.authorizes_action is False


# ==============================================================================
# 2. Declaración Honesta de Idioma y Disponibilidad
# ==============================================================================
def test_openwakeword_declares_unavailable_honestly_when_no_spanish_model() -> None:
    """Verifica que el servicio declara honestamente False si no existe un modelo local para 'Jessyca'."""
    # No se configuró model_path
    service = OpenWakeWordAcousticService(keyword="jessyca", model_path=None)
    assert service.is_acoustic_model_available() is False

    # Se configuró una ruta que no existe físicamente
    service_missing = OpenWakeWordAcousticService(keyword="jessyca", model_path="models/wakeword/non_existent.onnx")
    assert service_missing.is_acoustic_model_available() is False


def test_openwakeword_processing_without_model_reports_explicit_status(sample_audio_chunk: AudioChunk) -> None:
    """Verifica que procesar audio sin modelo configurado retorna estado tipado sin colapsar."""
    service = OpenWakeWordAcousticService(keyword="jessyca", model_path=None)
    res = service.process_audio(sample_audio_chunk)

    assert res.detected is False
    assert res.confidence == 0.0
    assert res.metadata.get("status") == "ACOUSTIC_MODEL_UNAVAILABLE"
    assert "inglés" in res.metadata.get("language_note", "").lower()


# ==============================================================================
# 3. Resampling y Manejo Multi-Frecuencia
# ==============================================================================
@pytest.mark.parametrize("input_sr", [8000, 22050, 44100, 48000])
def test_openwakeword_resamples_to_16000(input_sr: int) -> None:
    """Verifica que fragmentos con frecuencias distintas a 16kHz son remuestreados a 16kHz."""
    service = OpenWakeWordAcousticService()
    duration_s = 0.5
    raw_samples = np.ones(int(duration_s * input_sr), dtype=np.int16) * 1000

    resampled = service._resample_audio(raw_samples, input_sr)
    expected_samples = int(duration_s * 16000)

    # Tolerancia de 1 muestra por redondeo
    assert abs(len(resampled) - expected_samples) <= 1
    assert resampled.dtype == np.int16


# ==============================================================================
# 4. Modo Manual / Push-to-Talk y Cooldown
# ==============================================================================
def test_openwakeword_push_to_talk_mode(sample_audio_chunk: AudioChunk) -> None:
    """Verifica que el modo manual/push-to-talk opera de forma independiente y se consume una sola vez."""
    service = OpenWakeWordAcousticService(enabled=True)

    # Estado inicial: no detectado
    res1 = service.process_audio(sample_audio_chunk)
    assert res1.detected is False

    # Activar manualmente
    service.trigger_manually()
    res2 = service.process_audio(sample_audio_chunk)
    assert res2.detected is True
    assert res2.confidence == 1.0
    assert res2.metadata.get("trigger") == "manual_push_to_talk"
    assert res2.authorizes_action is False

    # Siguiente chunk: vuelve a no detectado (consumo atómico del trigger)
    res3 = service.process_audio(sample_audio_chunk)
    assert res3.detected is False


def test_openwakeword_session_reset(sample_audio_chunk: AudioChunk) -> None:
    """Verifica que reset() limpia triggers pendientes y vacía los buffers de audio."""
    service = OpenWakeWordAcousticService()
    service.trigger_manually()
    service._audio_buffer.append(np.ones(500, dtype=np.int16))

    service.reset()
    assert service._manual_triggered is False
    assert len(service._audio_buffer) == 0


# ==============================================================================
# 5. Inferencia Acústica con Modelo Simulado
# ==============================================================================
def test_openwakeword_acoustic_inference_detection(tmp_path: Path) -> None:
    """Verifica la detección acústica cuando el modelo ONNX predice un score superior al umbral."""
    # Crear un archivo de modelo falso en tmp_path
    fake_model_file = tmp_path / "jessyca_model.onnx"
    fake_model_file.write_bytes(b"FAKE_ONNX_MODEL_HEADER")

    mock_model_instance = MagicMock()
    # openWakeWord predict devuelve diccionario {model_name: score}
    mock_model_instance.predict.return_value = {"jessyca_model": 0.85}

    # This is a simulated inference contract; it must not require the optional package.
    from types import ModuleType
    fake_package = ModuleType("openwakeword")
    fake_model_module = ModuleType("openwakeword.model")
    fake_model_module.Model = MagicMock(return_value=mock_model_instance)
    fake_package.model = fake_model_module
    with mock.patch.dict(sys.modules, {"openwakeword": fake_package, "openwakeword.model": fake_model_module}):
        service = OpenWakeWordAcousticService(
            keyword="jessyca",
            model_path=fake_model_file,
            confidence_threshold=0.60,
            cooldown_seconds=1.0,
        )

        assert service.is_acoustic_model_available() is True

        # Enviar 1280 muestras (80ms a 16kHz)
        audio_frame = np.random.randint(-1000, 1000, 1280, dtype=np.int16)
        chunk = AudioChunk(data=audio_frame.tobytes(), sample_rate=16000, channels=1, timestamp=time.time())

        res = service.process_audio(chunk)

        assert res.detected is True
        assert res.confidence == 0.85
        assert res.keyword == "jessyca"
        assert res.authorizes_action is False

        # Inmediatamente siguiente chunk: cooldown activo (debe dar detected=False)
        res_cooldown = service.process_audio(chunk)
        assert res_cooldown.detected is False
        assert res_cooldown.metadata.get("status") == "COOLDOWN_ACTIVE"


# ==============================================================================
# 6. Fallo Graceful ante Ausencia de Dependencia openWakeWord
# ==============================================================================
def test_openwakeword_missing_dependency_behavior(tmp_path: Path) -> None:
    """Verifica que si openwakeword no está instalado, se registra el fallo sin abortar la aplicación."""
    fake_model_file = tmp_path / "model.onnx"
    fake_model_file.write_bytes(b"FAKE")

    with mock.patch.dict(sys.modules, {"openwakeword": None, "openwakeword.model": None}):
        service = OpenWakeWordAcousticService(keyword="jessyca", model_path=fake_model_file)
        assert service.is_acoustic_model_available() is False
        assert "no disponible" in (service._load_error or "").lower()


# ==============================================================================
# 7. Fábrica Gobernada y Exportaciones del Paquete
# ==============================================================================
def test_wake_word_factory_defaults_to_manual() -> None:
    """Verifica que get_wake_word_service retorna KeywordWakeWordService por defecto."""
    from services.voice.wake_word_service import KeywordWakeWordService, get_wake_word_service

    service = get_wake_word_service()
    assert isinstance(service, KeywordWakeWordService)
    assert service.authorizes_action is False
    assert service.is_acoustic_model_available() is False


def test_wake_word_factory_instantiates_openwakeword() -> None:
    """Verifica que get_wake_word_service(backend='openwakeword') retorna OpenWakeWordAcousticService."""
    from services.voice.wake_word_service import get_wake_word_service

    service = get_wake_word_service(backend="openwakeword")
    assert isinstance(service, OpenWakeWordAcousticService)
    assert service.authorizes_action is False


def test_wake_word_factory_fallback_on_init_failure() -> None:
    """Verifica que si la inicialización de openwakeword falla, se realiza fallback a manual."""
    from services.voice.wake_word_service import KeywordWakeWordService, get_wake_word_service

    with mock.patch("services.voice.openwakeword_service.OpenWakeWordAcousticService.__init__", side_effect=RuntimeError("Init crash")):
        service = get_wake_word_service(backend="openwakeword", fallback_to_manual=True)
        assert isinstance(service, KeywordWakeWordService)


def test_voice_package_exports_lazy_openwakeword() -> None:
    """Verifica la exportación e importación perezosa desde services.voice."""
    import services.voice as voice_pkg

    assert hasattr(voice_pkg, "get_wake_word_service")
    assert hasattr(voice_pkg, "OpenWakeWordAcousticService")
    assert voice_pkg.OpenWakeWordAcousticService is OpenWakeWordAcousticService

