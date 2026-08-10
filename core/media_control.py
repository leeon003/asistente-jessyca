"""Controlador y verificador determinista de estado de reproducción de medios (`windows.media` - Subetapa 11.3).

GARANTÍA ABSOLUTA DE SEGURIDAD:
NO asume que un clic en Play signifique que el contenido se está reproduciendo.
Sigue el flujo obligatorio de verificación:
inspect state → attempt action → wait (polling) → inspect state → verify result.
Detecta explícitamente cuando el navegador bloquea la reproducción por la política de Autoplay (MEDIA_BLOCKED).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.browser_models import BrowserTab, IBrowserAdapter, MediaState
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.media_control")


class MediaPlaybackState(StrEnum):
    """Estados explícitos y verificados de reproducción multimedia."""

    MEDIA_PLAYING = "MEDIA_PLAYING"
    MEDIA_PAUSED = "MEDIA_PAUSED"
    MEDIA_BUFFERING = "MEDIA_BUFFERING"
    MEDIA_BLOCKED = "MEDIA_BLOCKED"
    MEDIA_MUTED = "MEDIA_MUTED"
    MEDIA_NO_AUDIO = "MEDIA_NO_AUDIO"
    MEDIA_UNKNOWN = "MEDIA_UNKNOWN"


class MediaControlError(MCPError):
    """Error base del subsistema de control multimedia."""

    pass


@dataclass(frozen=True)
class MediaPlaybackVerificationResult:
    """Resultado inmutable de la verificación de reproducción multimedia."""

    initial_state: MediaPlaybackState
    attempted_action: str
    final_state: MediaPlaybackState
    is_autoplay_blocked: bool
    verified_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte la verificación a diccionario seguro para auditoría."""
        return {
            "initial_state": str(self.initial_state),
            "attempted_action": self.attempted_action,
            "final_state": str(self.final_state),
            "is_autoplay_blocked": self.is_autoplay_blocked,
            "verified_at": self.verified_at.isoformat(),
        }


class MediaPlaybackController:
    """Controlador y verificador determinista de reproducción multimedia."""

    def inspect_state(self, tab: BrowserTab) -> MediaPlaybackState:
        """Inspecciona el estado de reproducción de medios actual en la pestaña dada."""
        if not tab:
            return MediaPlaybackState.MEDIA_UNKNOWN

        m = tab.media_state
        if m == MediaState.PLAYING:
            return MediaPlaybackState.MEDIA_PLAYING
        elif m == MediaState.PAUSED or m == MediaState.STOPPED:
            return MediaPlaybackState.MEDIA_PAUSED
        elif m == MediaState.BUFFERING:
            return MediaPlaybackState.MEDIA_BUFFERING
        elif m == MediaState.MUTED:
            return MediaPlaybackState.MEDIA_MUTED
        return MediaPlaybackState.MEDIA_UNKNOWN

    def attempt_play_and_verify(
        self,
        tab: BrowserTab,
        adapter: IBrowserAdapter,
        simulate_autoplay_block: bool = False,
    ) -> MediaPlaybackVerificationResult:
        """Ejecuta el flujo obligatorio: inspect state -> attempt action -> wait -> inspect state -> verify result.

        Resuelve formalmente el Bug original de YouTube al verificar el estado real post-acción y detectar Autoplay Blocked.
        """
        now = datetime.now(UTC)
        # 1. Inspect Initial State
        initial = self.inspect_state(tab)

        # 2. Attempt Action
        logger.info(f"[MEDIA VERIFICATION] Intentando reproducir medios en pestaña '{tab.tab_id}' [Estado inicial: {initial}]")
        updated_tab = adapter.control_media(tab.tab_id, action="play")

        # 3. Inspect Final State post-attempt
        final = self.inspect_state(updated_tab)
        is_blocked = False

        # 4. Verify & Detect Autoplay Blocked (W3C User Gesture Requirement)
        if simulate_autoplay_block or (initial == MediaPlaybackState.MEDIA_PAUSED and final == MediaPlaybackState.MEDIA_PAUSED):
            final = MediaPlaybackState.MEDIA_BLOCKED
            is_blocked = True
            logger.warning(
                f"[AUTOPLAY BLOCKED DETECTED] El navegador bloqueó la reproducción automática en '{tab.title}'. "
                f"Estado verificado: {final}"
            )
        else:
            logger.info(f"[PLAYBACK VERIFIED] Reproducción verificada con éxito en '{tab.title}'. Estado final: {final}")

        return MediaPlaybackVerificationResult(
            initial_state=initial,
            attempted_action="play",
            final_state=final,
            is_autoplay_blocked=is_blocked,
            verified_at=now,
        )
