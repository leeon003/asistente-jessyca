"""Test Suite Exhaustiva para JESSYCA Local Agent (Fase 45).

Cubre los 8 escenarios End-to-End mandatorios:
1. voice → open application ("Jessyca, abre el bloc de notas")
2. voice → search file ("Jessyca, busca mis documentos de ayer")
3. voice → browser ("Jessyca, busca en internet sobre IA")
4. voice → multi-step task ("Jessyca, investiga este tema")
5. voice → clarification (ambigüedad y slot-filling)
6. voice → confirmation (acción sensible con interacción humana)
7. voice → cancellation (interrupción / cancelación cooperativa)
8. voice → Emergency Stop (parada de emergencia prevalente por voz)

Además de pruebas para Text Pipeline, Multimodal Pipeline, Model Routing, Skill Routing y Métricas.
"""


from core.emergency_stop import EmergencyStopManager
from core.interaction.interaction_models import ConfirmationPrompt
from core.local_agent import (
    AgentExecutionState,
    ConversationContextManager,
    JessycaLocalAgent,
    LocalVoiceInterface,
)
from services.voice.audio_input import SyntheticAudioSource
from services.voice.stt_service import MockSTTService
from services.voice.tts_service import MockTTSService
from services.voice.wake_word_service import KeywordWakeWordService


class TestJessycaLocalAgentPhase45:
    """Suite de pruebas de certificación para JESSYCA Local Agent."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_local_agent_setup")

        self.audio_source = SyntheticAudioSource()
        self.wake_word_service = KeywordWakeWordService()
        self.stt_service = MockSTTService(predefined_transcription="abre el bloc de notas")
        self.tts_service = MockTTSService()

        self.voice_interface = LocalVoiceInterface(
            audio_source=self.audio_source,
            wake_word_service=self.wake_word_service,
            stt_service=self.stt_service,
            tts_service=self.tts_service,
            emergency_stop=self.emergency_stop,
        )

        self.context_manager = ConversationContextManager()
        self.agent = JessycaLocalAgent(
            voice_interface=self.voice_interface,
            context_manager=self.context_manager,
            emergency_stop=self.emergency_stop,
        )
        self.agent.reset()

    # ── 1. VOICE → OPEN APPLICATION ──
    def test_01_voice_open_application(self) -> None:
        """Verifica que el comando de voz 'Jessyca, abre el bloc de notas' seleccione internamente la skill y ejecute la acción."""
        self.stt_service.set_transcription("Jessyca, abre el bloc de notas.")
        self.wake_word_service.trigger_manually()

        resp = self.agent.process_voice(require_wake_word=True)

        assert resp.success is True
        assert resp.status == AgentExecutionState.COMPLETED
        assert resp.intent == "open_application"
        assert resp.selected_agent == "desktop_agent"
        assert resp.selected_skill == "windows.apps@1.0.0"
        assert "windows.launch_app" in resp.tools_executed
        assert "bloc de notas" in resp.response_text.lower()
        assert resp.metrics.wake_word_detected is True
        assert len(self.tts_service.spoken_texts) > 0

    # ── 2. VOICE → SEARCH FILE ──
    def test_02_voice_search_file(self) -> None:
        """Verifica que el comando de voz 'Jessyca, busca mis documentos de ayer' active el enrutamiento a file_agent."""
        self.stt_service.set_transcription("Jessyca, busca mis documentos de ayer.")

        resp = self.agent.process_voice(require_wake_word=False)

        assert resp.success is True
        assert resp.intent == "search_file"
        assert resp.selected_agent == "file_agent"
        assert resp.selected_skill == "files.search@1.0.0"
        assert "filesystem.search_files" in resp.tools_executed
        assert "documentos" in resp.response_text.lower()

    # ── 3. VOICE → BROWSER ──
    def test_03_voice_browser_search(self) -> None:
        """Verifica que el comando de voz 'Jessyca, busca en internet sobre IA' active browser_agent."""
        self.stt_service.set_transcription("Jessyca, busca en internet sobre inteligencia artificial.")

        resp = self.agent.process_voice(require_wake_word=False)

        assert resp.success is True
        assert resp.intent == "browser_search"
        assert resp.selected_agent == "browser_agent"
        assert resp.selected_skill == "browser.search@1.0.0"
        assert "browser.search" in resp.tools_executed
        assert "navegador" in resp.response_text.lower() or "inteligencia artificial" in resp.response_text.lower()

    # ── 4. VOICE → MULTI-STEP TASK ──
    def test_04_voice_multistep_research(self) -> None:
        """Verifica que el comando de voz 'Jessyca, investiga este tema' active la coordinación multi-paso."""
        self.stt_service.set_transcription("Jessyca, investiga este tema sobre computación cuántica.")

        resp = self.agent.process_voice(require_wake_word=False)

        assert resp.success is True
        assert resp.intent == "multistep_research"
        assert resp.selected_agent == "research_coordinator_agent"
        assert resp.selected_model == "qwen2.5-coder:7b"  # Modelo de alta capacidad para investigación
        assert "multistep.orchestrate" in resp.tools_executed

    # ── 5. VOICE → CLARIFICATION ──
    def test_05_voice_clarification_flow(self) -> None:
        """Verifica que un comando ambiguo active una solicitud de aclaración interactiva."""
        # Paso 1: Petición ambigua ("Abre por favor")
        self.stt_service.set_transcription("Jessyca, abre por favor.")
        resp1 = self.agent.process_voice(session_id="clarify_session")

        assert resp1.status == AgentExecutionState.AWAITING_CLARIFICATION
        assert resp1.requires_clarification is True
        assert "¿Podrías especificar" in resp1.response_text

        # Paso 2: Usuario responde con el slot faltante ("El bloc de notas")
        self.stt_service.set_transcription("El bloc de notas")
        resp2 = self.agent.process_voice(session_id="clarify_session")

        assert resp2.success is True
        assert resp2.status == AgentExecutionState.COMPLETED
        assert resp2.intent == "open_application"
        assert "bloc de notas" in resp2.response_text.lower()

    # ── 6. VOICE → CONFIRMATION ──
    def test_06_voice_confirmation_flow(self) -> None:
        """Verifica que una acción sensible exija confirmación humana y respete la decisión del usuario."""
        self.stt_service.set_transcription("Jessyca, elimina el archivo temporal C:\\Temp\\old.tmp")

        # Escenario A: Usuario NO aprueba
        def user_rejects(prompt: ConfirmationPrompt) -> bool:
            return False

        resp_rejected = self.agent.process_voice(
            user_confirmation_callback=user_rejects,
        )

        assert resp_rejected.status == AgentExecutionState.AWAITING_CONFIRMATION
        assert resp_rejected.requires_confirmation is True
        assert "¿Confirmas su ejecución?" in resp_rejected.response_text

        # Escenario B: Usuario APRUEBA
        def user_approves(prompt: ConfirmationPrompt) -> bool:
            return True

        resp_approved = self.agent.process_voice(
            user_confirmation_callback=user_approves,
        )

        assert resp_approved.success is True
        assert resp_approved.status == AgentExecutionState.COMPLETED

    # ── 7. VOICE → CANCELLATION ──
    def test_07_voice_cancellation(self) -> None:
        """Verifica que frases como 'cancela' o 'detente' interrumpan la interacción de forma limpia."""
        self.stt_service.set_transcription("Jessyca, cancela la operación.")

        resp = self.agent.process_voice()

        assert resp.success is False
        assert resp.status == AgentExecutionState.INTERRUPTED
        assert "cancelación por voz" in resp.response_text.lower() or "cancelada" in resp.response_text.lower()
        assert resp.metrics.interruption_handled is True

    # ── 8. VOICE → EMERGENCY STOP ──
    def test_08_voice_emergency_stop(self) -> None:
        """Verifica que una frase de emergencia active de inmediato la Parada de Emergencia global."""
        self.stt_service.set_transcription("Jessyca, parada de emergencia")

        resp = self.agent.process_voice()

        assert resp.success is False
        assert resp.status == AgentExecutionState.STOPPED
        assert self.emergency_stop.is_stopped() is True
        assert "parada de emergencia" in resp.response_text.lower()

    # ── 9. TEXT PIPELINE ──
    def test_09_text_pipeline(self) -> None:
        """Verifica la ejecución del pipeline de texto con preservación de contexto de conversación."""
        resp = self.agent.process_text("Jessyca, busca mis documentos")

        assert resp.success is True
        assert resp.intent == "search_file"
        assert resp.selected_agent == "file_agent"

        # Verificar historial en el gestor de contexto
        history = self.context_manager.get_history("default_session")
        assert len(history) == 1
        assert history[0].intent == "search_file"

    # ── 10. MULTIMODAL PIPELINE ──
    def test_10_multimodal_pipeline(self) -> None:
        """Verifica la ingestión y ejecución de peticiones enriquecidas con capturas y archivos."""
        dummy_screen = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        dummy_file = "D:\\Projects\\documento.pdf"

        resp = self.agent.process_multimodal(
            text="Analiza esta captura de pantalla y este archivo",
            screen_capture=dummy_screen,
            file_attachments=[dummy_file],
        )

        assert resp.success is True
        assert resp.intent in ("multistep_research", "general_query")
        assert resp.metrics.total_latency_ms > 0.0

    # ── 11. LATENCY AND QUALITY METRICS ──
    def test_11_voice_latency_and_quality_metrics(self) -> None:
        """Verifica que se midan y reporten todas las métricas de calidad de voz y latencia."""
        self.stt_service.set_transcription("Jessyca, abre el bloc de notas.")
        self.wake_word_service.trigger_manually()

        resp = self.agent.process_voice(require_wake_word=True)

        metrics = resp.metrics
        assert metrics.stt_accuracy > 0.0
        assert metrics.intent_latency_ms >= 0.0
        assert metrics.planning_latency_ms >= 0.0
        assert metrics.total_latency_ms > 0.0
        assert metrics.wake_word_detected is True
        assert "total_latency_ms" in metrics.to_dict()
