"""Suite de Certificación y Pruebas Obligatorias de Integración para JESSYCA ORB — Núcleo Aurora 3D.

Verifica:
1. Inicio del orbe (Runtime, servidor FastAPI, WebSocket y ventana).
2. Transición reactiva IDLE → LISTENING.
3. Activación por voz (WakeWordDetected -> WAKEWORD con onda de energía).
4. Animación de pensamiento e inferencia cognitiva (TRANSCRIBING / ROUTING).
5. Animación durante ejecución de herramientas (EXECUTING).
6. Animación durante búsqueda web o investigación (subestado SEARCHING).
7. Sincronización con voz TTS (RESPONDING y telemetría de amplitud).
8. Interrupción por barge-in (UserInterrupted -> corte inmediato y retorno a LISTENING).
9. Manejo de error y recuperación visual automática (ERROR -> IDLE).
10. Cierre sin procesos colgados y liberación limpia de recursos.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

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
from core.state.context import StateContext
from core.state.machine import StateMachine
from core.state.states import SessionState
from interfaces.aurora.bridge import AuroraBridge
from interfaces.aurora.runtime import AuroraRuntime
from interfaces.aurora.server import AuroraServerManager
from interfaces.aurora.visual_states import (
    AURORA_THEMES,
    AuroraVisualState,
    SessionStateToAuroraAdapter,
)


class TestAuroraIntegrationSuite:
    """Suite de validación formal de los 10 puntos de integración de JESSYCA ORB."""

    def test_01_orb_startup_and_server_health(self) -> None:
        """PRUEBA 1: Inicio del orbe, endpoints REST y estado saludable."""
        manager = AuroraServerManager(port=8791)
        client = TestClient(manager.app)

        # 1. Comprobar index HTML
        resp_index = client.get("/")
        assert resp_index.status_code == 200
        assert "Núcleo Aurora 3D & Fusión Reactiva" in resp_index.text

        # 2. Comprobar health
        resp_health = client.get("/api/health")
        assert resp_health.status_code == 200
        health_data = resp_health.json()
        assert health_data["status"] == "HEALTHY"
        assert health_data["component"] == "JESSYCA_ORB_AURORA_3D"

        # 3. Comprobar que todos los temas requeridos están disponibles
        resp_themes = client.get("/api/themes")
        assert resp_themes.status_code == 200
        themes = resp_themes.json()
        for required_state in (
            "IDLE", "WAKEWORD", "LISTENING", "TRANSCRIBING",
            "ROUTING", "CLARIFYING", "CONFIRMING", "EXECUTING",
            "SEARCHING", "VERIFYING", "RESPONDING", "ERROR",
        ):
            assert required_state in themes, f"Tema ausente: {required_state}"

    def test_02_idle_to_listening_transition(self) -> None:
        """PRUEBA 2: Transición real IDLE -> LISTENING en la StateMachine."""
        sm = StateMachine(follow_up_window=10.0)
        manager = AuroraServerManager(port=8792)
        bridge = AuroraBridge(server_manager=manager, state_machine=sm)

        assert bridge.server_manager.current_state == AuroraVisualState.IDLE

        # Transición en StateMachine
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)

        assert sm.current_state == SessionState.LISTENING
        assert bridge.server_manager.current_state == AuroraVisualState.LISTENING

    def test_03_wakeword_activation_and_energy_pulse(self) -> None:
        """PRUEBA 3: Activación por voz ante WakeWordDetected."""
        bus = EventBus()
        manager = AuroraServerManager(port=8793)
        bridge = AuroraBridge(server_manager=manager, event_bus=bus)

        event = WakeWordDetected(wake_word="jessyca", confidence=0.98)
        bus.publish(event)

        assert bridge.server_manager.current_state == AuroraVisualState.WAKEWORD

    def test_04_thinking_and_routing_animation(self) -> None:
        """PRUEBA 4: Animación de procesamiento fonético y enrutamiento cognitivo."""
        bus = EventBus()
        manager = AuroraServerManager(port=8794)
        bridge = AuroraBridge(server_manager=manager, event_bus=bus)

        # STT finalizado -> TRANSCRIBING
        bus.publish(UtteranceFinal(text="abre el bloc de notas", confidence=0.95))
        assert bridge.server_manager.current_state == AuroraVisualState.TRANSCRIBING

        # Clasificación de intención / inferencia -> ROUTING
        bus.publish(IntentClassified(intent="open_application", confidence=0.99))
        assert bridge.server_manager.current_state == AuroraVisualState.ROUTING

    def test_05_tool_execution_animation(self) -> None:
        """PRUEBA 5: Animación durante la ejecución de herramientas del sistema."""
        bus = EventBus()
        manager = AuroraServerManager(port=8795)
        bridge = AuroraBridge(server_manager=manager, event_bus=bus)

        # Herramienta general de sistema -> EXECUTING
        bus.publish(ActionProposed(action_name="windows.apps.open", parameters={"app": "notepad"}))
        assert bridge.server_manager.current_state == AuroraVisualState.EXECUTING

        # Verificación post-ejecución -> VERIFYING
        bus.publish(VerificationResult(action_name="windows.apps.open", verified=True))
        assert bridge.server_manager.current_state == AuroraVisualState.VERIFYING

    def test_06_searching_substate_animation(self) -> None:
        """PRUEBA 6: Activación del subestado SEARCHING ante búsquedas web o investigación."""
        bus = EventBus()
        manager = AuroraServerManager(port=8796)
        bridge = AuroraBridge(server_manager=manager, event_bus=bus)

        # Acción de búsqueda web o archivos
        bus.publish(ActionProposed(action_name="browser.search", parameters={"query": "clima lima"}))
        assert bridge.server_manager.current_state == AuroraVisualState.SEARCHING

        # Acción de búsqueda en ficheros
        bus.publish(ActionProposed(action_name="files.search", parameters={"pattern": "*.txt"}))
        assert bridge.server_manager.current_state == AuroraVisualState.SEARCHING

    def test_07_tts_synchronization_and_audio_modulation(self) -> None:
        """PRUEBA 7: Sincronización con TTS y modulación de amplitud acústica."""
        manager = AuroraServerManager(port=8797)
        bridge = AuroraBridge(server_manager=manager)

        assert bridge._is_tts_playing is False

        # Iniciar locución TTS
        bridge.notify_tts_start("Hola, estoy lista para ayudarte con tus tareas en Windows.")
        assert bridge._is_tts_playing is True
        assert bridge.server_manager.current_state == AuroraVisualState.RESPONDING

        # Esperar 100ms para verificar modulación silábica activa
        time.sleep(0.12)
        assert bridge._smoothed_amplitude > 0.0

        # Finalizar locución
        bridge.notify_tts_end(interrupted=False)
        assert bridge._is_tts_playing is False
        assert bridge.server_manager.current_state == AuroraVisualState.IDLE

    def test_08_barge_in_interruption(self) -> None:
        """PRUEBA 8: Interrupción inmediata por habla del usuario (Barge-in)."""
        bus = EventBus()
        manager = AuroraServerManager(port=8798)
        bridge = AuroraBridge(server_manager=manager, event_bus=bus)

        bridge.notify_tts_start("Estoy explicando una respuesta larga que el usuario va a cortar...")
        assert bridge._is_tts_playing is True
        assert bridge.server_manager.current_state == AuroraVisualState.RESPONDING

        # Publicar interrupción del usuario
        bus.publish(UserInterrupted(reason="barge_in_vad"))

        # El habla debe cortarse de inmediato y retornar a LISTENING
        assert bridge._is_tts_playing is False
        assert bridge.server_manager.current_state == AuroraVisualState.LISTENING

    def test_09_error_recovery(self) -> None:
        """PRUEBA 9: Notificación de error visual ámbar y auto-recuperación a IDLE."""
        bus = EventBus()
        manager = AuroraServerManager(port=8799)
        bridge = AuroraBridge(server_manager=manager, event_bus=bus)

        # Disparar error
        bus.publish(ErrorOccurred(error_message="Fallo temporal simulado", error_type="NetworkTimeout"))
        assert bridge.server_manager.current_state == AuroraVisualState.ERROR

        # Auto-recuperación acelerada (0.2s)
        bridge.notify_error(duration_sec=0.25)
        time.sleep(0.35)
        assert bridge.server_manager.current_state == AuroraVisualState.IDLE

    def test_10_clean_shutdown_no_hanging_resources(self) -> None:
        """PRUEBA 10: Cierre ordenado y liberación limpia de todos los recursos."""
        runtime = AuroraRuntime(port=8801, headless=True)
        started = runtime.start()
        assert started is True
        assert runtime._is_running is True

        # Detener runtime
        runtime.stop()
        assert runtime._is_running is False
        assert AuroraRuntime.get_active_runtime() is None
