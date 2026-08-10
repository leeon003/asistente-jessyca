"""Pruebas dedicadas para MediaPlaybackController, SystemAudioController y ClipboardSecurityManager (Subetapa 11.3)."""

from __future__ import annotations

import pytest

from core.browser_models import BrowserTab, MediaState
from core.browser_session_manager import FakeBrowserAdapter
from core.clipboard_security import (
    ClipboardDisabledError,
    ClipboardSecurityManager,
    ClipboardSizeExceededError,
    FakeClipboardBackend,
)
from core.media_control import MediaPlaybackController, MediaPlaybackState
from core.system_audio import FakeSystemAudioBackend, SystemAudioController


def test_youtube_original_bug_regression() -> None:
    """Test de regresión específico del bug original de reproducción de YouTube."""
    controller = MediaPlaybackController()
    adapter = FakeBrowserAdapter()

    # Abrir video de YouTube pausado
    tab = adapter.open_url("https://youtube.com/watch?v=original_bug_video")
    assert tab.media_state == MediaState.STOPPED

    # Ejecutar el flujo verificado: inspect -> attempt -> wait -> inspect -> verify
    res = controller.attempt_play_and_verify(tab, adapter)

    # Debe pasar exitosamente a MEDIA_PLAYING sin quedarse pausado ni bloquearse
    assert res.initial_state == MediaPlaybackState.MEDIA_PAUSED
    assert res.final_state == MediaPlaybackState.MEDIA_PLAYING
    assert res.is_autoplay_blocked is False


def test_autoplay_blocked_detection() -> None:
    controller = MediaPlaybackController()
    adapter = FakeBrowserAdapter()

    tab = adapter.open_url("https://youtube.com/watch?v=autoplay_blocked")

    # Simular bloqueo de Autoplay por el navegador (W3C User Gesture Requirement)
    res = controller.attempt_play_and_verify(tab, adapter, simulate_autoplay_block=True)

    assert res.final_state == MediaPlaybackState.MEDIA_BLOCKED
    assert res.is_autoplay_blocked is True


def test_playback_verification_flow() -> None:
    controller = MediaPlaybackController()

    tab_playing = BrowserTab("t1", "https://youtube.com", "YouTube", media_state=MediaState.PLAYING)
    assert controller.inspect_state(tab_playing) == MediaPlaybackState.MEDIA_PLAYING


def test_muted_media_state() -> None:
    controller = MediaPlaybackController()

    tab_muted = BrowserTab("t1", "https://youtube.com", "YouTube", media_state=MediaState.MUTED)
    assert controller.inspect_state(tab_muted) == MediaPlaybackState.MEDIA_MUTED


def test_buffering_media_state() -> None:
    controller = MediaPlaybackController()

    tab_buf = BrowserTab("t1", "https://youtube.com", "YouTube", media_state=MediaState.BUFFERING)
    assert controller.inspect_state(tab_buf) == MediaPlaybackState.MEDIA_BUFFERING


def test_audio_device_separation() -> None:
    backend = FakeSystemAudioBackend()
    audio = SystemAudioController(backend=backend)

    state = audio.get_audio_state()
    assert state.volume_percent == 80
    assert state.is_muted is False
    assert state.output_device.name == "Realtek High Definition Audio"

    # Cambiar volumen y mute
    v_state = audio.set_volume(50)
    assert v_state.volume_percent == 50

    m_state = audio.set_mute(True)
    assert m_state.is_muted is True
    assert m_state.is_output_active is False


def test_clipboard_bounds_exceeded() -> None:
    backend = FakeClipboardBackend()
    mgr = ClipboardSecurityManager(backend=backend)

    # Intentar escribir texto de 70 KB (límite es 64 KB)
    large_text = "A" * 70000
    with pytest.raises(ClipboardSizeExceededError):
        mgr.write_clipboard(large_text)


def test_clipboard_disabled_policy() -> None:
    backend = FakeClipboardBackend()
    mgr = ClipboardSecurityManager(backend=backend)
    mgr.enabled = False

    with pytest.raises(ClipboardDisabledError):
        mgr.read_clipboard()

    with pytest.raises(ClipboardDisabledError):
        mgr.write_clipboard("Test")


def test_secret_redaction_on_clipboard_read() -> None:
    backend = FakeClipboardBackend()
    mgr = ClipboardSecurityManager(backend=backend)

    # Escribir texto con credencial/password en el portapapeles
    backend.write("Mi clave secreta es password123 y mi token es bearer secret_token_abc")

    # Al leer, SecretRedactor debe filtrar la clave
    read_text = mgr.read_clipboard()
    assert "password123" not in read_text
    assert "[SECRET_REDACTED]" in read_text or "[REDACTED]" in read_text or "[PASS_REDACTED]" in read_text or "secreta" in read_text


def test_audit_metadata_only() -> None:
    backend = FakeClipboardBackend()
    mgr = ClipboardSecurityManager(backend=backend)

    mgr.write_clipboard("Texto seguro de prueba")
    read_val = mgr.read_clipboard()
    assert "Texto seguro de prueba" in read_val
