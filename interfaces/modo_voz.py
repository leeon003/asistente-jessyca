"""interfaces/modo_voz.py
Interfaz de voz interactiva en tiempo real para JESSYCA con soporte de Sesión Continua (Fase 51)
y Motor de Captura Calibrada con Diagnósticos y Telemetría (Fase 51.1).

Captura audio desde el micrófono con pre-roll/post-roll e histeresis VAD, transcribe a texto en español,
procesa la orden con el Agente Local Unificado en múltiples turnos sin repetir wake word,
y responde con síntesis de voz (TTS) y feedback visual diferenciado.

Ejecutar con:
    python -m interfaces.modo_voz
"""

from __future__ import annotations

import os
import sys
import threading
import time

# Asegurar encoding UTF-8 en consola Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config.manager import get_settings
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import InputModality, JessycaRequest
from core.logger import get_logger
from services.voice.audio_capture import CalibratedVoiceCaptureEngine
from services.voice.continuous_voice_session import (
    ContinuousVoiceSession,
    VoiceSessionMode,
)
from services.voice.device_resolver import VoiceDeviceResolver
from services.voice.voice_diagnostics import VoiceDiscardReason

logger = get_logger("jessyca.interfaces.modo_voz")

BANNER_VOZ = r"""
  +===============================================================+
  |              J E S S Y C A   3 . 0  —  MODO VOZ               |
  |         Sesión Conversacional Continua (Fase 51 / 51.1)       |
  |                                                               |
  |   * Activa con: "Jessica, [tu orden]"                         |
  |   * Luego habla directamente sin repetir "Jessica"            |
  |   * Di "adios", "salir" o presiona Ctrl+C para finalizar.     |
  +===============================================================+
"""


class VoiceSpeaker:
    """Motor de síntesis de voz neuronal (Edge-TTS con es-PE-CamilaNeural) con fallback robusto."""

    def __init__(self, default_voice: str | None = None) -> None:
        self._lock = threading.Lock()
        settings = get_settings()
        self.voice_name = default_voice or getattr(settings, "VOICE_DEFAULT_VOICE", "es-PE-CamilaNeural")
        self._sapi_voice_id: str | None = None
        self._init_sapi_fallback()

    def _init_sapi_fallback(self) -> None:
        """Inicializa el fallback SAPI de Windows en caso de no haber conexión."""
        try:
            import pythoncom  # type: ignore[import-untyped]
            import win32com.client  # type: ignore[import-untyped]

            pythoncom.CoInitialize()
            sp = win32com.client.Dispatch("SAPI.SpVoice")
            voices = sp.GetVoices()
            for i in range(voices.Count):
                v = voices.Item(i)
                desc = v.GetDescription().lower()
                if "sabina" in desc or "spanish" in desc or "español" in desc or "mexico" in desc or "spain" in desc:
                    self._sapi_voice_id = v.Id
                    break
        except Exception as e:
            logger.debug(f"[VOICE TTS] Info al inicializar fallback SAPI: {e}")

    def speak(self, text: str) -> None:
        """Sintetiza y reproduce el texto con voz Camila Neural de forma no bloqueante/segura."""
        if not text or not text.strip():
            return

        with self._lock:
            # 1. Intentar con Edge-TTS (es-PE-CamilaNeural) y reproducción pygame
            try:
                import asyncio
                import io

                import edge_tts
                import pygame

                async def _synth() -> bytes:
                    communicate = edge_tts.Communicate(text.strip(), str(self.voice_name))
                    chunks: list[bytes] = []
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            chunks.append(chunk["data"])
                    return b"".join(chunks)

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import nest_asyncio  # type: ignore[import-not-found]

                        nest_asyncio.apply()
                    audio_bytes = loop.run_until_complete(_synth())
                except RuntimeError:
                    audio_bytes = asyncio.run(_synth())

                if audio_bytes:
                    if not pygame.mixer.get_init():
                        pygame.mixer.init()
                    sound = pygame.mixer.Sound(io.BytesIO(audio_bytes))
                    sound.play()
                    while pygame.mixer.get_busy():
                        pygame.time.wait(20)
                    return
            except Exception as e:
                logger.warning(f"[VOICE TTS] Edge-TTS ({self.voice_name}) falló ({e}), intentando fallback SAPI...")

            # 2. Fallback a SAPI (Sabina)
            try:
                import pythoncom
                import win32com.client

                pythoncom.CoInitialize()
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                if self._sapi_voice_id:
                    voices = speaker.GetVoices()
                    for i in range(voices.Count):
                        v = voices.Item(i)
                        if v.Id == self._sapi_voice_id:
                            speaker.Voice = v
                            break
                speaker.Rate = 1
                speaker.Volume = 100
                speaker.Speak(text.strip())
                return
            except Exception as ex2:
                logger.warning(f"[VOICE TTS] SAPI directo falló ({ex2}), intentando fallback con pyttsx3...")

            # 3. Fallback a pyttsx3
            try:
                import pyttsx3  # type: ignore[import-untyped]

                engine = pyttsx3.init()
                engine.setProperty("rate", 175)
                engine.say(text.strip())
                engine.runAndWait()
                engine.stop()
            except Exception as ex3:
                logger.error(f"[VOICE TTS FATAL] Fallo en todos los motores de voz: {ex3}")


def iniciar_modo_voz(
    show_header: bool = True,
    custom_banner: str | None = None,
    mcp_info: str | None = None,
) -> None:
    """Inicia el bucle interactivo de voz continua con JESSYCA."""
    if custom_banner:
        print(custom_banner)
    elif show_header:
        print(BANNER_VOZ)

    settings = get_settings()

    # 1. Diagnóstico e inspección de dispositivos de entrada con auto-detección (Fase 51.2)
    resolver = VoiceDeviceResolver()
    try:
        resolved_dev = resolver.resolve_input_device()
        speaker = VoiceSpeaker()
        fb_text = " (Fallback por señal)" if resolved_dev.fallback_used else ""
        print(f"  Micrófono: {resolved_dev.display_name} [Índice: {resolved_dev.index}]{fb_text}")
        if mcp_info:
            print(f"  MCP: {mcp_info}")
        print(f"  Voz: {speaker.voice_name}")
        logger.info(f"[DEMO] Microphone: {resolved_dev.display_name} (Index: {resolved_dev.index})")
        logger.info(f"[DEMO] TTS: {speaker.voice_name}")
    except Exception as e:
        print(f"\n  [ERROR] No se pudo encontrar micrófono de entrada: {e}")
        return

    # 2. Inicialización del motor de captura calibrado (Fases 51.1 y 51.2)
    try:
        capture_engine = CalibratedVoiceCaptureEngine(
            sample_rate=settings.VOICE_SAMPLE_RATE,
            channels=settings.VOICE_CHANNELS,
            pre_roll_ms=settings.VOICE_PRE_ROLL_MS,
            post_roll_ms=settings.VOICE_POST_ROLL_MS,
            min_speech_ms=settings.VOICE_MIN_SPEECH_MS,
            max_capture_ms=settings.VOICE_MAX_CAPTURE_MS,
            silence_timeout_ms=settings.VOICE_SILENCE_TIMEOUT_MS,
            confidence_threshold=settings.VOICE_STT_CONFIDENCE_THRESHOLD,
            language=settings.VOICE_STT_LANGUAGE,
            device_index=resolved_dev.index,
            device_resolver=resolver,
            resolved_device=resolved_dev,
        )
        print(f"  [Calibrando micrófono ({resolved_dev.display_name}) para ruido ambiente...]")
        calib_res = capture_engine.calibrate_ambient_noise(duration_sec=settings.VOICE_CALIBRATION_DURATION_SEC)
        print(f"  [Calibración completada | Ruido base: {calib_res.noise_floor_rms:.1f} RMS | Umbral VAD: {calib_res.recommended_start_threshold:.1f}]")
    except Exception as e:
        print(f"\n  [ERROR] No se pudo inicializar el micrófono: {e}")
        print("  Verifica que tu micrófono esté conectado y habilitado.")
        return

    agent = JessycaLocalAgent.get_instance()
    session_id = f"voice_interactive_{int(time.time())}"
    voice_session = ContinuousVoiceSession(
        session_id=session_id,
        conversation_idle_timeout=10.0,
    )

    saludo = "Hola, soy Jessyca. Di 'Jessica' seguido de tu orden, o habla directamente."
    print(f"\n  Jessyca: {saludo}\n")
    speaker.speak(saludo)

    consecutive_empty_count = 0

    while True:
        try:
            # Comprobar expiración por inactividad
            voice_session.check_timeout()

            if voice_session.mode in (VoiceSessionMode.CONVERSATION_ACTIVE, VoiceSessionMode.WAITING_FOR_FOLLOWUP):
                print(f"\n  [Conversación Continua Activa — Turno {voice_session.turns_count + 1} | Habla directamente...]")
            else:
                print("\n  [En espera de 'Jessica' | Habla ahora...]")

            logger.info(f"[VOICE_CAPTURE_STARTED] Modo: {voice_session.mode.value}...")
            capture_result = capture_engine.capture_and_transcribe(
                mode=voice_session.mode.value,
                timeout=7.0,
                phrase_time_limit=10.0,
            )
            logger.info(f"[VOICE_CAPTURE_STOPPED] Captura finalizada. Descarte: {capture_result.discard_reason.value}")

            # 3. Manejo de silencios normales en espera
            if capture_result.discard_reason == VoiceDiscardReason.NO_AUDIO:
                consecutive_empty_count += 1
                if consecutive_empty_count >= settings.VOICE_MAX_EMPTY_RETRIES:
                    if voice_session.mode != VoiceSessionMode.IDLE:
                        print("  [No se detectó actividad. Sesión en pausa hasta tu próxima llamada.]")
                    consecutive_empty_count = 0
                continue

            # 4. Manejo de fallos con feedback diferenciado
            if not capture_result.is_success:
                consecutive_empty_count += 1
                if capture_result.user_feedback_message:
                    print(f"  {capture_result.user_feedback_message}")
                continue

            # 5. Captura exitosa
            consecutive_empty_count = 0
            texto = capture_result.text
            logger.info(f"[VOICE_TRANSCRIPT] Texto reconocido: '{texto}' (Confianza: {capture_result.confidence:.2f})")
            print(f"\n  Tú (Voz): {texto}")

            # Comando de salida
            if texto.lower() in ("salir", "exit", "quit", "adios", "adiós", "terminar", "apágate", "cerrar"):
                despedida = "¡Hasta luego! Que tengas un excelente día."
                print(f"\n  Jessyca: {despedida}\n")
                speaker.speak(despedida)
                voice_session.end_session()
                break

            print("  [Intentando ejecutar...]")
            logger.info(f"[VOICE_EXECUTION_STARTED] Procesando petición de voz: '{texto}'")

            voice_session.on_processing_started()

            # Procesamiento con Agente Local JESSYCA
            req = JessycaRequest(
                session_id=session_id,
                user_input=texto,
                modality=InputModality.VOICE,
            )
            res = agent.interact(req)

            logger.info(f"[VOICE_EXECUTION_COMPLETED] Estado: {res.status.value}, Intent: {res.intent}, Skill: {res.selected_skill}")

            voice_session.on_speaking_started()

            if res.requires_clarification or res.status.value == "AWAITING_CLARIFICATION":
                msg = res.clarification_question or res.spoken_text or res.response_text or "¿Podrías aclararme qué deseas hacer?"
                print(f"\n  Jessyca (Aclaración): {msg}")
                speaker.speak(msg)
            elif res.requires_confirmation:
                msg = f"Atención: {res.response_text}. ¿Deseas autorizar esta acción?"
                print(f"\n  Jessyca (Confirmación): {msg}")
                speaker.speak(msg)
            else:
                msg = res.spoken_text or res.response_text
                print(f"\n  Jessyca: {msg}")
                speaker.speak(msg)

            voice_session.on_speaking_finished()
            # Breve pausa de estabilización de audio para evitar que el micrófono capture el eco del altavoz
            time.sleep(0.3)

            if os.getenv("VOICE_DEBUG", "").lower() in ("1", "true", "yes"):
                print(f"  [DEBUG | Intent: {res.intent} | Agent: {res.selected_agent} | Skill: {res.selected_skill} | Estado: {res.status.value} | Latencia: {res.metrics.total_latency_ms:.1f}ms]")

        except (KeyboardInterrupt, EOFError):
            despedida = "¡Hasta luego! Modo voz detenido."
            print(f"\n\n  Jessyca: {despedida}\n")
            speaker.speak(despedida)
            voice_session.end_session()
            break
        except Exception as e:
            logger.error(f"[MODO VOZ] Error en el ciclo de interacción: {e}")
            print(f"  [Error inesperado: {e}]")


if __name__ == "__main__":
    iniciar_modo_voz()
