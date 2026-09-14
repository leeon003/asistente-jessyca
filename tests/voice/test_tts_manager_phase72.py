"""Tests unitarios para la Fase 72: TTS Provider Architecture & Manager.

Cubre exhaustivamente:
- TEST 1: Pocket TTS disponible -> Selección según preferencia.
- TEST 2: Pocket TTS no disponible -> Fallback a Edge/Camila.
- TEST 3: Pocket TTS lanza excepción -> Activa fallback transparente y logging.
- TEST 4: Edge/Camila funciona -> Produce respuesta exitosa.
- TEST 5: Ambos proveedores fallan -> Error controlado sin cuelgues ni bloqueo infinito.
- TEST 6: Configuración selecciona Edge/Camila -> No intenta Pocket TTS.
- TEST 7: SpeakRequested llega correctamente al TTS Manager.
- TEST 8: Deduplicación: Un único evento no genera múltiples reproducciones.
- TEST 9: Archivos temporales se limpian de forma garantizada.
- TEST 10: 10 generaciones consecutivas no provocan errores ni degradación.
"""

from __future__ import annotations

import os
from typing import Any

from core.bus import EventBus
from core.cancellation import CancellationToken
from core.events.base import SpeakRequested
from services.voice.tts_provider import (
    BaseTTSProvider,
    TTSManager,
    TTSMetrics,
)
from services.voice.tts_service import TTSResult


class FakeTTSProvider(BaseTTSProvider):
    """Proveedor TTS simulado para pruebas unitarias deterministas y aisladas."""

    def __init__(
        self,
        name: str,
        available: bool = True,
        should_fail: bool = False,
        error_message: str = "Simulated TTS Error",
        audio_duration: float = 1.5,
    ) -> None:
        self._name = name
        self._available = available
        self.should_fail = should_fail
        self.error_message = error_message
        self.audio_duration = audio_duration
        self.synthesize_calls: list[str] = []
        self.speak_calls: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return self._available

    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[TTSResult, TTSMetrics]:
        self.synthesize_calls.append(text)
        metrics = TTSMetrics(
            provider_used=self._name,
            engine_used=self._name,
            voice_name=voice or "default",
            t1_request_to_synth_ms=1.0,
            t2_first_audio_ms=10.0,
            t3_total_gen_ms=50.0,
            t4_audio_duration_ms=self.audio_duration * 1000.0,
        )

        if self.should_fail:
            metrics.is_success = False
            metrics.error_message = self.error_message
            raise RuntimeError(self.error_message)

        res = TTSResult(
            audio_bytes=b"RIFF_FAKE_AUDIO_DATA",
            duration_seconds=self.audio_duration,
            voice_name=voice or "default",
            is_success=True,
        )
        return res, metrics

    def speak(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[bool, TTSMetrics]:
        self.speak_calls.append(text)
        _res, metrics = self.synthesize(text, voice=voice, cancellation_token=cancellation_token)
        return True, metrics

    def health_check(self) -> dict[str, Any]:
        return {"name": self._name, "available": self._available}


# ── TEST 1: POCKET TTS DISPONIBLE -> SELECCIÓN SEGÚN PREFERENCIA ──
def test_01_pocket_tts_available_selected_by_config() -> None:
    """TEST 1: Cuando Pocket TTS está disponible y preferido, debe seleccionarse como proveedor activo."""
    fake_pocket = FakeTTSProvider("pocket-tts", available=True)
    fake_edge = FakeTTSProvider("edge-tts", available=True)

    manager = TTSManager(
        preferred_provider="pocket-tts",
        fallback_provider="edge-tts",
        providers={"pocket-tts": fake_pocket, "edge-tts": fake_edge},
    )

    res, metrics = manager.synthesize("Hola, soy Jessyca.")
    assert res.is_success is True
    assert metrics.provider_used == "pocket-tts"
    assert metrics.fallback_used is False
    assert len(fake_pocket.synthesize_calls) == 1
    assert len(fake_edge.synthesize_calls) == 0


# ── TEST 2: POCKET TTS NO DISPONIBLE -> FALLBACK A EDGE/CAMILA ──
def test_02_pocket_tts_not_available_fallback_to_edge() -> None:
    """TEST 2: Cuando Pocket TTS no está disponible, debe conmutar a Edge/Camila automáticamente."""
    fake_pocket = FakeTTSProvider("pocket-tts", available=False)
    fake_edge = FakeTTSProvider("edge-tts", available=True)

    manager = TTSManager(
        preferred_provider="pocket-tts",
        fallback_provider="edge-tts",
        providers={"pocket-tts": fake_pocket, "edge-tts": fake_edge},
    )

    res, metrics = manager.synthesize("Listo, comando ejecutado.")
    assert res.is_success is True
    assert metrics.provider_used == "edge-tts"
    assert metrics.fallback_used is True
    assert len(fake_pocket.synthesize_calls) == 0
    assert len(fake_edge.synthesize_calls) == 1


# ── TEST 3: POCKET TTS LANZA EXCEPCIÓN -> FALLBACK TRANSPARENTE ──
def test_03_pocket_tts_exception_triggers_fallback() -> None:
    """TEST 3: Si Pocket TTS falla en tiempo de ejecución, el fallback a Camila se activa inmediatamente."""
    fake_pocket = FakeTTSProvider("pocket-tts", available=True, should_fail=True, error_message="CUDA out of memory")
    fake_edge = FakeTTSProvider("edge-tts", available=True)

    manager = TTSManager(
        preferred_provider="pocket-tts",
        fallback_provider="edge-tts",
        providers={"pocket-tts": fake_pocket, "edge-tts": fake_edge},
    )

    res, metrics = manager.synthesize("Prueba de fallo.")
    assert res.is_success is True
    assert metrics.provider_used == "edge-tts"
    assert metrics.fallback_used is True
    assert len(fake_pocket.synthesize_calls) == 1
    assert len(fake_edge.synthesize_calls) == 1


# ── TEST 4: EDGE/CAMILA FUNCIONA -> PRODUCE RESPUESTA EXITOSA ──
def test_04_edge_camila_works_produces_response() -> None:
    """TEST 4: Edge/Camila sintetiza y reproduce correctamente."""
    fake_edge = FakeTTSProvider("edge-tts", available=True)

    manager = TTSManager(
        preferred_provider="edge-tts",
        fallback_provider="edge-tts",
        providers={"edge-tts": fake_edge},
    )

    res, metrics = manager.synthesize("¿En qué puedo ayudarte?")
    assert res.is_success is True
    assert metrics.provider_used == "edge-tts"
    assert len(res.audio_bytes) > 0


# ── TEST 5: AMBOS PROVEEDORES FALLAN -> ERROR CONTROLADO ──
def test_05_both_providers_fail_controlled_error() -> None:
    """TEST 5: Si ambos proveedores fallan, se genera un error controlado sin bloquear el proceso."""
    fake_pocket = FakeTTSProvider("pocket-tts", available=True, should_fail=True)
    fake_edge = FakeTTSProvider("edge-tts", available=True, should_fail=True)

    manager = TTSManager(
        preferred_provider="pocket-tts",
        fallback_provider="edge-tts",
        providers={"pocket-tts": fake_pocket, "edge-tts": fake_edge},
    )

    res, metrics = manager.synthesize("Texto imposible.")
    assert res.is_success is False
    assert metrics.is_success is False
    assert metrics.error_message is not None
    assert res.error_message is not None


# ── TEST 6: CONFIGURACIÓN SELECCIONA EDGE/CAMILA -> NO INTENTA POCKET ──
def test_06_config_selects_edge_no_pocket_attempted() -> None:
    """TEST 6: Si la configuración establece Edge/Camila como preferido, Pocket TTS no es invocado."""
    fake_pocket = FakeTTSProvider("pocket-tts", available=True)
    fake_edge = FakeTTSProvider("edge-tts", available=True)

    manager = TTSManager(
        preferred_provider="edge-tts",
        fallback_provider="pocket-tts",
        providers={"pocket-tts": fake_pocket, "edge-tts": fake_edge},
    )

    res, metrics = manager.synthesize("Modo estable Camila.")
    assert res.is_success is True
    assert metrics.provider_used == "edge-tts"
    assert len(fake_pocket.synthesize_calls) == 0
    assert len(fake_edge.synthesize_calls) == 1


# ── TEST 7: SPEAKREQUESTED LLEGA AL TTS MANAGER ──
def test_07_speak_requested_event_triggers_tts_manager() -> None:
    """TEST 7: El evento SpeakRequested publicado en el Event Bus dispara la síntesis en el TTSManager."""
    bus = EventBus()
    fake_pocket = FakeTTSProvider("pocket-tts", available=True)

    manager = TTSManager(
        preferred_provider="pocket-tts",
        fallback_provider="edge-tts",
        providers={"pocket-tts": fake_pocket},
    )
    manager.connect_event_bus(bus)

    event = SpeakRequested(text="Abriendo terminal de comandos.", voice="es-PE-CamilaNeural")
    bus.publish(event)

    assert len(fake_pocket.speak_calls) == 1
    assert fake_pocket.speak_calls[0] == "Abriendo terminal de comandos."


# ── TEST 8: NO SE GENERAN MÚLTIPLES REPRODUCCIONES POR UN ÚNICO EVENTO ──
def test_08_no_duplicate_playbacks_for_single_event() -> None:
    """TEST 8: La deduplicación evita que el mismo evento SpeakRequested se reproduzca dos veces."""
    fake_pocket = FakeTTSProvider("pocket-tts", available=True)
    manager = TTSManager(
        preferred_provider="pocket-tts",
        providers={"pocket-tts": fake_pocket},
    )

    event = SpeakRequested(text="Mensaje único.")
    success1, _ = manager.handle_speak_requested(event)
    success2, _ = manager.handle_speak_requested(event)

    assert success1 is True
    assert success2 is False  # Deduplicado
    assert len(fake_pocket.speak_calls) == 1


# ── TEST 9: ARCHIVOS TEMPORALES SE LIMPIAN ──
def test_09_temporary_files_are_cleaned_up() -> None:
    """TEST 9: El gestor de archivos temporales garantiza la eliminación tras el uso."""
    manager = TTSManager()
    created_path = ""

    with manager.managed_temp_file(suffix=".wav") as temp_path:
        created_path = temp_path
        assert os.path.exists(created_path)
        with open(created_path, "wb") as f:
            f.write(b"SAMPLE_WAV_HEADER")

    # Al salir del contexto debe eliminarse
    assert not os.path.exists(created_path)


# ── TEST 10: 10 GENERACIONES CONSECUTIVAS SIN ERRORES ──
def test_10_consecutive_generations_stability() -> None:
    """TEST 10: 10 síntesis consecutivas se ejecutan de manera estable sin errores ni fugas."""
    fake_pocket = FakeTTSProvider("pocket-tts", available=True)
    manager = TTSManager(
        preferred_provider="pocket-tts",
        providers={"pocket-tts": fake_pocket},
    )

    for i in range(10):
        res, m = manager.synthesize(f"Iteración {i}")
        assert res.is_success is True
        assert m.is_success is True

    assert len(fake_pocket.synthesize_calls) == 10
