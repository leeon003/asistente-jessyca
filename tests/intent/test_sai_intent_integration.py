"""Tests de integración arquitectónica para el motor de intenciones SAI (tests/intent/test_sai_intent_integration.py).

Valida:
1. Invariante 1: En modo 'legacy', JessycaLocalAgent mantiene 100% el comportamiento anterior.
2. Invariante 2: En modo 'shadow', la respuesta ejecutada es la de legacy, y SAI se ejecuta de forma no bloqueante.
3. Invariante 3: En modo 'sai', órdenes compuestas se traducen en 'multistep_compound' con pasos ejecutables.
4. Invariante 4: En modo 'sai', correferencias contextuales ('abre eso') resuelven con el contexto de la sesión.
5. Invariante 5: Fallback resiliente: si el motor SAI falla, se conmuta automáticamente a legacy.
6. Invariante 6: Ejecución gobernada de plan compuesto valida cada paso y genera evidencia unificada.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from config.settings import AppSettings
from core.intent.models import (
    IntentType,
    PlannedActionStep,
    UserGoalInterpretation,
)
from core.intent.sai_intent_engine import SaiIntentEngine, get_sai_intent_engine
from core.local_agent.local_agent import (
    AgentExecutionState,
    InputModality,
    JessycaLocalAgent,
    JessycaRequest,
)


@pytest.fixture
def mock_settings():
    """Mockea get_settings con configuraciones controladas."""
    with patch("config.get_settings") as mock_get_set:
        s = AppSettings()
        mock_get_set.return_value = s
        yield s


class TestSaiIntentIntegration:
    """Suite de integración de modos de motor de intenciones."""

    def test_legacy_mode_preserves_original_behavior(self, monkeypatch):
        """Invariante 1: Con INTENT_ENGINE_MODE='legacy', opera con el motor regex existente."""
        monkeypatch.setenv("INTENT_ENGINE_MODE", "legacy")
        agent = JessycaLocalAgent()

        intent, params, ambiguous = agent._resolve_intent_and_slots("abre el bloc de notas", session_id="test_s1")
        assert intent == "open_application"
        assert "notepad" in str(params.get("app_name")).lower()

    def test_shadow_mode_executes_legacy_and_records_sai_telemetry(self, monkeypatch, caplog):
        """Invariante 2: Con INTENT_ENGINE_MODE='shadow', retorna legacy y ejecuta SAI pasivamente."""
        monkeypatch.setenv("INTENT_ENGINE_MODE", "shadow")
        agent = JessycaLocalAgent()

        with caplog.at_level(logging.DEBUG):
            intent, params, ambiguous = agent._resolve_intent_and_slots("baja el volumen a 30 y abre chrome", session_id="test_s2")

        # La respuesta es de legacy (que degrada o toma uno de los patrones)
        assert isinstance(intent, str)
        # Se ejecutó la telemetría shadow sin lanzar excepción
        assert any("SAI_SHADOW" in record.message for record in caplog.records)

    def test_shadow_mode_is_non_blocking_on_sai_failure(self, monkeypatch):
        """Invariante 2.1: Si el motor SAI explota en shadow, el flujo principal no se interrumpe."""
        monkeypatch.setenv("INTENT_ENGINE_MODE", "shadow")
        agent = JessycaLocalAgent()

        # Simular fallo en SAI engine
        with patch.object(agent.sai_intent_engine, "interpret", side_effect=RuntimeError("Simulated Ollama crash")):
            intent, params, ambiguous = agent._resolve_intent_and_slots("abre la calculadora", session_id="test_s3")

        # Debe continuar normalmente con legacy
        assert intent == "open_application"
        assert "calc" in str(params.get("app_name")).lower()

    def test_sai_mode_decomposes_compound_order(self, monkeypatch):
        """Invariante 3: En modo 'sai', una orden compuesta genera 'multistep_compound' con pasos."""
        monkeypatch.setenv("INTENT_ENGINE_MODE", "sai")
        agent = JessycaLocalAgent()

        intent, params, ambiguous = agent._resolve_intent_and_slots(
            "baja el volumen a 20, abre Chrome y busca el clima en Lima",
            session_id="test_s4",
        )

        assert intent == "multistep_compound"
        assert not ambiguous
        assert "steps" in params
        steps = params["steps"]
        assert len(steps) >= 3
        skills = [s["skill_name"] for s in steps]
        assert any(s in skills for s in ("windows.audio", "system.volume"))
        assert "windows.apps" in skills
        assert "browser.search" in skills

    def test_sai_mode_resolves_contextual_coreference(self, monkeypatch):
        """Invariante 4: En modo 'sai', 'abre eso' recupera la última app del contexto de sesión."""
        monkeypatch.setenv("INTENT_ENGINE_MODE", "sai")
        agent = JessycaLocalAgent()

        # Guardar en contexto de sesión
        sess = agent.context_manager.get_or_create_session("test_s5")
        sess.last_target_app = "spotify"

        intent, params, ambiguous = agent._resolve_intent_and_slots("abre eso", session_id="test_s5")
        assert intent == "open_application"
        assert params.get("app_name") == "spotify"

    def test_sai_mode_resilient_fallback_on_error(self, monkeypatch, caplog):
        """Invariante 5: Si el motor SAI falla en modo 'sai', se conmuta limpiamente a legacy."""
        monkeypatch.setenv("INTENT_ENGINE_MODE", "sai")
        agent = JessycaLocalAgent()

        with patch.object(agent.sai_intent_engine, "interpret", side_effect=Exception("Timeout connection")):
            with caplog.at_level(logging.WARNING):
                intent, params, ambiguous = agent._resolve_intent_and_slots("abre la calculadora", session_id="test_s6")

        assert "INTENT_ENGINE_FALLBACK" in caplog.text
        assert intent == "open_application"

    def test_multistep_compound_pipeline_execution(self, monkeypatch):
        """Invariante 6: Ejecución completa en interact() de un plan compuesto."""
        monkeypatch.setenv("INTENT_ENGINE_MODE", "sai")
        agent = JessycaLocalAgent()

        # Mockear las skills individuales para validar la orquestación segura
        mock_res_vol = MagicMock(success=True, output={"mensaje": "Volumen fijado en 20"}, error=None)
        mock_res_app = MagicMock(success=True, output={"mensaje": "Chrome abierto"}, error=None)
        mock_res_search = MagicMock(success=True, output={"mensaje": "Búsqueda realizada"}, error=None)

        def mock_exec(skill_name, parameters, session_id=None, **kwargs):
            if skill_name in ("system.volume", "windows.audio"):
                return mock_res_vol
            if skill_name == "windows.apps":
                return mock_res_app
            if skill_name == "browser.search":
                return mock_res_search
            return MagicMock(success=True, output={}, error=None)

        with patch.object(agent.skill_manager, "execute_skill", side_effect=mock_exec):
            req = JessycaRequest(
                user_input="baja el volumen a 20, abre Chrome y busca el clima en Lima",
                modality=InputModality.TEXT,
                session_id="test_s7",
            )
            resp = agent.interact(req)

        assert resp.success is True
        assert resp.status == AgentExecutionState.COMPLETED
        assert resp.intent == "multistep_compound"
        assert "He completado las siguientes acciones" in resp.response_text
        assert "browser.search" in resp.output_data.get("tools", [])
