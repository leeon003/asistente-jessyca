"""
audio/tts.py
Módulo de Síntesis de Voz (Text-To-Speech) usando edge-tts de Microsoft.
Convierte texto a voz en español y reproduce el audio resultante por las bocinas.
"""
import asyncio
import logging
import os
import tempfile
import yaml
import edge_tts
import pygame

logger = logging.getLogger(__name__)

# Ruta por defecto al archivo de configuración de settings
CONFIG_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "settings.yaml"
)

VOICE_DEFAULT = "es-PE-CamilaNeural"


def _obtener_voz_configurada(ruta_config: str = CONFIG_SETTINGS_PATH) -> str:
    """Carga la voz configurada en settings.yaml, o retorna 'es-PE-CamilaNeural' por defecto."""
    if os.path.exists(ruta_config):
        try:
            with open(ruta_config, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "audio" in data and isinstance(data["audio"], dict):
                    voz = data["audio"].get("default_voice")
                    if voz and isinstance(voz, str):
                        return voz
        except Exception as e:
            logger.warning(f"Error al leer la voz de {ruta_config}: {e}")
    return VOICE_DEFAULT


async def _generar_audio_async(texto: str, ruta_salida: str, voz: str) -> None:
    """Genera el archivo MP3 usando la API asíncrona de edge-tts."""
    communicate = edge_tts.Communicate(texto, voz)
    await communicate.save(ruta_salida)


def _reproducir_audio(ruta_audio: str) -> None:
    """Reproduce el archivo de audio por la bocina usando pygame.mixer."""
    try:
        pygame.mixer.init()
        pygame.mixer.music.load(ruta_audio)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
    finally:
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass


def hablar(texto: str) -> bool:
    """
    Sintetiza y reproduce por bocina el texto dado usando edge-tts.

    Args:
        texto (str): Mensaje a reproducir en voz alta.

    Returns:
        bool: True si la reproducción fue exitosa, False si ocurrió un error (ej. sin conexión).
    """
    if not texto or not str(texto).strip():
        return False

    voz = _obtener_voz_configurada()
    temp_file = None

    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_file = f.name

        # Sintetizar audio asíncronamente
        asyncio.run(_generar_audio_async(texto, temp_file, voz))

        # Reproducir audio
        _reproducir_audio(temp_file)
        return True

    except Exception as e:
        mensaje_error = f"[TTS - Error de conexión/voz]: No se pudo reproducir audio ({e})."
        logger.error(mensaje_error)
        print(f"\n{mensaje_error}")
        return False
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
