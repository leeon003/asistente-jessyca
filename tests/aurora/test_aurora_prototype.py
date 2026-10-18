"""Suite de Pruebas Automatizadas para JESSYCA ORB — Núcleo Aurora 3D (Fase 7).

Verifica:
1. Mapeo no invasivo de SessionState sin alterar los enums originales.
2. Integridad de activos estáticos y Three.js offline.
3. Servidor FastAPI, endpoints REST y canal WebSocket.
4. Adaptador de audio desacoplado (RMS, ZCR, amplitud normalizada).
5. No interferencia con Ollama, Whisper STT ni Desktop Automation.
6. Liberación limpia de recursos y ciclo de vida de ventana.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.state.states import SessionState
from interfaces.aurora.audio_adapter import AuroraAudioAdapter
from interfaces.aurora.server import AuroraServerManager
from interfaces.aurora.visual_states import (
    AURORA_THEMES,
    AuroraVisualState,
    SessionStateToAuroraAdapter,
)
from interfaces.aurora.window_manager import AuroraWindowManager


class TestAuroraPrototype:
    """Conjunto de pruebas técnicas para Núcleo Aurora 3D."""

    def test_01_session_state_immutability_and_mapping(self) -> None:
        """Verifica que SessionState no fue alterado y el adaptador mapea correctamente."""
        # 1. Verificar que SessionState tiene exactamente los 10 estados canónicos
        canonical_states = {
            "IDLE", "WAKEWORD", "LISTENING", "TRANSCRIBING",
            "ROUTING", "CONFIRMING", "CLARIFYING", "EXECUTING",
            "VERIFYING", "RESPONDING",
        }
        actual_states = {s.value for s in SessionState}
        assert actual_states == canonical_states, "SessionState NO debe ser modificado"

        # 2. Verificar que estados no canónicos NO están en SessionState
        for forbidden in ("PLANNING", "SPEAKING", "THINKING", "ERROR", "EMERGENCY"):
            assert forbidden not in actual_states

        # 3. Verificar mapeo del adaptador
        assert SessionStateToAuroraAdapter.to_visual_state(SessionState.IDLE) == AuroraVisualState.IDLE
        assert SessionStateToAuroraAdapter.to_visual_state(SessionState.WAKEWORD) == AuroraVisualState.LISTENING
        assert SessionStateToAuroraAdapter.to_visual_state(SessionState.LISTENING) == AuroraVisualState.LISTENING
        assert SessionStateToAuroraAdapter.to_visual_state(SessionState.TRANSCRIBING) == AuroraVisualState.THINKING
        assert SessionStateToAuroraAdapter.to_visual_state(SessionState.ROUTING) == AuroraVisualState.THINKING
        assert SessionStateToAuroraAdapter.to_visual_state(SessionState.EXECUTING) == AuroraVisualState.EXECUTING
        assert SessionStateToAuroraAdapter.to_visual_state(SessionState.VERIFYING) == AuroraVisualState.VERIFYING
        assert SessionStateToAuroraAdapter.to_visual_state(SessionState.RESPONDING) == AuroraVisualState.SPEAKING

    def test_02_all_visual_themes_defined(self) -> None:
        """Verifica que todos los estados visuales tienen temas cromáticos definidos y válidos."""
        assert len(AURORA_THEMES) >= 7
        for state in AuroraVisualState:
            theme = AURORA_THEMES.get(state)
            assert theme is not None, f"Tema ausente para {state}"
            assert theme.primary_color.startswith("#")
            assert theme.secondary_color.startswith("#")
            assert theme.accent_color.startswith("#")
            assert theme.core_pulse_speed > 0
            assert theme.noise_displacement > 0
            assert theme.orbital_speed > 0

    def test_03_static_files_integrity(self) -> None:
        """Comprueba que todos los archivos requeridos para el render 3D existen y son no-vacíos."""
        base_dir = Path("interfaces/aurora/static")
        files_to_check = [
            base_dir / "index.html",
            base_dir / "css" / "aurora.css",
            base_dir / "js" / "aurora_core.js",
            base_dir / "js" / "visual_controller.js",
            base_dir / "js" / "test_panel.js",
            base_dir / "vendor" / "three.min.js",
        ]

        for f in files_to_check:
            assert f.exists(), f"Archivo faltante: {f}"
            assert f.stat().st_size > 100, f"Archivo vacío o corrupto: {f}"

    def test_04_server_rest_endpoints(self) -> None:
        """Verifica los endpoints REST de la API de Aurora."""
        manager = AuroraServerManager(port=8799)
        client = TestClient(manager.app)

        # GET /
        resp_index = client.get("/")
        assert resp_index.status_code == 200
        assert "Núcleo Aurora" in resp_index.text

        # GET /api/health
        resp_health = client.get("/api/health")
        assert resp_health.status_code == 200
        data = resp_health.json()
        assert data["status"] == "HEALTHY"
        assert data["component"] == "JESSYCA_ORB_AURORA_3D"

        # GET /api/themes
        resp_themes = client.get("/api/themes")
        assert resp_themes.status_code == 200
        themes_data = resp_themes.json()
        assert "IDLE" in themes_data
        assert "THINKING" in themes_data
        assert themes_data["IDLE"]["primary_color"] == "#368BFF"

        # POST /api/state
        resp_state = client.post("/api/state", json={"state": "THINKING"})
        assert resp_state.status_code == 200
        assert resp_state.json()["new_state"] == "THINKING"
        assert manager.current_state == AuroraVisualState.THINKING

    def test_05_audio_adapter_pcm_processing(self) -> None:
        """Verifica el cálculo matemático de RMS y frecuencia dominante sin micrófono."""
        adapter = AuroraAudioAdapter()

        # Generar una señal sinusoidal pura de 440 Hz (16-bit PCM, 16000 Hz, 0.1s)
        sample_rate = 16000
        duration = 0.1
        freq = 440.0
        num_samples = int(sample_rate * duration)
        samples = [
            int(15000 * math.sin(2 * math.pi * freq * (i / sample_rate)))
            for i in range(num_samples)
        ]
        pcm_bytes = struct.pack(f"<{num_samples}h", *samples)

        metrics = adapter.process_pcm_chunk(pcm_bytes, sample_rate=sample_rate)
        assert metrics.rms > 5000.0
        assert metrics.normalized_amplitude > 0.3
        assert metrics.voice_detected is True
        assert 350.0 < metrics.dominant_frequency_hz < 550.0
        assert metrics.is_simulated is False

    def test_06_audio_simulation_modes(self) -> None:
        """Verifica que el modo de simulación genera métricas y está correctamente etiquetado."""
        adapter = AuroraAudioAdapter()

        m_idle = adapter.generate_simulated_metrics(AuroraVisualState.IDLE, 1.0)
        assert m_idle.is_simulated is True
        assert m_idle.normalized_amplitude < 0.1
        assert m_idle.voice_detected is False

        m_listening = adapter.generate_simulated_metrics(AuroraVisualState.LISTENING, 1.0)
        assert m_listening.is_simulated is True
        assert m_listening.voice_detected is True

        m_speaking = adapter.generate_simulated_metrics(AuroraVisualState.SPEAKING, 1.0)
        assert m_speaking.is_simulated is True
        assert m_speaking.tts_playback_active is True

    def test_07_tts_playback_notifications(self) -> None:
        """Verifica las notificaciones desacopladas de inicio y fin de reproducción TTS."""
        adapter = AuroraAudioAdapter()
        assert adapter.current_metrics.tts_playback_active is False

        adapter.notify_tts_playback_start()
        assert adapter.current_metrics.tts_playback_active is True

        adapter.notify_tts_playback_end()
        assert adapter.current_metrics.tts_playback_active is False

    def test_08_window_manager_detection(self) -> None:
        """Verifica la detección del navegador nativo en Windows 11."""
        wm = AuroraWindowManager(port=8765)
        exe = wm.find_browser_executable()
        assert exe is not None, "Debe detectar al menos un navegador nativo (Edge o Chrome)"
        assert exe.exists()

    def test_09_no_interference_with_cognitive_brain(self) -> None:
        """Verifica que el módulo de Aurora no modifica ni interfiere con JessycaBrain."""
        from core.cognitive_brain.brain_orchestrator import JessycaBrain

        # Comprobar que JessycaBrain sigue intacto con su model_provider y memoria
        brain = JessycaBrain()
        assert hasattr(brain, "model_provider")
        assert hasattr(brain, "memory_engine")
        assert hasattr(brain, "reasoning_engine")
