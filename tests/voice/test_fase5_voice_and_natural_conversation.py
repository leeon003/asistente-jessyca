"""Suite de Pruebas Integral para JESSYCA 4.0 — FASE 5: VOZ Y CONVERSACIÓN NATURAL.

Verifica:
1. Auditoría e integración de componentes de voz (STT, TTS, Barge-in, Emergency Stop).
2. Distinción conversacional:
   - Preguntas explicativas / científicas.
   - Conversación cotidiana sin frases comerciales ni autopresentaciones repetitivas.
   - Solicitudes de acciones directas (Desktop Controller).
   - Instrucciones compuestas.
   - Correcciones y cancelaciones.
   - Continuaciones de tareas contextuales.
3. Secuencia canónica de 6 diálogos:
   - "JESSYCA, ¿quién fue Albert Einstein?"
   - "JESSYCA, explícame el entrelazamiento cuántico."
   - "JESSYCA, abre Chrome."
   - "JESSYCA, ahora busca información sobre lo que acabamos de hablar."
   - "JESSYCA, detente."
   - "JESSYCA, continúa con la investigación anterior."
4. Configuración desacoplada en 'config/models_config.json' con baja latencia en Ollama.
5. Voces TTS compatibles en español y tolerancia a interrupciones (Barge-in).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.cancellation import CancellationToken
from core.desktop.unified_controller import DesktopActionResult, UnifiedDesktopController
from core.emergency_stop import EmergencyStopManager
from services.voice.barge_in_controller import BargeInController
from services.voice.natural_conversation_pipeline import (
    ConversationTurn,
    ConversationType,
    NaturalVoiceConversationPipeline,
)
from services.voice.stt_service import MockSTTService, TranscriptResult
from services.voice.tts_service import MockTTSService


@pytest.fixture(autouse=True)
def reset_emergency_stop():
    """Garantiza que la parada de emergencia esté limpia antes y después de cada prueba."""
    estop = EmergencyStopManager.get_instance()
    estop.reset(reason="test_setup", caller_id="system_admin")
    yield
    estop.reset(reason="test_teardown", caller_id="system_admin")


@pytest.fixture
def mock_desktop_controller():
    controller = MagicMock(spec=UnifiedDesktopController)
    controller.open_app.return_value = DesktopActionResult(
        success=True,
        action="open_app",
        target="chrome",
        evidence={"pid": 1234},
    )
    controller.close_app.return_value = DesktopActionResult(
        success=True,
        action="close_app",
        target="chrome.exe",
        evidence={},
    )
    controller.adjust_volume.return_value = {"success": True, "volume": 75}
    return controller


@pytest.fixture
def voice_pipeline(mock_desktop_controller):
    stt = MockSTTService(predefined_transcription="JESSYCA, abre Chrome.")
    tts = MockTTSService()
    pipeline = NaturalVoiceConversationPipeline(
        stt_service=stt,
        tts_service=tts,
        desktop_controller=mock_desktop_controller,
    )
    return pipeline


class TestFase5VoiceAndNaturalConversation:
    """Pruebas funcionales y de integración para la Fase 5."""

    def test_models_config_file_exists_and_valid(self):
        """Verifica que 'config/models_config.json' exista con el esquema esperado."""
        config_path = Path("config/models_config.json")
        assert config_path.exists(), "El archivo config/models_config.json debe existir."
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        assert "active_model" in cfg
        assert cfg["active_model"] == "llama3.2:latest"
        assert "system_voice" in cfg
        assert cfg["system_voice"]["default_voice"] == "es-PE-CamilaNeural"
        assert "conversation_policy" in cfg
        assert cfg["conversation_policy"]["anti_repetitive_pitch"] is True

    def test_normalize_input_removes_wake_word_prefixes(self, voice_pipeline):
        """Verifica la eliminación limpia de prefijos de activación."""
        assert voice_pipeline.normalize_input("JESSYCA, ¿quién fue Albert Einstein?") == "¿quién fue Albert Einstein?"
        assert voice_pipeline.normalize_input("Oye JESSYCA, abre Chrome") == "abre Chrome"
        assert voice_pipeline.normalize_input("hola jessyca, explícame la relatividad") == "explícame la relatividad"
        assert voice_pipeline.normalize_input("detente") == "detente"

    def test_classify_turn_categories(self, voice_pipeline):
        """Verifica la clasificación adecuada de cada categoría conversacional."""
        ctx = voice_pipeline.get_or_create_context("test_classification")

        # 1. Cancel / Stop
        c_type, _ = voice_pipeline.classify_turn("detente", ctx)
        assert c_type == ConversationType.CANCEL_STOP

        # 2. Direct Action
        c_type, meta = voice_pipeline.classify_turn("abre chrome", ctx)
        assert c_type == ConversationType.DIRECT_ACTION
        assert meta["action"] == "open_app"
        assert meta["target"] == "chrome"

        # 3. Question
        c_type, meta = voice_pipeline.classify_turn("¿quién fue Albert Einstein?", ctx)
        assert c_type == ConversationType.QUESTION
        assert "Albert Einstein" in meta["topic"]

        # 4. Continuation
        ctx.last_topic = "entrelazamiento cuántico"
        c_type, meta = voice_pipeline.classify_turn("ahora busca información sobre lo que acabamos de hablar", ctx)
        assert c_type == ConversationType.CONTINUATION
        assert meta["target_topic"] == "entrelazamiento cuántico"

        # 5. Compound instruction
        c_type, _ = voice_pipeline.classify_turn("abre chrome y luego busca noticias", ctx)
        assert c_type == ConversationType.COMPOUND_INSTRUCTION

        # 6. Correction
        c_type, _ = voice_pipeline.classify_turn("no, quise decir otra cosa", ctx)
        assert c_type == ConversationType.CORRECTION

    def test_canonical_dialogues_sequence(self, voice_pipeline, mock_desktop_controller):
        """Ejecuta y valida la secuencia completa de los 6 diálogos canónicos."""
        session_id = "canonical_session_phase5"

        # Turno 1: "¿quién fue Albert Einstein?"
        t1 = voice_pipeline.process_turn("JESSYCA, ¿quién fue Albert Einstein?", session_id=session_id)
        assert t1.conversation_type == ConversationType.QUESTION
        assert "albert einstein" in t1.context_topic.lower()
        assert len(t1.spoken_response) > 15
        assert "hola, soy jessyca" not in t1.spoken_response.lower()
        assert "ramy" not in t1.spoken_response.lower()

        # Turno 2: "explícame el entrelazamiento cuántico."
        t2 = voice_pipeline.process_turn("JESSYCA, explícame el entrelazamiento cuántico.", session_id=session_id)
        assert t2.conversation_type == ConversationType.QUESTION
        assert "entrelazamiento cuántico" in t2.context_topic.lower()
        assert len(t2.spoken_response) > 15
        assert "tienda" not in t2.spoken_response.lower()

        # Turno 3: "abre Chrome."
        t3 = voice_pipeline.process_turn("JESSYCA, abre Chrome.", session_id=session_id)
        assert t3.conversation_type == ConversationType.DIRECT_ACTION
        assert t3.action_executed == "open_app:chrome"
        assert t3.action_success is True
        assert "abierto chrome" in t3.spoken_response.lower()
        mock_desktop_controller.open_app.assert_called_with("chrome")

        # Turno 4: "ahora busca información sobre lo que acabamos de hablar."
        t4 = voice_pipeline.process_turn("JESSYCA, ahora busca información sobre lo que acabamos de hablar.", session_id=session_id)
        assert t4.conversation_type == ConversationType.CONTINUATION
        # Debe retomar el tema previo del turno 2
        assert "entrelazamiento cuántico" in t4.context_topic.lower()
        assert "buscando información" in t4.spoken_response.lower()
        assert t4.action_executed.startswith("browser_search:")

        # Turno 5: "detente."
        t5 = voice_pipeline.process_turn("JESSYCA, detente.", session_id=session_id)
        assert t5.conversation_type == ConversationType.CANCEL_STOP
        assert t5.action_executed == "emergency_stop"
        assert "detenido" in t5.spoken_response.lower()
        assert voice_pipeline.emergency_stop.is_stopped() is True

        # Turno 6: "continúa con la investigación anterior."
        t6 = voice_pipeline.process_turn("JESSYCA, continúa con la investigación anterior.", session_id=session_id)
        assert t6.conversation_type == ConversationType.CONTINUATION
        assert voice_pipeline.emergency_stop.is_stopped() is False  # Restablecido por la nueva orden
        assert "entrelazamiento cuántico" in t6.context_topic.lower()
        assert "investigación" in t6.spoken_response.lower() or "buscando" in t6.spoken_response.lower()

    def test_barge_in_and_interruption(self, voice_pipeline):
        """Verifica que el BargeInController detenga el TTS al detectar interrupción."""
        barge_in = voice_pipeline.barge_in
        cancel_token = CancellationToken()

        barge_in.notify_tts_started(cancel_token)
        assert barge_in.is_tts_active is True
        assert cancel_token.is_cancelled is False

        # El usuario interrumpe (barge-in)
        interrupted = barge_in.trigger_barge_in("User voice detected")
        assert interrupted is True
        assert cancel_token.is_cancelled is True
        assert barge_in.is_tts_active is False

    def test_voice_turn_from_audio_input(self, voice_pipeline):
        """Verifica el procesamiento de turnos recibidos en bytes de audio."""
        dummy_audio = b"\x00\x01" * 100
        voice_pipeline.stt_service.set_transcription("JESSYCA, abre la calculadora")

        turn = voice_pipeline.process_turn(dummy_audio, is_audio=True)
        assert turn.conversation_type == ConversationType.DIRECT_ACTION
        assert "calculator" in turn.action_executed or "calculadora" in turn.action_executed

    def test_casual_conversation_no_commercial_pitch(self, voice_pipeline):
        """Verifica conversación cotidiana natural sin mensajes comerciales o promocionales."""
        turn = voice_pipeline.process_turn("JESSYCA, ¿cómo estás?", session_id="casual_session")
        assert turn.conversation_type == ConversationType.CASUAL_CONVERSATION
        assert len(turn.spoken_response) > 5
        # Cero frases comerciales o repetitivas
        lower_resp = turn.spoken_response.lower()
        assert "tienda" not in lower_resp
        assert "comprar" not in lower_resp
        assert "ramy" not in lower_resp
        assert "hola, soy jessyca" not in lower_resp

    def test_volume_action_direct(self, voice_pipeline, mock_desktop_controller):
        """Verifica control y consulta de volumen del sistema operativo."""
        turn_set = voice_pipeline.process_turn("JESSYCA, sube el volumen", session_id="vol_session")
        assert turn_set.conversation_type == ConversationType.DIRECT_ACTION
        assert "75" in turn_set.spoken_response
        mock_desktop_controller.adjust_volume.assert_called()

        turn_get = voice_pipeline.process_turn("JESSYCA, cuál es el volumen", session_id="vol_session")
        assert turn_get.conversation_type == ConversationType.DIRECT_ACTION
        assert "volumen actual es del" in turn_get.spoken_response.lower()

    def test_compound_instruction_execution(self, voice_pipeline):
        """Verifica el despacho de instrucciones compuestas al AutonomousAgentEngine."""
        mock_engine = MagicMock()
        mock_engine.run_cycle.return_value = MagicMock(is_success=True, summary="Plan multi-paso ejecutado correctamente.")
        voice_pipeline.autonomous_engine = mock_engine

        turn = voice_pipeline.process_turn("JESSYCA, abre bloc de notas y escribe notas de reunión", session_id="compound_session")
        assert turn.conversation_type == ConversationType.COMPOUND_INSTRUCTION
        assert turn.action_executed == "compound_plan"
        assert turn.action_success is True
        assert "Plan multi-paso" in turn.spoken_response
        mock_engine.run_cycle.assert_called_once()

    def test_switch_model_dynamically_without_code_changes(self, tmp_path, mock_desktop_controller):
        """Verifica que el modelo se configure desde config/models_config.json sin tocar código."""
        custom_config = tmp_path / "custom_models_config.json"
        custom_config.write_text(
            json.dumps({
                "active_model": "qwen3:8b",
                "reasoning_model": "qwen3:8b",
                "system_voice": {"default_voice": "es-MX-DaliaNeural"}
            }),
            encoding="utf-8",
        )
        pipeline = NaturalVoiceConversationPipeline(
            config_path=custom_config,
            stt_service=MockSTTService(),
            tts_service=MockTTSService(),
            desktop_controller=mock_desktop_controller,
        )
        assert pipeline.active_model == "qwen3:8b"
        assert pipeline.config["system_voice"]["default_voice"] == "es-MX-DaliaNeural"

