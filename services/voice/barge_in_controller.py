"""Controlador de Interrupciones y Barge-in (barge_in_controller.py - Fase 73).

Permite al usuario interrumpir a JESSYCA mientras está hablando (TTS activo)
o cancelando inmediatamente la reproducción y generación de voz para escuchar al usuario.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from config.manager import get_settings
from core.bus import EventBus
from core.cancellation import CancellationToken
from core.events.base import UserInterrupted
from core.logger import get_logger
from core.state import SessionState, StateMachine
from services.voice.audio_input import AudioChunk
from services.voice.tts_service import ITTSService

logger = get_logger("jessyca.voice.barge_in")


@dataclass
class BargeInMetrics:
    """Métricas detalladas de latencia del ciclo de interrupción (Barge-in)."""

    t0_speech_start: float = 0.0
    t1_vad_detected: float = 0.0
    t2_event_published: float = 0.0
    t3_tts_stopped: float = 0.0
    latency_ms: float = 0.0
    interruption_reason: str = ""
    session_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "t0_speech_start": self.t0_speech_start,
            "t1_vad_detected": self.t1_vad_detected,
            "t2_event_published": self.t2_event_published,
            "t3_tts_stopped": self.t3_tts_stopped,
            "latency_ms": self.latency_ms,
            "interruption_reason": self.interruption_reason,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
        }


class BargeInController:
    """Controlador central de interrupciones y corte de habla (Barge-in)."""

    def __init__(
        self,
        tts_service: ITTSService | None = None,
        *,
        tts_manager: Any | None = None,
        event_bus: EventBus | None = None,
        state_machine: StateMachine | None = None,
        vad_service: Any | None = None,
        min_speech_duration_ms: float | None = None,
        echo_margin_factor: float | None = None,
        cooldown_ms: float | None = None,
    ) -> None:
        self.tts_service = tts_service
        self.tts_manager = tts_manager
        self.event_bus = event_bus
        self.state_machine = state_machine
        self.vad_service = vad_service

        settings = get_settings()
        self.min_speech_duration_ms = (
            min_speech_duration_ms
            if min_speech_duration_ms is not None
            else float(getattr(settings, "VOICE_BARGE_IN_MIN_SPEECH_MS", 150.0))
        )
        self.echo_margin_factor = (
            echo_margin_factor
            if echo_margin_factor is not None
            else float(getattr(settings, "VOICE_BARGE_IN_ECHO_MARGIN_FACTOR", 1.6))
        )
        self.cooldown_ms = (
            cooldown_ms
            if cooldown_ms is not None
            else float(getattr(settings, "VOICE_BARGE_IN_COOLDOWN_MS", 250.0))
        )

        self._lock = threading.RLock()
        self._is_tts_active = False
        self._interrupted_count = 0
        self._current_cancellation_token: CancellationToken | None = None
        self._current_session_id: str | None = None
        self._tts_start_time: float = 0.0

        # Anti-eco and duration filtering state
        self._speech_accumulator_ms: float = 0.0
        self._speech_start_time: float | None = None
        self._has_interrupted_current_turn: bool = False
        self._last_metrics: BargeInMetrics | None = None

    def notify_tts_started(
        self,
        cancellation_token: CancellationToken | None = None,
        session_id: str | None = None,
    ) -> None:
        """Notifica que JESSYCA ha comenzado a generar o reproducir voz."""
        with self._lock:
            self._is_tts_active = True
            self._current_cancellation_token = cancellation_token
            self._current_session_id = session_id
            self._tts_start_time = time.perf_counter()
            self._speech_accumulator_ms = 0.0
            self._speech_start_time = None
            self._has_interrupted_current_turn = False

    def notify_tts_finished(self) -> None:
        """Notifica que JESSYCA ha concluido la reproducción de voz."""
        with self._lock:
            self._is_tts_active = False
            self._current_cancellation_token = None
            self._speech_accumulator_ms = 0.0
            self._speech_start_time = None

    def trigger_barge_in(
        self,
        reason: str = "User speech detected",
        session_id: str | None = None,
        t0_speech_start: float | None = None,
        t1_vad_detected: float | None = None,
    ) -> bool:
        """Ejecuta una interrupción inmediata de la salida de audio si JESSYCA está hablando.

        Retorna True si se detuvo una reproducción activa, o False si no había voz activa
        o ya se había interrumpido el turno actual.
        """
        with self._lock:
            manager_active = False
            if self.tts_manager and hasattr(self.tts_manager, "is_active"):
                manager_active = bool(self.tts_manager.is_active)

            if not self._is_tts_active and not manager_active:
                return False

            if self._has_interrupted_current_turn:
                return False

            t_now = time.perf_counter()
            t0 = t0_speech_start if t0_speech_start is not None else (self._speech_start_time or t_now)
            t1 = t1_vad_detected if t1_vad_detected is not None else t_now

            self._has_interrupted_current_turn = True
            self._is_tts_active = False
            self._interrupted_count += 1

            target_session_id = session_id or self._current_session_id

            logger.info(
                f"[BARGE-IN] Interrumpiendo reproducción de voz: '{reason}' "
                f"(sesión={target_session_id})"
            )

            # 1. Cancelar CancellationToken local
            if self._current_cancellation_token:
                self._current_cancellation_token.cancel()
                self._current_cancellation_token = None

            # 2. Cancelar TTSManager (Pocket TTS / Edge TTS / Pygame)
            if self.tts_manager and hasattr(self.tts_manager, "cancel"):
                try:
                    self.tts_manager.cancel(reason=reason)
                except Exception as exc:
                    logger.warning(f"[BARGE-IN] Error al invocar tts_manager.cancel(): {exc}")

            # 3. Cancelar ITTSService legacy si existe
            if self.tts_service and hasattr(self.tts_service, "stop"):
                try:
                    self.tts_service.stop()
                except Exception as exc:
                    logger.warning(f"[BARGE-IN] Error al invocar tts_service.stop(): {exc}")

            t3 = time.perf_counter()

            # 4. Transición de State Machine (RESPONDING -> LISTENING)
            if self.state_machine:
                try:
                    curr_state = getattr(
                        self.state_machine,
                        "current_state",
                        getattr(self.state_machine, "state", None),
                    )
                    if curr_state == SessionState.RESPONDING:
                        self.state_machine.transition_to(SessionState.LISTENING)
                        logger.info("[BARGE-IN] StateMachine transitada de RESPONDING a LISTENING.")
                except Exception as exc:
                    logger.warning(f"[BARGE-IN] Error al transitar State Machine: {exc}")

            # 5. Publicar evento UserInterrupted una sola vez
            t2 = time.perf_counter()
            if self.event_bus:
                try:
                    event = UserInterrupted(
                        session_id=target_session_id,
                        reason=reason,
                    )
                    self.event_bus.publish(event)
                    logger.info(f"[BARGE-IN] UserInterrupted publicado: {event}")
                except Exception as exc:
                    logger.warning(f"[BARGE-IN] Error al publicar UserInterrupted en EventBus: {exc}")

            # Registrar métricas y latencia
            latency_ms = max(0.0, (t3 - t0) * 1000.0)
            self._last_metrics = BargeInMetrics(
                t0_speech_start=t0,
                t1_vad_detected=t1,
                t2_event_published=t2,
                t3_tts_stopped=t3,
                latency_ms=latency_ms,
                interruption_reason=reason,
                session_id=target_session_id,
            )

            # Limpiar estado acumulador
            self._speech_accumulator_ms = 0.0
            self._speech_start_time = None

            return True

    def process_audio_chunk(
        self,
        chunk: AudioChunk,
        conversation_active: bool = True,
        session_id: str | None = None,
    ) -> bool:
        """Evalúa un fragmento de audio en tiempo real para determinar si debe interrumpir el TTS.

        Aplica:
        1. Verificación de conversación activa (Sección 13).
        2. Verificación de estado de reproducción de TTS (Sección 8).
        3. Ventana de cooldown post-inicio de TTS (Sección 7 - anti-eco).
        4. Umbral de energía adaptativo anti-eco (Sección 6 y 7).
        5. Acumulación de duración mínima de voz para evitar falsos positivos por ruido corto (Sección 16).

        Retorna True si este chunk provocó una interrupción válida, False en caso contrario.
        """
        # Regla 1: conversation_active debe ser True (Sección 13)
        if not conversation_active:
            return False

        with self._lock:
            # Regla 2: TTS debe estar activo
            manager_active = False
            if self.tts_manager and hasattr(self.tts_manager, "is_active"):
                manager_active = bool(self.tts_manager.is_active)

            if not self._is_tts_active and not manager_active:
                self._speech_accumulator_ms = 0.0
                self._speech_start_time = None
                return False

            if self._has_interrupted_current_turn:
                return False

            now = time.perf_counter()

            # Regla 3: Cooldown window inicial para evitar transitorios de altavoz (Anti-eco)
            elapsed_tts_ms = (now - self._tts_start_time) * 1000.0
            if elapsed_tts_ms < self.cooldown_ms:
                return False

            # Regla 4: Umbral anti-eco con margen dinámico
            base_threshold = 300.0
            if self.vad_service and hasattr(self.vad_service, "start_threshold"):
                base_threshold = float(self.vad_service.start_threshold)
            elif self.vad_service and hasattr(self.vad_service, "energy_threshold"):
                base_threshold = float(self.vad_service.energy_threshold)

            dynamic_threshold = base_threshold * self.echo_margin_factor

            # Si el chunk tiene energía calculable
            chunk_energy = getattr(chunk, "energy_rms", 0.0)
            chunk_duration_ms = getattr(chunk, "duration_seconds", 0.0) * 1000.0
            if chunk_duration_ms <= 0:
                chunk_duration_ms = len(getattr(chunk, "data", b"")) / 32.0

            if chunk_energy < dynamic_threshold:
                # No supera el umbral de eco/voz: decae la acumulación
                self._speech_accumulator_ms = max(0.0, self._speech_accumulator_ms - (chunk_duration_ms * 0.5))
                if self._speech_accumulator_ms == 0.0:
                    self._speech_start_time = None
                return False

            # Supera el umbral dinámico
            if self._speech_start_time is None:
                self._speech_start_time = now

            self._speech_accumulator_ms += chunk_duration_ms

            # Regla 5: Comprobar duración mínima de habla
            if self._speech_accumulator_ms >= self.min_speech_duration_ms:
                t1_vad = now
                return self.trigger_barge_in(
                    reason=f"Speech detected ({self._speech_accumulator_ms:.1f}ms >= {self.min_speech_duration_ms:.1f}ms, RMS {chunk_energy:.1f})",
                    session_id=session_id or self._current_session_id,
                    t0_speech_start=self._speech_start_time,
                    t1_vad_detected=t1_vad,
                )

            return False

    @property
    def is_tts_active(self) -> bool:
        with self._lock:
            manager_active = False
            if self.tts_manager and hasattr(self.tts_manager, "is_active"):
                manager_active = bool(self.tts_manager.is_active)
            return self._is_tts_active or manager_active

    @property
    def interrupted_count(self) -> int:
        with self._lock:
            return self._interrupted_count

    @property
    def last_metrics(self) -> BargeInMetrics | None:
        with self._lock:
            return self._last_metrics

    def reset(self) -> None:
        """Restablece el estado del controlador."""
        with self._lock:
            self._is_tts_active = False
            self._interrupted_count = 0
            self._current_cancellation_token = None
            self._current_session_id = None
            self._speech_accumulator_ms = 0.0
            self._speech_start_time = None
            self._has_interrupted_current_turn = False
            self._last_metrics = None
