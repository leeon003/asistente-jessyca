"""
audio/wake_word.py
Módulo de detección de palabra de activación (Wake Word) "Jessyca" basado en VAD (Voice Activity Detection).

Enfoque VAD (Segmentación por voz/silencio):
En lugar de fragmentos de tiempo fijo, se utiliza detección de actividad de voz por energía/amplitud
con sounddevice.InputStream para detectar el INICIO y FIN de cada frase completa (esperando ~0.5s de silencio).
Incluye un búfer pre-roll circular (~0.4s) y filtro de similitud estricto (85%) con validación de longitud de palabras.
"""
from collections import deque
import difflib
import logging
import os
import tempfile
import unicodedata
import re
import time
import numpy as np
import sounddevice as sd
import yaml
from scipy.io import wavfile
from audio.stt import _get_model

logger = logging.getLogger(__name__)

CONFIG_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "settings.yaml"
)

# Palabras clave y variaciones fonéticas/parciales comunes de "Jessyca"
WAKE_WORD_VARIATIONS = {
    "jessyca", "jessica", "yesica", "yessica", "jesica", "jesika", "yesika",
    "esica", "sica", "yeca", "jess", "yesi", "jesi"
}


def _normalizar_texto(texto: str) -> str:
    """Normaliza texto eliminando acentos, puntuación y convirtiendo a minúsculas."""
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^\w\s]", "", texto)
    return texto


def _obtener_wake_word_configurada() -> set:
    """Carga la palabra de activación y sus variaciones desde settings.yaml o usa el conjunto por defecto."""
    variaciones = set(WAKE_WORD_VARIATIONS)
    if os.path.exists(CONFIG_SETTINGS_PATH):
        try:
            with open(CONFIG_SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "audio" in data and isinstance(data["audio"], dict):
                    ww = data["audio"].get("wake_word")
                    if ww and isinstance(ww, str):
                        variaciones.add(_normalizar_texto(ww))
                    vars_yaml = data["audio"].get("wake_word_variations")
                    if isinstance(vars_yaml, list):
                        for item in vars_yaml:
                            if isinstance(item, str):
                                variaciones.add(_normalizar_texto(item))
        except Exception:
            pass
    return variaciones


def _es_coincidencia_wake_word(
    texto_transcrito: str,
    wake_words: set,
    umbral_similitud: float = 0.85
) -> tuple[bool, float]:
    """
    Evalúa la similitud entre el texto transcrito y las palabras de activación.

    Reglas de filtro estricto:
    1. Búsqueda exacta de palabra clave o subcadena directa.
    2. Validación de longitud: Al menos una palabra debe tener longitud aceptable (>= 4 caracteres).
    3. Similitud aproximada estricta con SequenceMatcher (umbral mínimo 85%).

    Returns:
        tuple[bool, float]: (es_coincidencia, porcentaje_max_similitud)
    """
    if not texto_transcrito:
        return False, 0.0

    palabras = [p for p in texto_transcrito.split() if p]
    if not palabras:
        return False, 0.0

    # 1. Coincidencia exacta de palabras clave o subcadenas directas
    for ww in wake_words:
        if ww in texto_transcrito:
            for p in palabras:
                if p == ww or (len(p) >= 4 and (ww in p or p in ww)):
                    return True, 1.0

    # 2. Validación de longitud de palabras candidatas (>= 4 caracteres)
    palabras_candidatas = [p for p in palabras if len(p) >= 4]
    if not palabras_candidatas:
        return False, 0.0

    # 3. Comparación difusa mediante difflib con umbral estricto (85%)
    max_ratio = 0.0
    for p in palabras_candidatas:
        for ww in wake_words:
            ratio = difflib.SequenceMatcher(None, p, ww).ratio()
            if ratio > max_ratio:
                max_ratio = ratio
            if ratio >= umbral_similitud:
                return True, ratio

    return False, max_ratio


def esperar_wake_word(
    umbral_amplitud: int = 200,
    preroll_seg: float = 0.4,
    silencio_confirmacion_seg: float = 0.5,
    duracion_minima_seg: float = 0.5,
    tasa_muestreo: int = 16000,
    tamano_frame_ms: int = 50,
    umbral_similitud: float = 0.85
) -> None:
    """
    Escucha de forma continua mediante segmentación VAD basada en voz/silencio con búfer pre-roll.
    Evalúa la similitud del texto transcrito con un umbral estricto del 85% e imprime el porcentaje calculado.

    Args:
        umbral_amplitud (int): Umbral de amplitud de audio para detectar inicio de voz (200).
        preroll_seg (float): Segundos de audio previo en búfer circular (0.4s).
        silencio_confirmacion_seg (float): Segundos de silencio continuo para cerrar la frase (0.5s).
        duracion_minima_seg (float): Duración mínima de un segmento de voz para procesarlo (0.5s).
        tasa_muestreo (int): Frecuencia de muestreo en Hz (16000Hz).
        tamano_frame_ms (int): Tamaño de cada bloque de lectura en ms (50ms).
        umbral_similitud (float): Umbral de similitud mínima para activar (0.85 = 85%).
    """
    wake_words = _obtener_wake_word_configurada()
    model = _get_model()

    default_device_idx = sd.default.device[0]
    if default_device_idx is None or default_device_idx < 0:
        logger.warning("[Wake Word]: No hay micrófono predeterminado disponible.")
        return

    samples_per_frame = int(tasa_muestreo * (tamano_frame_ms / 1000.0))
    frames_silencio_requeridos = int(silencio_confirmacion_seg / (tamano_frame_ms / 1000.0))
    frames_preroll_requeridos = max(1, int(preroll_seg / (tamano_frame_ms / 1000.0)))

    print(f"\n[Wake Word VAD]: Escuchando (Pre-roll: {preroll_seg}s | Umbral Similitud: {int(umbral_similitud*100)}%)... Di 'Jessyca' para activar.")

    en_habla = False
    buffer_frase = []
    buffer_preroll = deque(maxlen=frames_preroll_requeridos)
    consecutivos_silencio = 0

    with sd.InputStream(
        samplerate=tasa_muestreo,
        channels=1,
        dtype="int16",
        device=default_device_idx,
        blocksize=samples_per_frame
    ) as stream:
        while True:
            try:
                frame, overflowed = stream.read(samples_per_frame)
                if not len(frame):
                    continue

                amp_max = np.max(np.abs(frame))

                if amp_max >= umbral_amplitud:
                    if not en_habla:
                        en_habla = True
                        buffer_frase = list(buffer_preroll)
                        consecutivos_silencio = 0

                    buffer_frase.append(frame)
                    consecutivos_silencio = 0
                else:
                    if en_habla:
                        buffer_frase.append(frame)
                        consecutivos_silencio += 1

                        if consecutivos_silencio >= frames_silencio_requeridos:
                            # Fin de frase detectado por silencio sostenido
                            en_habla = False
                            audio_frase = np.concatenate(buffer_frase, axis=0)
                            buffer_frase = []
                            buffer_preroll.clear()
                            consecutivos_silencio = 0

                            duracion_real = len(audio_frase) / tasa_muestreo
                            if duracion_real < duracion_minima_seg:
                                continue

                            # Procesar la frase completa
                            temp_wav = None
                            try:
                                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                                    temp_wav = f.name

                                wavfile.write(temp_wav, tasa_muestreo, audio_frase)

                                segments, _ = model.transcribe(
                                    temp_wav,
                                    language="es",
                                    beam_size=1,
                                    condition_on_previous_text=False,
                                    vad_filter=True,
                                    no_speech_threshold=0.6
                                )
                                texto_transcrito = _normalizar_texto(" ".join([s.text for s in segments]))

                                es_coincidencia, sim_max = _es_coincidencia_wake_word(
                                    texto_transcrito,
                                    wake_words,
                                    umbral_similitud=umbral_similitud
                                )
                                sim_pct = sim_max * 100.0

                                print(f"[Wake Word VAD]: Segmento ({duracion_real:.2f}s) -> \"{texto_transcrito}\" | Similitud Máx: {sim_pct:.1f}%")
                                logger.info(f"[VAD Segment {duracion_real:.2f}s]: '{texto_transcrito}' (Similitud: {sim_pct:.1f}%)")

                                if es_coincidencia:
                                    print(f"\n[Wake Word Detectada]: '{texto_transcrito}' (Similitud: {sim_pct:.1f}%)")
                                    return

                            finally:
                                if temp_wav and os.path.exists(temp_wav):
                                    try:
                                        os.remove(temp_wav)
                                    except Exception:
                                        pass
                    else:
                        buffer_preroll.append(frame)

            except KeyboardInterrupt:
                print("\n[Wake Word]: Detección cancelada por el usuario.")
                return
            except Exception as e:
                logger.error(f"[Wake Word VAD Error]: {e}")
                time.sleep(0.1)
