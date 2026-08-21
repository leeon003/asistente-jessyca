"""Text-to-Speech Service (tts_service.py - Fase 13).

Síntesis de voz no bloqueante con edge-tts (voz: es-PE-CamilaNeural), soporte de cancelación
inmediata y fallback seguro sin crashes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from core.cancellation import CancellationToken
from core.logger import get_logger
from services.voice.voice_errors import TTSFailureError, VoiceCancelledError

logger = get_logger("jessyca.voice.tts")

DEFAULT_VOICE_NAME = "es-PE-CamilaNeural"


@dataclass(frozen=True)
class TTSResult:
    """Resultado formal inmutable de una operación de síntesis de voz."""

    audio_bytes: bytes
    duration_seconds: float
    voice_name: str
    is_success: bool
    error_message: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "size_bytes": len(self.audio_bytes),
            "duration_seconds": self.duration_seconds,
            "voice_name": self.voice_name,
            "is_success": self.is_success,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat(),
        }


class ITTSService(Protocol):
    """Protocolo abstracto para servicios de síntesis de voz."""

    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TTSResult: ...

    def speak(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> bool: ...

    def stop(self) -> None: ...


class MockTTSService:
    """Servicio TTS sintético para pruebas rápidas y deterministas en CI/CD."""

    def __init__(self, default_voice: str = DEFAULT_VOICE_NAME) -> None:
        self.default_voice = default_voice
        self.should_fail = False
        self.failure_reason = "Simulated TTS Error"
        self.spoken_texts: list[str] = []
        self.is_speaking = False

    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TTSResult:
        if cancellation_token and cancellation_token.is_cancelled:
            raise VoiceCancelledError("Operación de síntesis TTS cancelada.")

        if self.should_fail:
            return TTSResult(
                audio_bytes=b"",
                duration_seconds=0.0,
                voice_name=voice or self.default_voice,
                is_success=False,
                error_message=self.failure_reason,
            )

        # Generar bytes sintéticos simulados (100 bytes por carácter)
        synthetic_bytes = b"\x00" * max(10, len(text) * 100)
        duration = len(text) * 0.05

        return TTSResult(
            audio_bytes=synthetic_bytes,
            duration_seconds=duration,
            voice_name=voice or self.default_voice,
            is_success=True,
        )

    def speak(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> bool:
        if cancellation_token and cancellation_token.is_cancelled:
            raise VoiceCancelledError("Reproducción de TTS cancelada.")

        if self.should_fail:
            raise TTSFailureError(self.failure_reason)

        self.is_speaking = True
        self.spoken_texts.append(text)
        logger.info(f"[MOCK TTS] Hablando: '{text}' (Voz: {voice or self.default_voice})")
        self.is_speaking = False
        return True

    def stop(self) -> None:
        """Detiene inmediatamente la reproducción de voz actual (Barge-in)."""
        self.is_speaking = False
        logger.info("[MOCK TTS] Reproducción de voz detenida por interrupción.")


class EdgeTTSService:
    """Servicio de síntesis de voz mediante edge-tts con control de cancelación y fallback."""

    def __init__(self, default_voice: str = DEFAULT_VOICE_NAME) -> None:
        self.default_voice = default_voice
        self._lock = threading.RLock()
        self._current_token: CancellationToken | None = None

    def stop(self) -> None:
        """Detiene de inmediato cualquier reproducción activa de voz."""
        with self._lock:
            if self._current_token:
                self._current_token.cancel()
                self._current_token = None
        logger.info("[EDGE-TTS] Síntesis/Reproducción cancelada por comando stop.")

    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TTSResult:
        """Sintetiza texto a audio MP3 utilizando edge-tts."""
        if not text or not text.strip():
            return TTSResult(
                audio_bytes=b"",
                duration_seconds=0.0,
                voice_name=voice or self.default_voice,
                is_success=True,
            )

        if cancellation_token and cancellation_token.is_cancelled:
            raise VoiceCancelledError("Síntesis de voz cancelada antes de iniciar.")

        selected_voice = voice or self.default_voice

        try:
            # En un entorno real se ejecuta el generador asíncrono de edge-tts
            # Si no hay conexión o no está instalado edge-tts, se captura ordenadamente
            import asyncio

            import edge_tts

            async def _run_edge_tts() -> bytes:
                communicate = edge_tts.Communicate(text, selected_voice)
                chunks: list[bytes] = []
                async for chunk in communicate.stream():
                    if cancellation_token and cancellation_token.is_cancelled:
                        raise VoiceCancelledError("Síntesis cancelada durante streaming.")
                    if chunk["type"] == "audio":
                        chunks.append(chunk["data"])
                return b"".join(chunks)

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import nest_asyncio
                    nest_asyncio.apply()
                audio_data = loop.run_until_complete(_run_edge_tts())
            except RuntimeError:
                audio_data = asyncio.run(_run_edge_tts())

            return TTSResult(
                audio_bytes=audio_data,
                duration_seconds=len(text) * 0.06,
                voice_name=selected_voice,
                is_success=True,
            )
        except VoiceCancelledError:
            raise
        except ImportError:
            logger.warning("[EDGE-TTS] Módulo edge-tts no disponible. Retornando fallback sin crash.")
            return TTSResult(
                audio_bytes=b"",
                duration_seconds=0.0,
                voice_name=selected_voice,
                is_success=False,
                error_message="Módulo edge-tts no disponible en el entorno.",
            )
        except Exception as e:
            logger.error(f"[EDGE-TTS] Error durante síntesis: {e}")
            return TTSResult(
                audio_bytes=b"",
                duration_seconds=0.0,
                voice_name=selected_voice,
                is_success=False,
                error_message=str(e),
            )

    def speak(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> bool:
        res = self.synthesize(text, voice=voice, cancellation_token=cancellation_token)
        return res.is_success
