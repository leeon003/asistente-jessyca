"""Pruebas de Aceptación y Validación del Motor Agéntico Autónomo (JESSYCA 4.0 - Fase 3).

Valida de extremo a extremo:
1. "JESSYCA, abre YouTube y pon música clásica." -> Abre, busca, intenta reproducir y verifica.
2. "JESSYCA, investiga qué es el entrelazamiento cuántico." -> Síntesis conceptual profunda y búsqueda sin reducirse a abrir navegador en blanco.
3. "JESSYCA, abre Bloc de notas y escribe un resumen." -> Resuelve contenido, abre aplicación, escribe y verifica resultado.
4. "JESSYCA, baja el volumen, abre Chrome y busca información sobre Einstein." -> Descompone y ejecuta las 3 acciones secuenciales.
5. "JESSYCA, abre lo último que encontramos." -> Resuelve anáfora contextual o solicita aclaración si no hay historial.
6. Solicitudes ambiguas ("abre por favor") -> Solicita aclaración.
7. Cancelación y Confirmación -> Operación cancelada / confirmada limpiamente.
8. Despliegue Gradual y Mecanismo de Reversión (Feature Flag ON/OFF).
9. Ciclo agéntico canónico completo gobernado por JDE y RiskEngine.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.execution.execution_verifier import ExecutionEvidence
from core.intent.autonomous_engine import (
    AutonomousAgentEngine,
    AutonomousCycleResult,
)
from core.intent.models import IntentType, UserGoalInterpretation
from core.intent.sai_intent_engine import SaiIntentEngine, get_sai_intent_engine
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest, JessycaResponse
from skills.base_skill import BaseSkill
from skills.skill_manager import SkillManager
from skills.skill_models import SkillResult, SkillStatus


@pytest.fixture(autouse=True)
def clean_emergency_stop() -> None:
    """Asegura que el gestor de parada de emergencia esté restablecido antes y después de cada prueba."""
    mgr = get_emergency_stop_manager()
    mgr.reset("test_fase3_setup")
    yield
    mgr.reset("test_fase3_teardown")


class TestAutonomousAgentPhase3:
    """Suite integral de aceptación y verificación de Fase 3."""

    def test_01_acceptance_youtube_and_music(self) -> None:
        """EJEMPLO 1: 'JESSYCA, abre YouTube y pon música clásica.'
        Debe abrir, buscar, reproducir y verificar.
        """
        engine = AutonomousAgentEngine()
        res = engine.run_cycle(
            user_text="JESSYCA, abre YouTube y pon música clásica.",
            session_id="test_session_yt",
        )

        assert res.is_success is True
        assert res.intent_type in (IntentType.MULTI_STEP_PLAN, IntentType.SINGLE_ACTION)
        assert any("youtube" in t or "browser" in t for t in res.tools_executed)
        assert res.evidence is not None
        assert res.evidence.is_verified is True
        assert "completado" in res.spoken_text.lower() or "exitosamente" in res.spoken_text.lower()

    def test_02_acceptance_quantum_entanglement_research(self) -> None:
        """EJEMPLO 2: 'JESSYCA, investiga qué es el entrelazamiento cuántico.'
        Debe investigar o responder según requisitos de actualidad, sin reducir la solicitud a abrir un navegador en blanco.
        """
        engine = AutonomousAgentEngine()
        res = engine.run_cycle(
            user_text="JESSYCA, investiga qué es el entrelazamiento cuántico.",
            session_id="test_session_quantum",
        )

        assert res.is_success is True
        assert res.intent_type == IntentType.RESEARCH
        # No se limita a abrir un navegador en blanco: incluye síntesis conceptual rigurosa
        resp_lower = res.response_text.lower()
        assert "mecánica cuántica" in resp_lower or "mecanica cuantica" in resp_lower
        assert "partículas" in resp_lower or "particulas" in resp_lower
        assert "estado" in resp_lower or "distancia" in resp_lower

    def test_03_acceptance_notepad_and_write_summary(self) -> None:
        """EJEMPLO 3: 'JESSYCA, abre Bloc de notas y escribe un resumen.'
        Debe resolver el contenido relevante, abrir la aplicación, escribir y comprobar el resultado.
        """
        engine = AutonomousAgentEngine()
        context = {
            "last_investigation_summary": "El proyecto JESSYCA 4.0 superó la Fase 2 con éxito."
        }
        res = engine.run_cycle(
            user_text="JESSYCA, abre Bloc de notas y escribe un resumen.",
            session_id="test_session_notepad",
            session_context=context,
        )

        assert res.is_success is True
        assert any(r.skill_name == "windows.apps" for r in res.step_records)
        # Verifica que el parámetro text_to_write haya recibido el resumen
        notepad_step = next(r for r in res.step_records if r.skill_name == "windows.apps")
        assert "text_to_write" in notepad_step.parameters
        assert "JESSYCA 4.0" in notepad_step.parameters["text_to_write"]
        assert res.evidence is not None
        assert res.evidence.is_verified is True

    def test_04_acceptance_volume_chrome_and_einstein_search(self) -> None:
        """EJEMPLO 4: 'JESSYCA, baja el volumen, abre Chrome y busca información sobre Einstein.'
        Debe identificar y ejecutar las tres acciones secuencialmente.
        """
        engine = AutonomousAgentEngine()
        res = engine.run_cycle(
            user_text="JESSYCA, baja el volumen, abre Chrome y busca información sobre Einstein.",
            session_id="test_session_compound",
        )

        assert res.is_success is True
        assert res.intent_type == IntentType.MULTI_STEP_PLAN
        assert len(res.step_records) == 3
        assert res.tools_executed == ["windows.audio", "windows.apps", "browser.search"]
        assert res.completed_steps == 3
        # Validar verificación Anti-False Success en cada paso
        for record in res.step_records:
            assert record.success is True
            assert record.evidence is not None
            assert record.evidence.is_verified is True

    def test_05_acceptance_open_last_found_context_resolution(self) -> None:
        """EJEMPLO 5A: 'JESSYCA, abre lo último que encontramos.' con contexto previo.
        Debe utilizar el contexto para resolver la referencia de forma inequívoca.
        """
        engine = AutonomousAgentEngine()
        context = {
            "last_found_target": "C:\\Reportes\\balance_anual.pdf",
        }
        res = engine.run_cycle(
            user_text="JESSYCA, abre lo último que encontramos.",
            session_id="test_session_context",
            session_context=context,
        )

        assert res.is_success is True
        assert any(r.skill_name == "windows.apps" for r in res.step_records)
        step = res.step_records[0]
        assert "balance_anual.pdf" in str(step.parameters.get("app_name"))

    def test_06_acceptance_open_last_found_ambiguous_without_context(self) -> None:
        """EJEMPLO 5B: 'JESSYCA, abre lo último que encontramos.' SIN contexto previo.
        Debe preguntar cuando la referencia sea ambigua o no esté en el historial.
        """
        engine = AutonomousAgentEngine()
        res = engine.run_cycle(
            user_text="JESSYCA, abre lo último que encontramos.",
            session_id="test_session_empty_ctx",
            session_context={},
        )

        assert res.is_success is False
        assert res.requires_clarification is True
        assert "¿A qué elemento te refieres?" in res.clarification_question

    def test_07_ambiguous_request_clarification(self) -> None:
        """Comprueba que una orden ambigua e incompleta ('abre por favor') solicite aclaración."""
        engine = AutonomousAgentEngine()
        res = engine.run_cycle(
            user_text="JESSYCA, abre por favor.",
            session_id="test_session_ambiguous",
        )

        assert res.is_success is False
        assert res.requires_clarification is True
        assert "¿Podrías especificar qué aplicación" in res.clarification_question

    def test_08_cancellation_and_confirmation(self) -> None:
        """Comprueba el reconocimiento y despacho de cancelaciones y confirmaciones."""
        engine = AutonomousAgentEngine()
        res_cancel = engine.run_cycle(user_text="JESSYCA, cancela la tarea ahora mismo.")
        assert res_cancel.intent_type == IntentType.CANCELLATION
        assert res_cancel.is_success is True
        assert "cancelada" in res_cancel.spoken_text.lower()

        res_confirm = engine.run_cycle(user_text="JESSYCA, confirmo.")
        assert res_confirm.intent_type == IntentType.CONFIRMATION
        assert res_confirm.is_success is True

    def test_09_cascade_stop_on_step_failure(self) -> None:
        """Comprueba que si un paso de un plan multi-paso falla, la secuencia se detiene en cascada."""
        engine = AutonomousAgentEngine()
        # Mockeamos una skill para que falle deliberadamente
        mock_skill_mgr = MagicMock()
        mock_res_ok = SkillResult(skill_id="windows.audio", success=True, status=SkillStatus.COMPLETED)
        mock_res_fail = SkillResult(skill_id="windows.apps", success=False, status=SkillStatus.FAILED, error="App no encontrada")
        mock_skill_mgr.execute_skill.side_effect = [mock_res_ok, mock_res_fail]

        engine.skill_manager = mock_skill_mgr
        res = engine.run_cycle(
            user_text="Baja el volumen, abre programa_inexistente y busca información.",
            session_id="test_session_cascade",
        )

        assert res.is_success is False
        assert res.completed_steps == 1
        # No debe haber ejecutado el 3er paso
        assert len(res.step_records) == 2

    def test_10_feature_flag_rollback_mechanism(self) -> None:
        """Verifica el mecanismo de reversión y despliegue gradual mediante feature flag."""
        agent = JessycaLocalAgent.get_instance()

        # 1. Con flag activa (True): utiliza el motor autónomo
        with patch.dict(os.environ, {"JESSYCA_ENABLE_AUTONOMOUS_AGENT": "true"}):
            assert agent._is_autonomous_engine_enabled() is True
            intent, params, is_ambig = agent._resolve_intent("Baja el volumen y abre Chrome", "sess_flag_on")
            assert intent == "multistep_compound"
            assert "steps" in params
            assert len(params["steps"]) >= 2

        # 2. Con flag desactivada (False): mecanismo de reversión inmediata a motor legacy
        with patch.dict(os.environ, {"JESSYCA_ENABLE_AUTONOMOUS_AGENT": "false"}):
            assert agent._is_autonomous_engine_enabled() is False
            intent_leg, params_leg, is_ambig_leg = agent._resolve_intent("Baja el volumen y abre Chrome", "sess_flag_off")
            # El motor legacy resuelve solo una intención (pérdida de la segunda) sin crashear
            assert intent_leg in ("control_audio", "open_application", "open_browser")
