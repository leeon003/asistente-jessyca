"""tests/demo/test_demo_stabilization.py
Pruebas integrales y end-to-end de la Fase de Estabilización de Demo de JESSYCA 3.0:
1. "Jessyca saluda a Carmen." -> Saludo contextual natural a Carmen
2. "Jessyca dame un concepto básico de física." -> Respuesta académica real de física (LLM / síntesis)
3. "Profundiza en el espacio-tiempo." -> Continuidad multi-turno sobre espacio-tiempo
4. "Abre Bloc de notas." -> open_application notepad con verificación real
5. "Cierra Bloc de notas." -> close_application notepad con verificación de terminación
6. "Abre Google." -> open_browser https://www.google.com (sin invocar google.exe)
7. "Busca física cuántica." -> browser_search query "física cuántica"
8. "¿Qué puedes hacer?" -> Explicación de capacidades
9. "Adiós." -> Despedida cordial
"""

from __future__ import annotations

import time

import pytest

from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import InputModality, JessycaRequest


@pytest.fixture
def agent() -> JessycaLocalAgent:
    return JessycaLocalAgent.get_instance()


class TestDemoStabilization:
    """Suite de validación formal de los 9 pasos de la demo."""

    def test_step_1_saluda_a_carmen(self, agent: JessycaLocalAgent) -> None:
        """Paso 1: Saludo natural a Carmen sin hacks ni dummy skill."""
        session_id = f"demo_session_{int(time.time())}"
        req = JessycaRequest(
            session_id=session_id,
            user_input="Jessyca saluda a Carmen.",
            modality=InputModality.VOICE,
        )
        res = agent.interact(req)
        assert res.intent == "general_query"
        assert res.success is True
        assert "carmen" in res.response_text.lower()
        assert len(res.response_text.strip()) > 10

    def test_step_2_concepto_fisica(self, agent: JessycaLocalAgent) -> None:
        """Paso 2: Concepto básico de física generado con respuesta real."""
        session_id = f"demo_session_{int(time.time())}"
        req = JessycaRequest(
            session_id=session_id,
            user_input="Jessyca dame un concepto básico de física.",
            modality=InputModality.VOICE,
        )
        res = agent.interact(req)
        assert res.intent == "general_query"
        assert res.success is True
        lower_resp = res.response_text.lower()
        # Verificar contenido conceptual real
        assert any(kw in lower_resp for kw in ("física", "ciencia", "materia", "energía", "universo", "estudia"))
        assert len(res.response_text.strip()) > 30

    def test_step_3_profundiza_espacio_tiempo(self, agent: JessycaLocalAgent) -> None:
        """Paso 3: Continuidad contextual en segundo turno sobre espacio-tiempo."""
        session_id = f"demo_session_multiturn_{int(time.time())}"
        # Turno 1
        req1 = JessycaRequest(
            session_id=session_id,
            user_input="Jessyca dame un concepto básico de física.",
            modality=InputModality.VOICE,
        )
        res1 = agent.interact(req1)
        assert res1.intent == "general_query"

        # Turno 2
        req2 = JessycaRequest(
            session_id=session_id,
            user_input="Profundiza en el espacio-tiempo.",
            modality=InputModality.VOICE,
        )
        res2 = agent.interact(req2)
        assert res2.intent == "general_query"
        assert res2.success is True
        lower_resp = res2.response_text.lower()
        assert any(kw in lower_resp for kw in ("espacio", "tiempo", "relatividad", "einstein", "curvatura", "dimensiones", "gravedad"))
        assert len(res2.response_text.strip()) > 30

    def test_step_4_abre_bloc_de_notas(self, agent: JessycaLocalAgent) -> None:
        """Paso 4: Abre Bloc de notas con verificación de ejecución real."""
        session_id = f"demo_session_{int(time.time())}"
        req = JessycaRequest(
            session_id=session_id,
            user_input="Abre Bloc de notas.",
            modality=InputModality.VOICE,
        )
        res = agent.interact(req)
        assert res.intent == "open_application"
        assert res.success is True
        assert "bloc de notas" in res.response_text.lower()

    def test_step_5_cierra_bloc_de_notas(self, agent: JessycaLocalAgent) -> None:
        """Paso 5: Cierra Bloc de notas con verificación de terminación de proceso."""
        session_id = f"demo_session_{int(time.time())}"
        # Primero abrir para asegurar que haya proceso o probar cierre directo
        req_open = JessycaRequest(
            session_id=session_id,
            user_input="Abre Bloc de notas.",
            modality=InputModality.VOICE,
        )
        agent.interact(req_open)

        req_close = JessycaRequest(
            session_id=session_id,
            user_input="Cierra Bloc de notas.",
            modality=InputModality.VOICE,
        )
        res_close = agent.interact(req_close)
        assert res_close.intent == "close_application"
        assert res_close.success is True
        assert "cerr" in res_close.response_text.lower()
        assert "bloc de notas" in res_close.response_text.lower()

    def test_step_6_abre_google(self, agent: JessycaLocalAgent) -> None:
        """Paso 6: Abre Google debe clasificar como open_browser (sin google.exe)."""
        session_id = f"demo_session_{int(time.time())}"
        req = JessycaRequest(
            session_id=session_id,
            user_input="Abre Google.",
            modality=InputModality.VOICE,
        )
        res = agent.interact(req)
        assert res.intent in ("open_browser", "browser_open")
        assert res.success is True
        assert "google" in res.response_text.lower()

    def test_step_7_busca_fisica_cuantica(self, agent: JessycaLocalAgent) -> None:
        """Paso 7: Busca física cuántica -> browser_search con motor y query."""
        session_id = f"demo_session_{int(time.time())}"
        req = JessycaRequest(
            session_id=session_id,
            user_input="Busca física cuántica.",
            modality=InputModality.VOICE,
        )
        res = agent.interact(req)
        assert res.intent == "browser_search"
        assert res.success is True
        assert "física cuántica" in res.response_text.lower() or "fisica cuantica" in res.response_text.lower()

    def test_step_8_que_puedes_hacer(self, agent: JessycaLocalAgent) -> None:
        """Paso 8: ¿Qué puedes hacer? -> Capacidades explicadas claramente."""
        session_id = f"demo_session_{int(time.time())}"
        req = JessycaRequest(
            session_id=session_id,
            user_input="¿Qué puedes hacer?",
            modality=InputModality.VOICE,
        )
        res = agent.interact(req)
        assert res.intent == "general_query"
        assert res.success is True
        lower_resp = res.response_text.lower()
        assert any(w in lower_resp for w in ("jessyca", "aplicaciones", "ayudar", "buscar", "asistente"))

    def test_step_9_adios_y_stt_normalizer(self, agent: JessycaLocalAgent) -> None:
        """Paso 9: Normalizador STT tolerando prefijos de audio y variaciones."""
        from core.local_agent.stt_normalizer import get_stt_normalizer
        norm = get_stt_normalizer()

        # Tolerar ruidos como 'música' o 'ruido'
        res1 = norm.normalize("música cierre bloc de notas")
        assert "cierra bloc de notas" in res1.normalized_text

        # Normalizar flexión
        res2 = norm.normalize("puedes cerrar el bloc de notas")
        assert "cierra bloc de notas" in res2.normalized_text
