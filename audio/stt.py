"""
audio/stt.py
Módulo de Reconocimiento de Voz (Speech-To-Text) usando faster-whisper.
Graba audio del micrófono por un tiempo determinado y transcribe la voz a texto en español.
"""
import logging
import os
import tempfile
import numpy as np
import sounddevice as sd
from scipy.io import wavfile

logger = logging.getLogger(__name__)

# Modelo por defecto ("base" para equilibrio entre velocidad y precisión)
MODEL_NAME = "base"
_model_instance = None


def _get_model(model_name: str = MODEL_NAME):
    """Inicializa y mantiene en caché la instancia de WhisperModel."""
    global _model_instance
    if _model_instance is None:
        try:
            from faster_whisper import WhisperModel
            _model_instance = WhisperModel(model_name, device="cpu", compute_type="int8")
        except Exception as e:
            logger.error(f"[STT Error] No se pudo cargar el modelo faster-whisper '{model_name}': {e}")
            raise
    return _model_instance


def escuchar(duracion_segundos: int = 5, tasa_muestreo: int = 16000) -> str:
    """
    Graba audio desde el micrófono durante `duracion_segundos`
    y lo transcribe a texto en español mediante la librería faster-whisper.

    Args:
        duracion_segundos (int): Tiempo de grabación en segundos (por defecto 5).
        tasa_muestreo (int): Frecuencia de muestreo en Hz (por defecto 16000).

    Returns:
        str: Texto transcrito o "" en caso de silencio, error o ausencia de micrófono.
    """
    if duracion_segundos <= 0:
        return ""

    temp_wav_path = None
    try:
        # 1. Obtener y verificar dispositivo de entrada predeterminado del sistema
        try:
            default_device_idx = sd.default.device[0]
            if default_device_idx is None or default_device_idx < 0:
                print("\n[STT - Aviso]: No se detectó ningún micrófono predeterminado disponible.")
                return ""
            dev_info = sd.query_devices(default_device_idx, "input")
            dev_name = dev_info.get("name", "Desconocido")
        except Exception as e:
            print(f"\n[STT - Aviso]: Error al consultar el micrófono predeterminado ({e}).")
            return ""

        print(f"\n[Escuchando...] Usando micrófono [{default_device_idx}: {dev_name}] durante {duracion_segundos}s...")

        # 2. Grabar audio del micrófono predeterminado
        num_frames = int(duracion_segundos * tasa_muestreo)
        audio_data = sd.rec(num_frames, samplerate=tasa_muestreo, channels=1, dtype="int16", device=default_device_idx)
        sd.wait()

        if audio_data is None or len(audio_data) == 0:
            print("[STT - Aviso]: La grabación resultó vacía.")
            return ""

        # Diagnóstico de nivel de volumen máximo capturado (amplitud entre 0 y 32767)
        max_amplitude = int(np.max(np.abs(audio_data)))
        print(f"[STT Diagnóstico]: Amplitud de volumen máxima capturada: {max_amplitude} / 32767")

        if max_amplitude < 100:  # Umbral de silencio
            print("[STT - Aviso]: No se detectó voz (silencio).")
            return ""

        # 3. Guardar audio temporalmente en formato WAV
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_wav_path = f.name

        wavfile.write(temp_wav_path, tasa_muestreo, audio_data)

        # 4. Transcribir usando el modelo de faster-whisper
        model = _get_model()
        segments, _ = model.transcribe(temp_wav_path, language="es", beam_size=5)

        texto_transcrito = " ".join([segment.text.strip() for segment in segments]).strip()
        return texto_transcrito

    except Exception as e:
        mensaje_error = f"[STT Error]: Error durante el reconocimiento de voz ({e})."
        logger.error(mensaje_error)
        print(f"\n{mensaje_error}")
        return ""
    finally:
        if temp_wav_path and os.path.exists(temp_wav_path):
            try:
                os.remove(temp_wav_path)
            except Exception:
                pass
