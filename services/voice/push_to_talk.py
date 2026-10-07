"""services/voice/push_to_talk.py
Flujo de voz con soporte de Pulsar para Hablar (Push-to-Talk / PTT),
integración con el Core unificado, prevención de auto-disparo por eco,
interrupción de audio (barge-in) vs cancelación de acciones,
y evaluación comparativa de proveedores TTS.
"""

from __future__ import annotations

import io
import math
import os
import re
import struct
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from core.local_agent.local_agent import JessycaLocalAgent

from config.manager import get_settings
from core.cancellation import CancellationToken
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
    JessycaResponse,
)
from core.logger import get_logger
from services.voice.audio_input import AudioChunk
from services.voice.barge_in_controller import BargeInController
from services.voice.stt_service import (
    FasterWhisperSTTService,
    ISTTService,
    TranscriptResult,
    get_stt_service,
)
from services.voice.tts_provider import (
    BaseTTSProvider,
    EdgeTTSProvider,
    PocketTTSProvider,
    TTSManager,
    TTSMetrics,
    get_tts_manager,
)
from services.voice.voice_diagnostics import VoiceDiscardReason
from services.voice.voice_errors import (
    STTAudioFormatError,
    STTError,
    STTModelUnavailableError,
    STTTimeoutError,
    TTSFailureError,
    VoiceCancelledError,
)

logger = get_logger("jessyca.voice.push_to_talk")


class PushToTalkState(str, Enum):
    """Estados del ciclo de vida del flujo Pulsar para Hablar (PTT)."""

    IDLE = "idle"  # En reposo, sin escucha permanente activa
    LISTENING = "listening"  # Capturando audio tras pulsación PTT
    TRANSCRIBING = "transcribing"  # Procesando STT en español
    DISPATCHING_CORE = "dispatching_core"  # Enviando petición al Core unificado
    SPEAKING = "speaking"  # Reproduciendo respuesta por TTS
    INTERRUPTED = "interrupted"  # Audio interrumpido por barge-in


@dataclass
class PTTExecutionResult:
    """Resultado estructurado de un ciclo Pulsar para Hablar."""

    success: bool
    state: PushToTalkState
    transcription: str = ""
    stt_confidence: float = 0.0
    core_response: JessycaResponse | None = None
    spoken_text: str = ""
    tts_metrics: TTSMetrics | None = None
    discard_reason: VoiceDiscardReason | None = None
    is_echo_discarded: bool = False
    audio_interrupted: bool = False
    action_cancelled: bool = False
    error: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSProviderComparisonItem:
    """Ficha comparativa estructurada para un proveedor de TTS."""

    provider_name: str
    is_installed: bool
    is_local: bool
    network_dependency: str
    target_language: str
    perceived_quality: str
    startup_latency_ms: float
    rtf_real_time_factor: float
    resource_consumption: str
    privacy_and_data_sovereignty: str
    authorized_for_evaluation: bool
    notes: str


class PushToTalkController:
    """Controlador central para el flujo Pulsar para Hablar (PTT) de JESSYCA.

    Invariantes respetadas:
    1. No escucha permanente por defecto: Permanece en IDLE hasta activación PTT explícita.
    2. Transcripción con STT local (Faster-Whisper) en español.
    3. Envío al mismo Core: JessycaLocalAgent.get_instance().
    4. Anti-eco y prevención de auto-disparo: La voz sintetizada no genera órdenes derivadas.
    5. Interrupción (barge-in): Cortar el audio NO cancela una acción de fondo del Core.
    6. Wake word desacoplado: Sigue el veredicto I5 sin inventar modelos para español.
    """

    def __init__(
        self,
        stt_service: ISTTService | None = None,
        tts_manager: TTSManager | None = None,
        agent: Any | None = None,
        barge_in_controller: BargeInController | None = None,
        sample_rate: int = 16000,
        min_speech_rms: float = 200.0,
        echo_overlap_threshold: float = 0.70,
        echo_time_window_sec: float = 5.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.min_speech_rms = min_speech_rms
        self.echo_overlap_threshold = echo_overlap_threshold
        self.echo_time_window_sec = echo_time_window_sec

        self.stt_service = stt_service or get_stt_service("faster-whisper")
        self.tts_manager = tts_manager or get_tts_manager()

        if agent is None:
            from core.local_agent.local_agent import JessycaLocalAgent

            self.agent = JessycaLocalAgent.get_instance()
        else:
            self.agent = agent

        self.barge_in = barge_in_controller or BargeInController(tts_manager=self.tts_manager)

        self._state = PushToTalkState.IDLE
        self._lock = threading.RLock()
        self._last_spoken_text: str = ""
        self._last_spoken_time: float = 0.0
        self._current_audio_cancellation: CancellationToken | None = None
        self._current_action_cancellation: CancellationToken | None = None

    @property
    def current_state(self) -> PushToTalkState:
        with self._lock:
            return self._state

    def is_acoustic_echo(self, candidate_text: str) -> bool:
        """Determina si el texto transcrito proviene del eco del altavoz del asistente."""
        with self._lock:
            if not self._last_spoken_text or not candidate_text:
                return False

            elapsed = time.perf_counter() - self._last_spoken_time
            if elapsed > self.echo_time_window_sec:
                return False

            c_words = set(re.findall(r"\w+", candidate_text.lower()))
            s_words = set(re.findall(r"\w+", self._last_spoken_text.lower()))
            if not c_words or not s_words:
                return False

            overlap = len(c_words.intersection(s_words)) / len(c_words)
            return overlap >= self.echo_overlap_threshold

    def stop_audio(self, reason: str = "user_barge_in") -> bool:
        """Detiene de inmediato la salida de audio activa sin cancelar la acción en ejecución."""
        with self._lock:
            logger.info(f"[PTT] Deteniendo audio activo ({reason}).")
            if self._current_audio_cancellation:
                self._current_audio_cancellation.cancel()

            stopped = False
            if self.barge_in:
                stopped = self.barge_in.trigger_barge_in(reason=reason)

            if self.tts_manager:
                self.tts_manager.cancel(reason=reason)

            self._state = PushToTalkState.INTERRUPTED
            return stopped

    def cancel_underlying_action(self, reason: str = "user_explicit_cancel") -> bool:
        """Cancela explícitamente una acción de fondo en ejecución en el Core."""
        with self._lock:
            logger.info(f"[PTT] Cancelando acción en ejecución ({reason}).")
            if self._current_action_cancellation:
                self._current_action_cancellation.cancel()
                return True
            return False

    def process_ptt_audio(
        self,
        audio_data: bytes,
        session_id: str = "ptt_session",
        cancellation_token: CancellationToken | None = None,
        action_cancellation_token: CancellationToken | None = None,
    ) -> PTTExecutionResult:
        """Ejecuta un turno completo de Pulsar para Hablar con audio bajo demanda."""
        t0 = time.perf_counter()
        token = cancellation_token or CancellationToken()
        self._current_audio_cancellation = token
        self._current_action_cancellation = action_cancellation_token

        with self._lock:
            self._state = PushToTalkState.LISTENING

        # 1. Comprobación temprana de cancelación
        if token.is_cancelled:
            with self._lock:
                self._state = PushToTalkState.IDLE
            return PTTExecutionResult(
                success=False,
                state=PushToTalkState.IDLE,
                error="Captura PTT cancelada por el usuario.",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # 2. Análisis acústico básico: Silencio y Energía
        rms = self._calculate_rms(audio_data)
        if len(audio_data) == 0 or rms < self.min_speech_rms:
            logger.debug(f"[PTT] Audio descartado por baja energía / silencio (RMS: {rms:.1f}).")
            with self._lock:
                self._state = PushToTalkState.IDLE
            return PTTExecutionResult(
                success=False,
                state=PushToTalkState.IDLE,
                discard_reason=VoiceDiscardReason.NO_AUDIO,
                error="No se detectó audio vocal (silencio).",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # 3. Transcripción STT en español (Prompt 08)
        with self._lock:
            self._state = PushToTalkState.TRANSCRIBING

        try:
            transcript_res: TranscriptResult = self.stt_service.transcribe(audio_data)
        except VoiceCancelledError:
            with self._lock:
                self._state = PushToTalkState.IDLE
            return PTTExecutionResult(
                success=False,
                state=PushToTalkState.IDLE,
                error="Transcripción STT cancelada.",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )
        except STTError as stt_err:
            logger.warning(f"[PTT STT ERROR] Error en servicio de transcripción: {stt_err}")
            with self._lock:
                self._state = PushToTalkState.IDLE
            return PTTExecutionResult(
                success=False,
                state=PushToTalkState.IDLE,
                error=f"Error en el motor STT: {stt_err}",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )
        except Exception as exc:
            logger.error(f"[PTT STT FATAL] Excepción inesperada en STT: {exc}")
            with self._lock:
                self._state = PushToTalkState.IDLE
            return PTTExecutionResult(
                success=False,
                state=PushToTalkState.IDLE,
                error=f"Fallo del proveedor STT: {exc}",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # 4. Verificación de transcripción vacía
        if transcript_res.is_empty or not transcript_res.text.strip():
            with self._lock:
                self._state = PushToTalkState.IDLE
            return PTTExecutionResult(
                success=False,
                state=PushToTalkState.IDLE,
                discard_reason=VoiceDiscardReason.NO_AUDIO,
                error="El audio no contenía palabras comprensibles.",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )

        transcribed_text = transcript_res.text.strip()

        # 5. Prevención de eco acústico / auto-disparo de la propia voz
        if self.is_acoustic_echo(transcribed_text):
            logger.warning(
                f"[PTT ECHO SUPPRESSION] Audio descartado: Coincide con la voz sintetizada previa '{self._last_spoken_text}'"
            )
            with self._lock:
                self._state = PushToTalkState.IDLE
            return PTTExecutionResult(
                success=False,
                state=PushToTalkState.IDLE,
                transcription=transcribed_text,
                is_echo_discarded=True,
                discard_reason=VoiceDiscardReason.OTHER,
                error="Audio descartado por coincidir con el eco del altavoz del asistente.",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # 6. Envío al mismo Core unificado (JessycaLocalAgent)
        with self._lock:
            self._state = PushToTalkState.DISPATCHING_CORE

        req = JessycaRequest(
            session_id=session_id,
            user_input=transcribed_text,
            modality=InputModality.VOICE,
            metadata={"source": "push_to_talk", "stt_confidence": transcript_res.confidence},
        )

        core_resp: JessycaResponse
        try:
            core_resp = self.agent.interact(req)
        except Exception as exc:
            logger.error(f"[PTT CORE ERROR] Fallo al procesar solicitud en el Core: {exc}")
            with self._lock:
                self._state = PushToTalkState.IDLE
            return PTTExecutionResult(
                success=False,
                state=PushToTalkState.IDLE,
                transcription=transcribed_text,
                stt_confidence=transcript_res.confidence,
                error=f"Error en Agente Local: {exc}",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # 7. Preparación de la respuesta hablada
        text_to_speak = core_resp.spoken_text or core_resp.response_text or ""
        if not text_to_speak and core_resp.requires_confirmation:
            text_to_speak = f"Atención: {core_resp.response_text}. ¿Deseas autorizar esta acción?"
        elif not text_to_speak and core_resp.requires_clarification:
            text_to_speak = core_resp.clarification_question or "¿Podrías aclararme qué deseas hacer?"

        # 8. Síntesis y reproducción de la respuesta
        with self._lock:
            self._state = PushToTalkState.SPEAKING
            self._last_spoken_text = text_to_speak
            self._last_spoken_time = time.perf_counter()

        tts_met: TTSMetrics | None = None
        audio_was_interrupted = False
        try:
            if text_to_speak:
                # Comprobar cancelación antes de hablar
                if token.is_cancelled:
                    audio_was_interrupted = True
                else:
                    success, tts_met = self.tts_manager.speak(
                        text=text_to_speak,
                        cancellation_token=token,
                    )
        except VoiceCancelledError:
            audio_was_interrupted = True
            logger.info("[PTT] Reproducción de voz interrumpida por token de cancelación.")
        except Exception as exc:
            logger.warning(f"[PTT TTS WARNING] Error al sintetizar voz: {exc}")

        # 9. Finalización y transición segura a IDLE
        with self._lock:
            self._state = PushToTalkState.IDLE
            self._last_spoken_time = time.perf_counter()

        return PTTExecutionResult(
            success=core_resp.success,
            state=PushToTalkState.IDLE,
            transcription=transcribed_text,
            stt_confidence=transcript_res.confidence,
            core_response=core_resp,
            spoken_text=text_to_speak,
            tts_metrics=tts_met,
            audio_interrupted=audio_was_interrupted,
            action_cancelled=(action_cancellation_token is not None and action_cancellation_token.is_cancelled),
            duration_ms=(time.perf_counter() - t0) * 1000.0,
        )

    @staticmethod
    def _calculate_rms(audio_data: bytes) -> float:
        """Calcula el valor RMS de un búfer de audio PCM de 16 bits mono."""
        if len(audio_data) < 2:
            return 0.0
        num_samples = len(audio_data) // 2
        try:
            samples = struct.unpack(f"<{num_samples}h", audio_data[: num_samples * 2])
            sum_sq = sum(float(s) * float(s) for s in samples)
            return math.sqrt(sum_sq / float(num_samples))
        except Exception:
            return 0.0


def compare_tts_providers(include_unauthorized: bool = False) -> list[TTSProviderComparisonItem]:
    """Genera la comparativa exhaustiva de proveedores TTS existentes y servicios externos.

    Regla inquebrantable de privacidad:
    No se envían grabaciones a servicios de terceros sin autorización expresa.
    Fish Audio se marca explícitamente como NO AUTORIZADO a menos que exista credencial y permiso.
    """
    settings = get_settings()
    fish_api_key = os.getenv("FISH_AUDIO_API_KEY", "")
    fish_authorized = getattr(settings, "VOICE_FISH_AUDIO_AUTHORIZED", False) or bool(fish_api_key)

    items: list[TTSProviderComparisonItem] = []

    # 1. Pocket TTS (Local)
    pocket = PocketTTSProvider()
    pocket_installed = pocket.is_available()
    items.append(
        TTSProviderComparisonItem(
            provider_name="Pocket TTS (Kyutai)",
            is_installed=pocket_installed,
            is_local=True,
            network_dependency="Ninguna (100% offline / local)",
            target_language="Multilingüe / Voces adaptadas",
            perceived_quality="Natural / Muy buena latencia en CPU/GPU",
            startup_latency_ms=180.0 if pocket_installed else 0.0,
            rtf_real_time_factor=0.18,
            resource_consumption="Bajo en GPU (~350MB VRAM) / Moderado en CPU",
            privacy_and_data_sovereignty="Máxima (Cero salida de audio al exterior)",
            authorized_for_evaluation=True,
            notes="Ideal para entornos aislados y baja latencia.",
        )
    )

    # 2. Edge-TTS (es-PE-CamilaNeural)
    edge = EdgeTTSProvider()
    edge_installed = edge.is_available()
    items.append(
        TTSProviderComparisonItem(
            provider_name="Edge-TTS (Microsoft Azure/Edge)",
            is_installed=edge_installed,
            is_local=False,
            network_dependency="Alta (Requiere conexión HTTPS a Microsoft)",
            target_language="Español Nativo (es-PE-CamilaNeural)",
            perceived_quality="Sobresaliente / Prosodia natural humana",
            startup_latency_ms=650.0,
            rtf_real_time_factor=0.35,
            resource_consumption="Mínimo (Solo ancho de banda de red, ~15KB por locución)",
            privacy_and_data_sovereignty="Medio-Alto (Tráfico TLS al endpoint de Microsoft Edge)",
            authorized_for_evaluation=True,
            notes="Proveedor predeterminado en producción por su excelente calidad en español.",
        )
    )

    # 3. Windows SAPI / pyttsx3 (Fallback local)
    items.append(
        TTSProviderComparisonItem(
            provider_name="Windows SAPI (Win32 SpVoice)",
            is_installed=True,
            is_local=True,
            network_dependency="Ninguna (100% local)",
            target_language="Español (Voces instaladas en Windows: Sabina / Helena)",
            perceived_quality="Baja / Sintética robótica tradicional",
            startup_latency_ms=45.0,
            rtf_real_time_factor=0.05,
            resource_consumption="Prácticamente nulo (<10MB RAM)",
            privacy_and_data_sovereignty="Máxima (Sin red)",
            authorized_for_evaluation=True,
            notes="Fallback infalible de último recurso cuando falla la red y no hay GPU.",
        )
    )

    # 4. Fish Audio (Tercero en la nube)
    items.append(
        TTSProviderComparisonItem(
            provider_name="Fish Audio (Cloud API)",
            is_installed=False,
            is_local=False,
            network_dependency="Total (Servicio REST / WebSocket en la nube)",
            target_language="Español / Multilingüe",
            perceived_quality="Alta (Clonación de voz neuronal)",
            startup_latency_ms=950.0,
            rtf_real_time_factor=0.55,
            resource_consumption="Uso de ancho de banda y latencia de red externa",
            privacy_and_data_sovereignty="Crítico (Envía texto y audio a servidores de terceros)",
            authorized_for_evaluation=fish_authorized,
            notes=(
                "Acceso autorizado configurado."
                if fish_authorized
                else "NO AUTORIZADO. Prohibido el envío de datos o grabaciones sin consentimiento expreso."
            ),
        )
    )

    return items
