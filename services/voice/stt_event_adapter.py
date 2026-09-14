"""Adaptador de eventos STT para JESSYCA 4.0 (Fase 67).

Conecta de forma incremental, desacoplada y reversible el subsistema STT existente
con el Event Bus (Fase 65) y la State Machine (Fase 66):
Audio/Transcripción → STT Event Adapter → UtteranceFinal → Event Bus → State Machine → ROUTING
"""

from __future__ import annotations

from typing import Any

from core.bus import EventBus, get_event_bus
from core.events import ErrorOccurred, UtteranceFinal
from core.logger import get_logger
from core.state import SessionState, StateMachine
from services.voice.stt_service import ISTTService, MockSTTService, TranscriptResult

logger = get_logger("jessyca.voice.stt_adapter")


class STTEventAdapter:
    """Adaptador de eventos que orquesta el flujo de audio/transcripción hacia Event Bus y State Machine."""

    def __init__(
        self,
        stt_service: ISTTService | Any | None = None,
        event_bus: EventBus | None = None,
        state_machine: StateMachine | None = None,
    ) -> None:
        """Inicializa el adaptador con inyección de dependencias.

        Args:
            stt_service: Motor STT (ISTTService o compatible). Si es None, usa MockSTTService.
            event_bus: Instancia de EventBus de Fase 65. Si es None, usa get_event_bus().
            state_machine: Instancia de StateMachine de Fase 66. Si es None, crea una nueva.
        """
        self.stt_service: Any = stt_service or MockSTTService()
        self.event_bus: EventBus = event_bus or get_event_bus()
        self.state_machine: StateMachine = state_machine or StateMachine()

    @property
    def session_id(self) -> str:
        """Obtiene el identificador de la sesión activa desde la State Machine."""
        return self.state_machine.session_id

    def process_audio(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        timeout_seconds: float = 10.0,
    ) -> UtteranceFinal | None:
        """Procesa un buffer de audio con el STT, publica UtteranceFinal y actualiza el estado.

        Flujo de estados:
            LISTENING → TRANSCRIBING → [UtteranceFinal] → ROUTING
        """
        self._prepare_transcribing_state()

        # 1. Transcripción con captura de excepciones
        try:
            transcript = self.stt_service.transcribe(
                audio_data,
                sample_rate=sample_rate,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            self._handle_stt_exception(exc)
            return None

        # 2. Despacho y validación de la transcripción
        return self._dispatch_transcript(transcript)

    async def process_audio_async(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        timeout_seconds: float = 10.0,
    ) -> UtteranceFinal | None:
        """Versión asíncrona de process_audio con soporte awaitable."""
        await self._prepare_transcribing_state_async()

        try:
            transcript = self.stt_service.transcribe(
                audio_data,
                sample_rate=sample_rate,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            await self._handle_stt_exception_async(exc)
            return None


        return await self._dispatch_transcript_async(transcript)

    def process_transcript(
        self,
        transcript: TranscriptResult | str,
        confidence: float = 1.0,
        language: str = "es",
        metadata: dict[str, Any] | None = None,
    ) -> UtteranceFinal | None:
        """Procesa una transcripción ya calculada (ej. por CalibratedVoiceCaptureEngine)."""
        self._prepare_transcribing_state()

        if isinstance(transcript, str):
            obj = TranscriptResult(
                text=transcript,
                confidence=confidence,
                language=language,
                duration_ms=0.0,
                metadata=metadata or {},
            )
        else:
            obj = transcript

        return self._dispatch_transcript(obj)

    async def process_transcript_async(
        self,
        transcript: TranscriptResult | str,
        confidence: float = 1.0,
        language: str = "es",
        metadata: dict[str, Any] | None = None,
    ) -> UtteranceFinal | None:
        """Versión asíncrona de process_transcript."""
        await self._prepare_transcribing_state_async()

        if isinstance(transcript, str):
            obj = TranscriptResult(
                text=transcript,
                confidence=confidence,
                language=language,
                duration_ms=0.0,
                metadata=metadata or {},
            )
        else:
            obj = transcript

        return await self._dispatch_transcript_async(obj)

    # ── Métodos internos de soporte y recuperación ──

    def _prepare_transcribing_state(self) -> None:
        """Asegura que la State Machine transicione a TRANSCRIBING desde LISTENING o IDLE."""
        curr = self.state_machine.current_state
        if curr == SessionState.LISTENING:
            self.state_machine.transition_to(SessionState.TRANSCRIBING)
        elif curr == SessionState.IDLE:
            self.state_machine.transition_to(SessionState.WAKEWORD)
            self.state_machine.transition_to(SessionState.LISTENING)
            self.state_machine.transition_to(SessionState.TRANSCRIBING)

    async def _prepare_transcribing_state_async(self) -> None:
        """Versión asíncrona de _prepare_transcribing_state."""
        curr = self.state_machine.current_state
        if curr == SessionState.LISTENING:
            await self.state_machine.transition_to_async(SessionState.TRANSCRIBING)
        elif curr == SessionState.IDLE:
            await self.state_machine.transition_to_async(SessionState.WAKEWORD)
            await self.state_machine.transition_to_async(SessionState.LISTENING)
            await self.state_machine.transition_to_async(SessionState.TRANSCRIBING)

    def _dispatch_transcript(self, transcript: TranscriptResult) -> UtteranceFinal | None:
        """Valida y publica la transcripción, actualizando el estado de la máquina."""
        clean_text = transcript.text.strip() if transcript.text else ""

        # Manejo de transcripción vacía / whitespace
        if not clean_text:
            logger.debug(
                f"STT: Transcripción vacía o whitespace descartada (session_id={self.session_id})."
            )
            self._recover_from_empty_or_failed()
            return None

        logger.info(f"STT: Transcripción recibida: '{clean_text}' (confianza: {transcript.confidence:.2f})")

        # Construcción de evento UtteranceFinal tipado
        event = UtteranceFinal(
            text=clean_text,
            confidence=transcript.confidence,
            language=transcript.language,
            session_id=self.session_id,
            metadata=dict(transcript.metadata) if transcript.metadata else {},
        )

        # Actualizar contexto de sesión
        self.state_machine.context.utterance = clean_text

        # Publicar en EventBus
        self.event_bus.publish(event)
        logger.info(f"EVENT: UtteranceFinal publicado (session_id={self.session_id})")

        # Transición hacia ROUTING
        if self.state_machine.current_state == SessionState.TRANSCRIBING:
            self.state_machine.transition_to(SessionState.ROUTING)
            logger.info(f"STATE: TRANSCRIBING → ROUTING (session_id={self.session_id})")

        return event

    async def _dispatch_transcript_async(self, transcript: TranscriptResult) -> UtteranceFinal | None:
        """Versión asíncrona de _dispatch_transcript."""
        clean_text = transcript.text.strip() if transcript.text else ""

        if not clean_text:
            logger.debug(
                f"STT: Transcripción vacía o whitespace descartada (session_id={self.session_id})."
            )
            await self._recover_from_empty_or_failed_async()
            return None

        logger.info(f"STT: Transcripción recibida: '{clean_text}' (confianza: {transcript.confidence:.2f})")

        event = UtteranceFinal(
            text=clean_text,
            confidence=transcript.confidence,
            language=transcript.language,
            session_id=self.session_id,
            metadata=dict(transcript.metadata) if transcript.metadata else {},
        )

        self.state_machine.context.utterance = clean_text

        await self.event_bus.publish_async(event)
        logger.info(f"EVENT: UtteranceFinal publicado (session_id={self.session_id})")

        if self.state_machine.current_state == SessionState.TRANSCRIBING:
            await self.state_machine.transition_to_async(SessionState.ROUTING)
            logger.info(f"STATE: TRANSCRIBING → ROUTING (session_id={self.session_id})")

        return event

    def _handle_stt_exception(self, exc: Exception) -> None:
        """Gestiona un fallo del motor STT emitiendo ErrorOccurred y recuperando el estado."""
        logger.error(f"STT: Excepción no controlada durante transcripción: {exc}", exc_info=True)

        err_event = ErrorOccurred(
            error_message=str(exc),
            error_type=type(exc).__name__,
            details={"session_id": self.session_id, "stage": "stt_transcription"},
        )
        self.event_bus.publish(err_event)

        self._recover_from_empty_or_failed()
        return None

    async def _handle_stt_exception_async(self, exc: Exception) -> None:
        """Versión asíncrona de _handle_stt_exception."""
        logger.error(f"STT: Excepción no controlada durante transcripción: {exc}", exc_info=True)

        err_event = ErrorOccurred(
            error_message=str(exc),
            error_type=type(exc).__name__,
            details={"session_id": self.session_id, "stage": "stt_transcription"},
        )
        await self.event_bus.publish_async(err_event)

        await self._recover_from_empty_or_failed_async()
        return None

    def _recover_from_empty_or_failed(self) -> None:
        """Devuelve la State Machine a un estado coherente tras fallo o audio vacío."""
        if self.state_machine.current_state == SessionState.TRANSCRIBING:
            if self.state_machine.conversation_active:
                self.state_machine.transition_to(SessionState.LISTENING)
            else:
                self.state_machine.transition_to(SessionState.IDLE)

    async def _recover_from_empty_or_failed_async(self) -> None:
        """Versión asíncrona de _recover_from_empty_or_failed."""
        if self.state_machine.current_state == SessionState.TRANSCRIBING:
            if self.state_machine.conversation_active:
                await self.state_machine.transition_to_async(SessionState.LISTENING)
            else:
                await self.state_machine.transition_to_async(SessionState.IDLE)
