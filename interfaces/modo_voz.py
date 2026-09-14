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
from dataclasses import dataclass
from typing import Any

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
from core.state import StateMachine
from services.voice.audio_capture import CalibratedVoiceCaptureEngine
from services.voice.audio_device_manager import (
    SignalValidationStatus,
    get_audio_device_manager,
)
from services.voice.barge_in_controller import BargeInController
from services.voice.continuous_voice_session import (
    ContinuousVoiceSession,
    VoiceSessionMode,
)
from services.voice.device_resolver import VoiceDeviceResolver
from services.voice.stt_event_adapter import STTEventAdapter
from services.voice.tts_provider import get_tts_manager
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


@dataclass
class VoiceSpeakerMetrics:
    """Métricas de síntesis y reproducción de voz."""

    startup_latency_ms: float = 0.0
    duration_ms: float = 0.0
    engine_used: str = "edge_tts"
    voice_name: str = "es-PE-CamilaNeural"


class VoiceSpeaker:
    """Motor de síntesis de voz neuronal (Edge-TTS con es-PE-CamilaNeural) con fallback robusto."""

    def __init__(self, default_voice: str | None = None, barge_in_controller: Any | None = None) -> None:
        self._lock = threading.Lock()
        settings = get_settings()
        self.voice_name = default_voice or getattr(settings, "VOICE_DEFAULT_VOICE", "es-PE-CamilaNeural")
        self._sapi_speaker: Any = None
        self._sapi_voice_id: str | None = None
        self._pygame_ready = False
        self._tts_manager = get_tts_manager()
        self.barge_in_controller = barge_in_controller
        self._init_audio_system()

    def _init_audio_system(self) -> None:
        """Inicializa el subsistema de audio y mixer una sola vez para evitar overhead."""
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=1024)
            self._pygame_ready = True
        except Exception as e:
            logger.debug(f"[VOICE TTS] Info al inicializar pygame.mixer: {e}")
            self._pygame_ready = False

    def _get_sapi_speaker(self) -> Any:
        """Inicializa perezosamente y de forma persistente el fallback SAPI."""
        if self._sapi_speaker is not None:
            return self._sapi_speaker
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            sp = win32com.client.Dispatch("SAPI.SpVoice")
            voices = sp.GetVoices()
            for i in range(voices.Count):
                v = voices.Item(i)
                desc = v.GetDescription().lower()
                if "sabina" in desc or "spanish" in desc or "español" in desc or "mexico" in desc or "spain" in desc:
                    sp.Voice = v
                    self._sapi_voice_id = v.Id
                    break
            sp.Rate = 1
            sp.Volume = 100
            self._sapi_speaker = sp
            return self._sapi_speaker
        except Exception as e:
            logger.debug(f"[VOICE TTS] SAPI fallback no disponible: {e}")
            return None

    def speak(self, text: str, session_id: str | None = None) -> VoiceSpeakerMetrics:
        """Sintetiza y reproduce el texto mediante TTSManager con fallback transparente y mide latencias."""
        if not text or not text.strip():
            return VoiceSpeakerMetrics()

        clean_text = text.strip()
        metrics = VoiceSpeakerMetrics(voice_name=str(self.voice_name))
        t_start = time.perf_counter()

        if self.barge_in_controller:
            self.barge_in_controller.notify_tts_started(session_id=session_id)

        try:
            with self._lock:
                # 1. Motor Centralizado e Intercambiable: TTSManager (Pocket TTS -> Edge-TTS Camila Fallback)
                try:
                    success, tts_met = self._tts_manager.speak(clean_text, voice=str(self.voice_name))
                    if success:
                        metrics.startup_latency_ms = tts_met.t2_first_audio_ms or ((time.perf_counter() - t_start) * 1000.0)
                        metrics.duration_ms = tts_met.t4_audio_duration_ms
                        metrics.engine_used = tts_met.engine_used or tts_met.provider_used
                        return metrics
                except Exception as e:
                    logger.warning(f"[VOICE TTS] TTSManager falló ({e}), intentando fallback SAPI...")

            # 2. Fallback a SAPI
            try:
                sp = self._get_sapi_speaker()
                if sp:
                    t_play_start = time.perf_counter()
                    metrics.startup_latency_ms = (t_play_start - t_start) * 1000.0
                    sp.Speak(clean_text)
                    metrics.duration_ms = (time.perf_counter() - t_play_start) * 1000.0
                    metrics.engine_used = "sapi"
                    return metrics
            except Exception as ex2:
                logger.warning(f"[VOICE TTS] SAPI directo falló ({ex2}), intentando fallback con pyttsx3...")

            # 3. Fallback a pyttsx3
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", 175)
                t_play_start = time.perf_counter()
                metrics.startup_latency_ms = (t_play_start - t_start) * 1000.0
                engine.say(clean_text)
                engine.runAndWait()
                engine.stop()
                metrics.duration_ms = (time.perf_counter() - t_play_start) * 1000.0
                metrics.engine_used = "pyttsx3"
                return metrics
            except Exception as ex3:
                logger.error(f"[VOICE TTS FATAL] Fallo en todos los motores de voz: {ex3}")
                return metrics
        finally:
            if self.barge_in_controller:
                self.barge_in_controller.notify_tts_finished()


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

    # 1. Diagnóstico e inspección de dispositivos de entrada con AudioDeviceManager (Fase 71)
    device_manager = get_audio_device_manager()
    resolver = VoiceDeviceResolver()
    try:
        selected_desc = device_manager.select_device(validate_signal=True)
        resolved_dev = selected_desc.to_resolved_audio_device()
        speaker = VoiceSpeaker()

        # Log estructurado informativo (Fase 71 - Sección 14)
        val_status = "OK" if selected_desc.signal_status in (SignalValidationStatus.VALID, SignalValidationStatus.SILENT) else selected_desc.signal_status.value
        logger.info(
            f"AUDIO:\n"
            f"selected: {selected_desc.display_name}\n"
            f"runtime_index: {selected_desc.runtime_index}\n"
            f"host_api: {selected_desc.host_api}\n"
            f"input_channels: {selected_desc.max_input_channels}\n"
            f"validation: {val_status}"
        )

        fb_text = " (Fallback por señal)" if resolved_dev.fallback_used else ""
        print(f"  Micrófono: {selected_desc.display_name} [Índice temporal: {selected_desc.runtime_index}]{fb_text}")
        if mcp_info:
            print(f"  MCP: {mcp_info}")
        print(f"  Voz: {speaker.voice_name}")
        # Log estructurado de TTS (Fase 72)
        tts_mgr = get_tts_manager()
        active_tts = tts_mgr.get_active_provider()
        logger.info(
            f"TTS:\n"
            f"preferred: {tts_mgr.preferred_provider_name}\n"
            f"active: {active_tts.name}\n"
            f"fallback: {tts_mgr.fallback_provider_name}"
        )
        print(f"  TTS Motor: {active_tts.name} (Preferido: {tts_mgr.preferred_provider_name}, Fallback: {tts_mgr.fallback_provider_name})")
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
    state_machine = StateMachine(follow_up_window=10.0)
    stt_event_adapter = STTEventAdapter(state_machine=state_machine)
    barge_in_controller = BargeInController(
        tts_manager=tts_mgr,
        state_machine=state_machine,
        vad_service=capture_engine.vad_service,
    )
    speaker.barge_in_controller = barge_in_controller


    saludo = "Hola, soy Jessyca. Di 'Jessica' seguido de tu orden, o habla directamente."
    print(f"\n  Jessyca: {saludo}\n")
    speaker.speak(saludo, session_id=session_id)

    consecutive_empty_count = 0
    last_spoken_text = saludo
    last_spoken_time = time.perf_counter()

    def _is_acoustic_echo(captured_text: str, spoken_text: str, elapsed_sec: float) -> bool:
        if not spoken_text or not captured_text or elapsed_sec > 4.5:
            return False
        import re
        c_words = set(re.findall(r"\w+", captured_text.lower()))
        s_words = set(re.findall(r"\w+", spoken_text.lower()))
        if not c_words or not s_words:
            return False
        overlap = len(c_words.intersection(s_words)) / len(c_words)
        return overlap >= 0.70

    while True:
        try:
            # Comprobar expiración por inactividad
            voice_session.check_timeout()

            if voice_session.mode in (VoiceSessionMode.CONVERSATION_ACTIVE, VoiceSessionMode.WAITING_FOR_FOLLOWUP):
                print(f"\n  [Conversación Continua Activa — Turno {voice_session.turns_count + 1} | Habla directamente...]")
            else:
                print("\n  [En espera de 'Jessica' | Habla ahora...]")

            logger.info(f"[VOICE_CAPTURE_STARTED] Modo: {voice_session.mode.value}...")
            t_capture_start = time.perf_counter()
            capture_result = capture_engine.capture_and_transcribe(
                mode=voice_session.mode.value,
                timeout=7.0,
                phrase_time_limit=10.0,
            )
            stt_latency_ms = (time.perf_counter() - t_capture_start) * 1000.0
            logger.info(f"[VOICE_CAPTURE_STOPPED] Captura finalizada. Descarte: {capture_result.discard_reason.value}")

            # 3. Manejo de silencios normales en espera
            if capture_result.discard_reason == VoiceDiscardReason.NO_AUDIO:
                stt_event_adapter.process_transcript("")
                consecutive_empty_count += 1
                if consecutive_empty_count >= settings.VOICE_MAX_EMPTY_RETRIES:
                    if voice_session.mode != VoiceSessionMode.IDLE:
                        print("  [No se detectó actividad. Sesión en pausa hasta tu próxima llamada.]")
                    consecutive_empty_count = 0
                continue

            # 4. Manejo de fallos con feedback diferenciado
            if not capture_result.is_success:
                stt_event_adapter.process_transcript("")
                consecutive_empty_count += 1
                if capture_result.user_feedback_message:
                    print(f"  {capture_result.user_feedback_message}")
                continue

            # 5. Captura exitosa
            consecutive_empty_count = 0
            texto = capture_result.text

            # 5.1 Descarte de eco acústico del altavoz en conversación continua
            elapsed_since_speech = time.perf_counter() - last_spoken_time
            if (
                voice_session.mode in (VoiceSessionMode.CONVERSATION_ACTIVE, VoiceSessionMode.WAITING_FOR_FOLLOWUP)
                and _is_acoustic_echo(texto, last_spoken_text, elapsed_since_speech)
            ):
                logger.warning(
                    f"[VOICE_ECHO_DETECTED] Descartando eco acústico de la voz del asistente: '{texto}' "
                    f"(último mensaje: '{last_spoken_text}' hace {elapsed_since_speech:.2f}s)"
                )
                print(f"  [Eco acústico del altavoz detectado y descartado: '{texto}']")
                continue

            # Emitir evento UtteranceFinal y actualizar State Machine (Fase 67)
            stt_event_adapter.process_transcript(texto, confidence=capture_result.confidence)
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
            t_interact_start = time.perf_counter()
            req = JessycaRequest(
                session_id=session_id,
                user_input=texto,
                modality=InputModality.VOICE,
            )
            res = agent.interact(req)
            agent_latency_ms = (time.perf_counter() - t_interact_start) * 1000.0

            logger.info(f"[VOICE_EXECUTION_COMPLETED] Estado: {res.status.value}, Intent: {res.intent}, Skill: {res.selected_skill}")

            voice_session.on_speaking_started()

            if res.requires_clarification or res.status.value == "AWAITING_CLARIFICATION":
                msg = res.clarification_question or res.spoken_text or res.response_text or "¿Podrías aclararme qué deseas hacer?"
                print(f"\n  Jessyca (Aclaración): {msg}")
                tts_metrics = speaker.speak(msg, session_id=session_id)
            elif res.requires_confirmation:
                msg = f"Atención: {res.response_text}. ¿Deseas autorizar esta acción?"
                print(f"\n  Jessyca (Confirmación): {msg}")
                tts_metrics = speaker.speak(msg, session_id=session_id)
            else:
                msg = res.spoken_text or res.response_text
                print(f"\n  Jessyca: {msg}")
                tts_metrics = speaker.speak(msg, session_id=session_id)

            last_spoken_text = msg or ""
            last_spoken_time = time.perf_counter()
            voice_session.on_speaking_finished()

            # Medición y registro formal de latencias
            llm_latency_ms = res.metrics.model_inference_latency_ms if res.metrics.model_inference_latency_ms > 0 else agent_latency_ms
            tts_dur_ms = tts_metrics.duration_ms if tts_metrics else 0.0
            tts_start_ms = tts_metrics.startup_latency_ms if tts_metrics else 0.0
            total_turn_ms = stt_latency_ms + agent_latency_ms + tts_dur_ms

            logger.info(
                f"[VOICE_LATENCY] STT={stt_latency_ms:.1f}ms LLM={llm_latency_ms:.1f}ms "
                f"TTS_STARTUP={tts_start_ms:.1f}ms TTS={tts_dur_ms:.1f}ms TOTAL={total_turn_ms:.1f}ms"
            )
            print(
                f"  [VOICE_LATENCY] STT={stt_latency_ms:.1f}ms | LLM={llm_latency_ms:.1f}ms | "
                f"TTS={tts_dur_ms:.1f}ms | TOTAL={total_turn_ms:.1f}ms"
            )

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
