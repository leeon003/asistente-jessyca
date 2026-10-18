"""Puente de Integración Unificado para JESSYCA ORB — Núcleo Aurora 3D & Fusión Reactiva.

Conecta el orbe visual existente con la arquitectura real de JESSYCA 4.0:
1. Máquina de Estados (StateMachine): Mapeo 1:1 de SessionState a estados visuales.
2. Bus de Eventos (EventBus): Suscripción a eventos reales (WakeWord, STT, Intent, Actions, Verification, TTS, Barge-in, Errors).
3. Sincronización Acústica del Micrófono: Cálculo suave de RMS y amplitud sin doble captura ni interferencia con VAD/Whisper.
4. Sincronización de Voz JESSYCA (TTS): Modulación del ecualizador radial de 44 barras durante locución y corte por barge-in.
5. Telemetría Cognitiva y Herramientas: Detección de búsquedas web (SEARCHING), ejecución (EXECUTING) y verificación (VERIFYING).
6. Blindaje de Razonamiento: Los canales internos de pensamiento (<think>) nunca se exponen al usuario ni al HUD.
"""

from __future__ import annotations

import math
import struct
import threading
import time
from typing import Any, Callable

from core.bus import EventBus
from core.events.base import (
    ActionExecuted,
    ActionProposed,
    AudioCaptured,
    ClarificationRequested,
    ErrorOccurred,
    IntentClassified,
    SpeakRequested,
    UserInterrupted,
    UtteranceFinal,
    VerificationResult,
    WakeWordDetected,
)
from core.logger import get_logger
from core.state.context import StateContext
from core.state.machine import StateMachine
from core.state.states import SessionState
from interfaces.aurora.audio_adapter import AuroraAudioAdapter
from interfaces.aurora.server import AuroraServerManager
from interfaces.aurora.visual_states import (
    AuroraVisualState,
    SessionStateToAuroraAdapter,
)

logger = get_logger("jessyca.aurora.bridge")

SEARCH_TOOL_PREFIXES = (
    "browser.search",
    "browser.navigate",
    "browser.read",
    "browser.youtube",
    "files.search",
    "search",
    "buscar_archivo",
    "web_search",
    "google_search",
    "research",
)


class AuroraBridge:
    """Puente desacoplado y reactivo entre el cerebro de JESSYCA y el Orbe Aurora."""

    _instance: AuroraBridge | None = None

    def __init__(
        self,
        server_manager: AuroraServerManager | None = None,
        state_machine: StateMachine | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.server_manager = server_manager or AuroraServerManager(port=8765)
        self.state_machine = state_machine
        self.event_bus = event_bus
        self.audio_adapter = AuroraAudioAdapter()

        # Telemetría acústica suavizada (Filtro EMA)
        self._smoothed_amplitude: float = 0.0
        self._alpha_mic: float = 0.40  # Factor de suavizado para entrada de micro
        self._alpha_tts: float = 0.55  # Factor de suavizado para salida TTS

        # Control de locución TTS activa
        self._is_tts_playing: bool = False
        self._tts_playback_thread: threading.Thread | None = None
        self._tts_stop_event = threading.Event()

        # Temporizador de recuperación visual de errores
        self._error_timer: threading.Timer | None = None
        self._state_listeners: list[Callable[[AuroraVisualState], None]] = []
        self._lock = threading.Lock()

        # Si se proveyeron instancias en __init__, conectar de inmediato
        if self.state_machine:
            self.attach_state_machine(self.state_machine)
        if self.event_bus:
            self.attach_event_bus(self.event_bus)

    @classmethod
    def get_instance(
        cls,
        server_manager: AuroraServerManager | None = None,
        state_machine: StateMachine | None = None,
        event_bus: EventBus | None = None,
    ) -> AuroraBridge:
        """Obtiene o inicializa la instancia singleton del bridge."""
        if cls._instance is None:
            cls._instance = cls(
                server_manager=server_manager,
                state_machine=state_machine,
                event_bus=event_bus,
            )
        else:
            if server_manager and not cls._instance.server_manager:
                cls._instance.server_manager = server_manager
            if state_machine:
                cls._instance.attach_state_machine(state_machine)
            if event_bus:
                cls._instance.attach_event_bus(event_bus)
        return cls._instance

    # ── 1. CONEXIÓN CON STATE MACHINE ──────────────────────────────────────────

    def attach_state_machine(self, state_machine: StateMachine) -> None:
        """Conecta la máquina de estados suscribiéndose a las entradas de cada estado."""
        self.state_machine = state_machine
        for state in SessionState:
            def _make_handler(s: SessionState) -> Callable[[StateContext], None]:
                return lambda ctx: self._on_session_state_entered(s, ctx)
            state_machine.on_enter(state, _make_handler(state))
        logger.info("[AURORA BRIDGE] StateMachine conectada exitosamente a los 10 estados canónicos.")

    def _on_session_state_entered(self, session_state: SessionState, ctx: StateContext) -> None:
        """Maneja la entrada a un estado formal de la sesión."""
        # Si estamos en reproducción de TTS no forzar sobreescrituras espurias de audio
        if session_state == SessionState.RESPONDING:
            self.notify_state_change(AuroraVisualState.RESPONDING)
            return

        target_visual = SessionStateToAuroraAdapter.to_granular_visual_state(session_state)
        self.notify_state_change(target_visual)

    # ── 2. CONEXIÓN CON EVENT BUS ──────────────────────────────────────────────

    def attach_event_bus(self, event_bus: EventBus) -> None:
        """Suscribe el orbe a todos los eventos relevantes del ciclo de vida de JESSYCA."""
        self.event_bus = event_bus

        event_bus.subscribe(WakeWordDetected, self._on_wakeword_detected)
        event_bus.subscribe(AudioCaptured, self._on_audio_captured)
        event_bus.subscribe(UtteranceFinal, self._on_utterance_final)
        event_bus.subscribe(IntentClassified, self._on_intent_classified)
        event_bus.subscribe(ActionProposed, self._on_action_proposed)
        event_bus.subscribe(ActionExecuted, self._on_action_executed)
        event_bus.subscribe(VerificationResult, self._on_verification_result)
        event_bus.subscribe(SpeakRequested, self._on_speak_requested)
        event_bus.subscribe(UserInterrupted, self._on_user_interrupted)
        event_bus.subscribe(ClarificationRequested, self._on_clarification_requested)
        event_bus.subscribe(ErrorOccurred, self._on_error_occurred)

        logger.info("[AURORA BRIDGE] EventBus conectado: 11 tipos de eventos tipados suscritos.")

    def _on_wakeword_detected(self, event: WakeWordDetected) -> None:
        logger.info(f"[AURORA BRIDGE] WakeWord detectada ('{event.wake_word}'). Disparando expansión visual.")
        self.notify_state_change(AuroraVisualState.WAKEWORD)
        self.trigger_accent(boost=1.5, color="#00F0FF")

    def _on_audio_captured(self, event: AudioCaptured) -> None:
        if event.audio_data:
            self.on_pcm_chunk(event.audio_data)

    def _on_utterance_final(self, event: UtteranceFinal) -> None:
        logger.info(f"[AURORA BRIDGE] STT Finalizado: '{event.text[:40]}...'. Transición a TRANSCRIBING.")
        self.notify_state_change(AuroraVisualState.TRANSCRIBING)

    def _on_intent_classified(self, event: IntentClassified) -> None:
        logger.info(f"[AURORA BRIDGE] Intención clasificada: '{event.intent}'. Transición a ROUTING.")
        self.notify_state_change(AuroraVisualState.ROUTING)

    def _on_action_proposed(self, event: ActionProposed) -> None:
        action_lower = event.action_name.lower()
        is_search = any(action_lower.startswith(prefix) for prefix in SEARCH_TOOL_PREFIXES)
        if is_search:
            logger.info(f"[AURORA BRIDGE] Acción de búsqueda propuesta: '{event.action_name}'. Activando SEARCHING.")
            self.notify_state_change(AuroraVisualState.SEARCHING)
        else:
            logger.info(f"[AURORA BRIDGE] Acción propuesta: '{event.action_name}'. Activando EXECUTING.")
            self.notify_state_change(AuroraVisualState.EXECUTING)
        self.trigger_accent(boost=1.0)

    def _on_action_executed(self, event: ActionExecuted) -> None:
        logger.info(f"[AURORA BRIDGE] Acción ejecutada: '{event.action_name}' (Success: {event.success}). Transición a VERIFYING.")
        self.notify_state_change(AuroraVisualState.VERIFYING)

    def _on_verification_result(self, event: VerificationResult) -> None:
        logger.info(f"[AURORA BRIDGE] Verificación recibida: {event.status} (Verified: {event.verified}).")
        if event.verified:
            self.trigger_accent(boost=1.2, color="#70D9FF")
        self.notify_state_change(AuroraVisualState.VERIFYING)

    def _on_speak_requested(self, event: SpeakRequested) -> None:
        logger.info(f"[AURORA BRIDGE] SpeakRequested recibido ({len(event.text)} caracteres).")
        self.notify_state_change(AuroraVisualState.RESPONDING)

    def _on_user_interrupted(self, event: UserInterrupted) -> None:
        logger.info(f"[AURORA BRIDGE] Barge-in detectado (Razón: '{event.reason}'). Interrumpiendo habla de inmediato.")
        self.notify_tts_end(interrupted=True)

    def _on_clarification_requested(self, event: ClarificationRequested) -> None:
        logger.info("[AURORA BRIDGE] Solicitud de aclaración activa. Transición a CLARIFYING.")
        self.notify_state_change(AuroraVisualState.CLARIFYING)

    def _on_error_occurred(self, event: ErrorOccurred) -> None:
        logger.warning(f"[AURORA BRIDGE] Error detectado: {event.error_type} - {event.error_message}")
        self.notify_error(duration_sec=2.5)

    # ── 3. SINCRONIZACIÓN DE AUDIO CON EL MICRÓFONO ────────────────────────────

    def on_pcm_chunk(self, pcm_bytes: bytes, sample_rate: int = 16000, sample_width: int = 2) -> None:
        """Procesa de forma continua los paquetes PCM capturados por el micrófono real.

        Aplica normalización e interpolación exponencial suave para evitar sobresaltos en los shaders.
        """
        if not pcm_bytes or len(pcm_bytes) < sample_width:
            return

        metrics = self.audio_adapter.process_pcm_chunk(
            pcm_bytes=pcm_bytes,
            sample_rate=sample_rate,
            sample_width=sample_width,
        )

        # Filtro de Suavizado Exponencial (EMA)
        raw_amp = metrics.normalized_amplitude
        with self._lock:
            self._smoothed_amplitude = (self._alpha_mic * raw_amp) + ((1.0 - self._alpha_mic) * self._smoothed_amplitude)
            current_amp = self._smoothed_amplitude

        # Difundir métricas al servidor WebSocket
        payload = {
            "rms": round(metrics.rms, 2),
            "normalized_amplitude": round(current_amp, 4),
            "voice_detected": metrics.voice_detected,
            "dominant_frequency_hz": round(metrics.dominant_frequency_hz, 1),
            "tts_playback_active": self._is_tts_playing,
            "is_simulated": False,
        }
        self.server_manager.broadcast_audio_metrics_sync(payload)

    # ── 4. SINCRONIZACIÓN CON LA VOZ DE JESSYCA (TTS) ──────────────────────────

    def notify_tts_start(self, text: str = "", audio_bytes: bytes | None = None) -> None:
        """Notifica el inicio de la reproducción de audio del TTS."""
        with self._lock:
            self._is_tts_playing = True
            self._tts_stop_event.clear()

        self.audio_adapter.notify_tts_playback_start()
        self.notify_state_change(AuroraVisualState.RESPONDING)

        # Iniciar hilo de modulación acústica durante la locución real
        self._tts_playback_thread = threading.Thread(
            target=self._tts_acoustic_modulation_worker,
            args=(audio_bytes,),
            daemon=True,
            name="AuroraTTSModulationWorker",
        )
        self._tts_playback_thread.start()

    def _tts_acoustic_modulation_worker(self, audio_bytes: bytes | None = None) -> None:
        """Modula en tiempo real la envolvente de la voz para el ecualizador y pulsaciones del orbe."""
        t_start = time.time()

        # Si tenemos los bytes PCM/WAV reales del audio sintetizado, extraer envolvente física
        chunks_rms: list[float] = []
        if audio_bytes and len(audio_bytes) > 200:
            try:
                # Omitir cabecera WAV típica de 44 bytes si existe
                raw_pcm = audio_bytes[44:] if audio_bytes.startswith(b"RIFF") else audio_bytes
                chunk_len = 1600  # ~50ms a 16kHz 16-bit
                for i in range(0, len(raw_pcm) - chunk_len, chunk_len):
                    sub = raw_pcm[i:i + chunk_len]
                    num_s = len(sub) // 2
                    samples = struct.unpack(f"<{num_s}h", sub[:num_s * 2])
                    sum_sq = sum(s * s for s in samples)
                    rms = math.sqrt(sum_sq / num_s) if num_s > 0 else 0.0
                    chunks_rms.append(min(1.0, max(0.08, (rms - 100.0) / 12000.0)))
            except Exception:
                chunks_rms = []

        chunk_idx = 0
        while not self._tts_stop_event.is_set():
            elapsed = time.time() - t_start

            if chunks_rms and chunk_idx < len(chunks_rms):
                target_amp = chunks_rms[chunk_idx]
                chunk_idx += 1
            else:
                # Modulación silábica natural continua (~4.25 Hz con micro-pausas)
                sim = self.audio_adapter.generate_simulated_metrics(AuroraVisualState.SPEAKING, elapsed)
                target_amp = sim.normalized_amplitude

            with self._lock:
                self._smoothed_amplitude = (self._alpha_tts * target_amp) + ((1.0 - self._alpha_tts) * self._smoothed_amplitude)
                current_amp = self._smoothed_amplitude

            self.server_manager.broadcast_audio_metrics_sync({
                "rms": round(current_amp * 12000.0, 2),
                "normalized_amplitude": round(current_amp, 4),
                "voice_detected": False,
                "tts_playback_active": True,
                "dominant_frequency_hz": 215.0,
                "is_simulated": not bool(chunks_rms),
            })
            time.sleep(0.035)  # ~28 Hz de refresco de envolvente

    def notify_tts_end(self, interrupted: bool = False) -> None:
        """Notifica el cese de la reproducción de voz del TTS."""
        with self._lock:
            self._is_tts_playing = False
            self._tts_stop_event.set()

        self.audio_adapter.notify_tts_playback_end()

        # Enviar nivel cero inmediato
        self.server_manager.broadcast_audio_metrics_sync({
            "rms": 0.0,
            "normalized_amplitude": 0.0,
            "tts_playback_active": False,
            "is_simulated": False,
        })

        if interrupted:
            logger.info("[AURORA BRIDGE] Locución interrumpida. Disparando choque de interrupción y regresando a LISTENING.")
            self.trigger_accent(boost=1.6, color="#00F0FF")
            self.notify_state_change(AuroraVisualState.LISTENING)
        else:
            # Si hay seguimiento continuo o reposo
            next_state = AuroraVisualState.IDLE
            if self.state_machine and self.state_machine.current_state != SessionState.RESPONDING:
                next_state = SessionStateToAuroraAdapter.to_granular_visual_state(self.state_machine.current_state)
            self.notify_state_change(next_state)

    # ── 5. ACTIVIDAD DEL CEREBRO Y HERRAMIENTAS ────────────────────────────────

    def notify_cognition(self, stage: str = "reasoning") -> None:
        """Notifica actividad interna de razonamiento, planificación o memoria."""
        if stage in ("searching", "investigating"):
            self.notify_state_change(AuroraVisualState.SEARCHING)
        elif stage in ("planning", "routing"):
            self.notify_state_change(AuroraVisualState.ROUTING)
        else:
            self.notify_state_change(AuroraVisualState.ROUTING)

    def notify_tool_start(self, tool_name: str) -> None:
        """Notifica el inicio de ejecución de una herramienta o skill."""
        t_low = tool_name.lower()
        if any(t_low.startswith(p) for p in SEARCH_TOOL_PREFIXES):
            self.notify_state_change(AuroraVisualState.SEARCHING)
        else:
            self.notify_state_change(AuroraVisualState.EXECUTING)
        self.trigger_accent(boost=0.85)

    def notify_verification(self, verified: bool = True) -> None:
        """Notifica la fase de escaneo y verificación de resultados."""
        self.notify_state_change(AuroraVisualState.VERIFYING)
        if verified:
            self.trigger_accent(boost=1.1, color="#70D9FF")

    def notify_error(self, duration_sec: float = 2.5) -> None:
        """Activa una alerta visual ámbar breve y restaura automáticamente el reposo."""
        if self._error_timer:
            self._error_timer.cancel()

        self.notify_state_change(AuroraVisualState.ERROR)

        def _recover() -> None:
            logger.info("[AURORA BRIDGE] Recuperación de error completada. Regresando a IDLE.")
            self.notify_state_change(AuroraVisualState.IDLE)

        self._error_timer = threading.Timer(duration_sec, _recover)
        self._error_timer.daemon = True
        self._error_timer.start()

    # ── 6. CONTROL VISUAL DIRECTO Y DESPACHO SEGURO ────────────────────────────

    def notify_state_change(self, state: AuroraVisualState | str) -> None:
        """Difunde el nuevo estado de manera segura y no bloqueante a los clientes WebSocket."""
        try:
            target = state if isinstance(state, AuroraVisualState) else AuroraVisualState(str(state).upper())
        except ValueError:
            target = SessionStateToAuroraAdapter.to_granular_visual_state(str(state))

        logger.debug(f"[AURORA BRIDGE] Broadcast visual: {target.value}")
        self.server_manager.broadcast_state_sync(target)

        # Notificar a los observadores registrados
        with self._lock:
            listeners = list(self._state_listeners)
        for listener in listeners:
            try:
                listener(target)
            except Exception as e:
                logger.debug(f"[AURORA BRIDGE] Error en state_listener: {e}")

    def add_state_listener(self, listener: Callable[[AuroraVisualState], None]) -> None:
        """Registra un observador que recibe cambios de estado visual."""
        with self._lock:
            if listener not in self._state_listeners:
                self._state_listeners.append(listener)

    def remove_state_listener(self, listener: Callable[[AuroraVisualState], None]) -> None:
        """Elimina un observador de estados visuales."""
        with self._lock:
            if listener in self._state_listeners:
                self._state_listeners.remove(listener)

    def trigger_accent(self, boost: float = 1.0, color: str | None = None) -> None:
        """Dispara un pulso de onda de choque hiperreactivo en el orbe."""
        self.server_manager.broadcast_accent_sync(boost=boost, color=color)

    def close(self) -> None:
        """Limpia los temporizadores y detiene los hilos secundarios del bridge."""
        with self._lock:
            self._tts_stop_event.set()
            if self._error_timer:
                self._error_timer.cancel()
        logger.info("[AURORA BRIDGE] Recursos del bridge liberados limpiamente.")
