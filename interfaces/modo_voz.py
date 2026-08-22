"""interfaces/modo_voz.py
Interfaz de voz interactiva en tiempo real para JESSYCA con soporte de Sesión Continua (Fase 51).
Captura audio desde el micrófono, transcribe la voz a texto (STT),
procesa la orden con el Agente Local Unificado de JESSYCA en múltiples turnos sin repetir wake word,
y responde con síntesis de voz (TTS) y texto en pantalla.

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

from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import InputModality, JessycaRequest
from core.logger import get_logger
from services.voice.continuous_voice_session import (
    ContinuousVoiceSession,
    VoiceSessionMode,
)

logger = get_logger("jessyca.interfaces.modo_voz")

BANNER_VOZ = r"""
  +===============================================================+
  |              J E S S Y C A   3 . 0  —  MODO VOZ               |
  |         Sesión Conversacional Continua (Fase 51)              |
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
            import pyttsx3
            self._engine = pyttsx3.init()
            voices = self._engine.getProperty("voices")
            # Buscar voz en español (ej. Sabina o cualquier voz 'es')
            selected_voice = None
            for v in voices:
                if "spanish" in v.name.lower() or "sabina" in v.name.lower() or "es-" in v.id.lower() or "es_" in v.id.lower():
                    selected_voice = v.id
                    break
            if selected_voice:
                self._engine.setProperty("voice", selected_voice)
            self._engine.setProperty("rate", 175)  # Velocidad natural
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
                        import win32com.client
                        speaker = win32com.client.Dispatch("SAPI.SpVoice")
                        speaker.Speak(text)
                except Exception as e:
                    logger.error(f"[VOICE TTS] Error al reproducir voz: {e}")

        # Ejecutar en hilo desacoplado
        t = threading.Thread(target=_run_speak, daemon=True)
        t.start()
        t.join(timeout=15.0)


class VoiceListener:
    """Motor de reconocimiento de voz (STT) desde micrófono."""

    def __init__(self) -> None:
        import speech_recognition as sr
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.8
        self.microphone = sr.Microphone()

        # Calibrar ruido ambiente inicial
        try:
            with self.microphone as source:
                print("  [Calibrando microfono para ruido ambiente...]")
                self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
        except Exception as e:
            logger.warning(f"[VOICE STT] Advertencia calibrando microfono: {e}")

    def listen_user(self, timeout: float = 8.0, phrase_time_limit: float = 12.0) -> str | None:
        """Escucha el micrófono del usuario y retorna el texto transcrito en español."""
        import speech_recognition as sr
        try:
            with self.microphone as source:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)

            print("  [Procesando voz...]")
            # Transcripción con Google Speech Recognition en español
            text = self.recognizer.recognize_google(audio, language="es-ES")
            return text.strip()
        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return ""  # No se entendió el audio
        except sr.RequestError as e:
            logger.error(f"[VOICE STT] Error del servicio STT: {e}")
            return None
        except Exception as e:
            logger.error(f"[VOICE STT] Error general de microfono: {e}")
            return None


def iniciar_modo_voz() -> None:
    """Inicia el bucle interactivo de voz continua con JESSYCA."""
    print(BANNER_VOZ)

    speaker = VoiceSpeaker()
    try:
        listener = VoiceListener()
    except Exception as e:
        print(f"\n  [ERROR] No se pudo inicializar el micrófono: {e}")
        print("  Verifica que tu micrófono esté conectado.")
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

    while True:
        try:
            # Comprobar expiración por inactividad
            voice_session.check_timeout()

            if voice_session.mode in (VoiceSessionMode.CONVERSATION_ACTIVE, VoiceSessionMode.WAITING_FOR_FOLLOWUP):
                print(f"\n  [Conversación Continua Activa — Turno {voice_session.turns_count + 1} | Habla directamente...]")
            else:
                print("\n  [En espera de 'Jessica' | Habla ahora...]")

            logger.info(f"[VOICE_CAPTURE_STARTED] Modo: {voice_session.mode.value}...")
            texto = listener.listen_user(timeout=7.0, phrase_time_limit=10.0)
            logger.info("[VOICE_CAPTURE_STOPPED] Captura de audio finalizada.")

            if texto is None:
                continue

            if texto == "":
                print("  [No se detectó voz clara. Intenta de nuevo...]")
                continue

            logger.info(f"[VOICE_TRANSCRIPT] Texto reconocido: '{texto}'")
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

            if os.getenv("VOICE_DEBUG", "").lower() in ("1", "true", "yes"):
                print(f"  [DEBUG | Intent: {res.intent} | Confidence: {res.intent_confidence:.2f} | Agent: {res.selected_agent} | Skill: {res.selected_skill} | Estado: {res.status.value} | Latencia: {res.metrics.total_latency_ms:.1f}ms]")

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
