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
from services.voice.audio_capture import (
    CalibratedVoiceCaptureEngine,
    MicrophoneDiagnostics,
)
from services.voice.continuous_voice_session import (
    ContinuousVoiceSession,
    VoiceSessionMode,
)
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
    """Motor de síntesis de voz (TTS) para respuestas habladas."""

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()
        self._init_tts()

    def _init_tts(self) -> None:
        try:
            import pyttsx3  # type: ignore[import-untyped]

            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            # Buscar voz en español (ej. Sabina o cualquier voz 'es')
            selected_voice = None
            for v in voices:
                v_name = getattr(v, "name", "").lower()
                v_id = getattr(v, "id", "").lower()
                if "spanish" in v_name or "sabina" in v_name or "es-" in v_id or "es_" in v_id:
                    selected_voice = v.id
                    break
            if selected_voice:
                engine.setProperty("voice", selected_voice)
            engine.setProperty("rate", 175)  # Velocidad natural
            self._engine = engine
        except Exception as e:
            logger.warning(f"[VOICE TTS] Fallback a motor SAPI directo: {e}")
            self._engine = None

    def speak(self, text: str) -> None:
        """Sintetiza y reproduce el texto por los altavoces de forma no bloqueante o controlada."""
        if not text or not text.strip():
            return

        def _run_speak() -> None:
            with self._lock:
                try:
                    if self._engine:
                        self._engine.say(text)
                        self._engine.runAndWait()
                    else:
                        # Fallback a Windows SAPI directo vía win32com
                        import win32com.client  # type: ignore[import-untyped]

                        speaker = win32com.client.Dispatch("SAPI.SpVoice")
                        speaker.Speak(text)
                except Exception as e:
                    logger.error(f"[VOICE TTS] Error al reproducir voz: {e}")

        # Ejecutar en hilo desacoplado
        t = threading.Thread(target=_run_speak, daemon=True)
        t.start()
        t.join(timeout=15.0)


def iniciar_modo_voz() -> None:
    """Inicia el bucle interactivo de voz continua con JESSYCA."""
    print(BANNER_VOZ)

    settings = get_settings()

    # 1. Diagnóstico e inspección de dispositivos de entrada
    default_dev = MicrophoneDiagnostics.get_default_device()
    print(f"  [Dispositivo de Micrófono: {default_dev.name} | Frecuencia: {settings.VOICE_SAMPLE_RATE}Hz]")

    speaker = VoiceSpeaker()

    # 2. Inicialización del motor de captura calibrado (Fase 51.1)
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
        )
        print("  [Calibrando micrófono para ruido ambiente...]")
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

            if res.requires_clarification and res.clarification_question:
                msg = res.clarification_question
                print(f"\n  Jessyca (Aclaración): {msg}")
                speaker.speak(msg)
            elif res.requires_confirmation:
                msg = f"Atención: {res.response_text}. ¿Deseas autorizar esta acción?"
                print(f"\n  Jessyca (Confirmación): {msg}")
                speaker.speak(msg)
            else:
                msg = res.response_text
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
