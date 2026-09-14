"""Tests de Integración: ActionIntentContract ↔ JessycaLocalAgent (Fase 64.1.4).

Verifica la integración progresiva, aditiva y compatible del ActionIntentContract
dentro de core/local_agent/local_agent.py.
"""

from unittest.mock import MagicMock

from core.emergency_stop import EmergencyStopManager
from core.interaction.interaction_models import ConfirmationPrompt
from core.local_agent import (
    AgentExecutionState,
    ConversationContextManager,
    InputModality,
    JessycaLocalAgent,
    JessycaRequest,
    LocalVoiceInterface,
)
from services.voice.audio_input import SyntheticAudioSource
from services.voice.stt_service import MockSTTService
from services.voice.tts_service import MockTTSService
from services.voice.wake_word_service import KeywordWakeWordService


class TestActionIntentContractIntegration:
    """Suite de integración de ActionIntentContract en JessycaLocalAgent."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_action_contract_setup")

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

    # ── A, B, C, D, E, I, J: ACCIÓN VÁLIDA CONSERVACIÓN Y CONTRATO ────────────
    def test_valid_action_produces_and_transports_contract(self) -> None:
        """Demuestra que LocalAgent produce/transporta un ActionIntentContract para una acción válida."""
        resp = self.agent.process_text("abre el bloc de notas", session_id="valid_action_session")

        assert resp.success is True
        assert resp.status == AgentExecutionState.COMPLETED
        assert resp.action_intent_contract is not None

        contract = resp.action_intent_contract
        # B) La intención se conserva
        assert contract.action_intent.intent_name == "open_application"
        # C) Confidence se conserva
        assert contract.action_intent.confidence >= 0.5
        # D) Parameters se conservan
        assert "app_name" in contract.action_intent.parameters
        # E) Target se conserva
        assert contract.action_intent.target in ("notepad", "bloc de notas", "bloc de notas.")
        # I) execution_report refleja el resultado real verificado (Fase 64.1.5)
        assert contract.execution_report is not None
        assert contract.execution_report.claims_success is True
        assert contract.execution_report.is_verified is True
        assert contract.execution_report.execution_status == "success"
        # J) post_action_feedback refleja la locución real generada
        assert contract.post_action_feedback is not None
        assert "bloc de notas" in contract.post_action_feedback.spoken_response.lower()
        # Gate
        assert contract.execution_gate.needs_clarification is False
        assert contract.execution_gate.needs_confirmation is False

    # ── F: ACLARACIONES SE CONSERVAN ─────────────────────────────────────────
    def test_ambiguous_action_preserves_clarification_in_contract(self) -> None:
        """Demuestra que una acción ambigua conserva needs_clarification y clarification_prompt."""
        resp = self.agent.process_text("abre por favor", session_id="clarif_contract_session")

        assert resp.status == AgentExecutionState.AWAITING_CLARIFICATION
        assert resp.requires_clarification is True
        assert resp.action_intent_contract is not None

        contract = resp.action_intent_contract
        assert contract.action_intent.is_ambiguous is True
        assert contract.execution_gate.needs_clarification is True
        assert contract.execution_gate.can_execute is False
        assert contract.execution_gate.clarification_prompt is not None
        assert len(contract.execution_gate.clarification_prompt) > 0
        # Anti false-success
        assert contract.execution_report is None
        assert contract.post_action_feedback is None

    # ── G: CONFIRMACIONES SE CONSERVAN ───────────────────────────────────────
    def test_sensitive_action_preserves_confirmation_in_contract(self) -> None:
        """Demuestra que una acción sensible conserva needs_confirmation, risk_level y prompt."""
        def user_rejects(prompt: ConfirmationPrompt) -> bool:
            return False

        req = JessycaRequest(
            user_input="elimina el archivo C:\\Temp\\test.tmp",
            session_id="confirm_contract_session",
            modality=InputModality.TEXT,
        )
        resp = self.agent.interact(
            request=req,
            user_confirmation_callback=user_rejects,
        )

        assert resp.status == AgentExecutionState.AWAITING_CONFIRMATION
        assert resp.requires_confirmation is True
        assert resp.action_intent_contract is not None

        contract = resp.action_intent_contract
        assert contract.execution_gate.needs_confirmation is True
        assert contract.execution_gate.can_execute is False
        assert contract.execution_gate.risk_level is not None
        assert contract.execution_gate.confirmation_prompt is not None
        assert len(contract.execution_gate.confirmation_prompt) > 0
        # Anti false-success
        assert contract.execution_report is None
        assert contract.post_action_feedback is None

    # ── H: CONVERSACIÓN NORMAL NO SE CONVIERTE EN ACCIÓN ─────────────────────
    def test_pure_conversational_turn_does_not_create_artificial_action(self) -> None:
        """Demuestra que 'Hola Jessyca' y '¿Cómo estás?' NO crean artificialmente un ActionIntentContract."""
        for greeting in ("Hola Jessyca", "¿Cómo estás?", "cuéntame algo"):
            resp = self.agent.process_text(greeting, session_id="chit_chat_session")
            assert resp.status == AgentExecutionState.COMPLETED
            # Conversación normal NO debe tener contrato de acción forzado
            assert resp.action_intent_contract is None

    # ── K: NO SE EJECUTA NINGUNA SKILL POR CREAR EL CONTRATO ─────────────────
    def test_no_skill_executed_simply_by_creating_contract(self) -> None:
        """Demuestra que el contrato es un snapshot y NO ejecuta skills directamente."""
        mock_skill_manager = MagicMock()
        self.agent.skill_manager = mock_skill_manager

        resp = self.agent.process_text("abre por favor", session_id="no_skill_session")
        assert resp.status == AgentExecutionState.AWAITING_CLARIFICATION
        assert resp.action_intent_contract is not None
        # Ninguna skill debe haberse ejecutado a través del skill_manager
        mock_skill_manager.execute_skill.assert_not_called()

    # ── L: COMPORTAMIENTO EXISTENTE Y SERIALIZACIÓN TO_DICT CONTINÚAN FUNCIONANDO ──
    def test_existing_behavior_and_serialization_preserved(self) -> None:
        """Demuestra que to_dict y campos existentes continúan operando normalmente."""
        resp = self.agent.process_text("abre el bloc de notas", session_id="compat_session")
        d = resp.to_dict()

        assert "request_id" in d
        assert "session_id" in d
        assert "success" in d
        assert "status" in d
        assert "response_text" in d
        assert "action_intent_contract" in d
        assert isinstance(d["action_intent_contract"], dict)
        assert d["action_intent_contract"]["action_intent"]["intent_name"] == "open_application"

    # ── METADATA & SESSION_ID / REQUEST_ID CONSERVADOS EN CONTRATO ────────────
    def test_request_id_and_session_id_reused_in_contract(self) -> None:
        """Demuestra que request_id y session_id del contexto se conservan en el contrato."""
        req = JessycaRequest(
            request_id="req-custom-999",
            session_id="session-custom-888",
            user_input="abre la calculadora",
            modality=InputModality.TEXT,
        )
        resp = self.agent.interact(request=req)
        assert resp.action_intent_contract is not None
        assert resp.action_intent_contract.request_id == "req-custom-999"
        assert resp.action_intent_contract.session_id == "session-custom-888"
