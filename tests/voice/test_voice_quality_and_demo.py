"""Suite de pruebas para el Modo Demo de Voz y Pipeline de Calidad de Audio (test_voice_quality_and_demo.py).

Verifica:
1. Captura de audio y manejo de errores STT.
2. Detección de silencios, audio corto y fragmentos.
3. Evaluación de calidad y confianza de transcripciones.
4. Enrutamiento controlado hacia agentes y skills sin bypass de seguridad.
5. Invariantes de parada de emergencia en modo voz.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.local_agent.local_agent import (
    AgentExecutionState,
    JessycaLocalAgent,
    JessycaRequest,
)
from core.local_agent.local_agent_models import InputModality
from core.local_agent.quality_analyzer import (
    IntentCompleteness,
    IntentCompletenessChecker,
    TranscriptQuality,
    TranscriptQualityAnalyzer,
)


@pytest.fixture(autouse=True)
def reset_local_agent():
    agent = JessycaLocalAgent.get_instance()
    agent.reset()
    yield
    agent.reset()


def test_transcript_quality_analyzer_empty_and_noise():
    """Valida que entradas vacías o compuestas por palabras aisladas de ruido sean rechazadas."""
    analyzer = TranscriptQualityAnalyzer()

    # Vacío
    res_empty = analyzer.analyze("")
    assert res_empty.quality == TranscriptQuality.EMPTY
    assert not res_empty.is_acceptable

    # Solo ruido / fragmento sospechoso único
    res_noise = analyzer.analyze("ab")
    assert res_noise.quality == TranscriptQuality.NOISE
    assert not res_noise.is_acceptable


def test_transcript_quality_analyzer_low_confidence():
    """Valida que transcripciones con baja confianza sean marcadas adecuadamente."""
    analyzer = TranscriptQualityAnalyzer(min_confidence=0.75)
    res = analyzer.analyze("abre calculadora", confidence=0.50)
    assert res.quality == TranscriptQuality.LOW_CONFIDENCE
    assert not res.is_acceptable
    assert "No te entendí bien" in (res.suggested_prompt or "")


def test_transcript_quality_analyzer_valid():
    """Valida que órdenes claras con alta confianza sean aceptadas."""
    analyzer = TranscriptQualityAnalyzer()
    res = analyzer.analyze("Jessica abre el bloc de notas", confidence=0.95)
    assert res.quality == TranscriptQuality.VALID
    assert res.is_acceptable
    assert res.normalized_text == "abre el bloc de notas"


def test_intent_completeness_checker_incomplete_patterns():
    """Valida detección de fragmentos incompletos como 'abre el', 'busca en', 'cierra'."""
    checker = IntentCompletenessChecker()

    assert checker.check_completeness("abre el").completeness == IntentCompleteness.INCOMPLETE
    assert checker.check_completeness("busca").completeness == IntentCompleteness.INCOMPLETE
    assert checker.check_completeness("cierra la").completeness == IntentCompleteness.INCOMPLETE
    assert checker.check_completeness("elimina").completeness == IntentCompleteness.INCOMPLETE
    assert checker.check_completeness("dame un informe de lo").completeness == IntentCompleteness.INCOMPLETE


def test_voice_request_with_wake_word_and_emergency_stop():
    """Verifica que si la parada de emergencia está activa, el modo voz rechaza la ejecución incondicionalmente."""
    agent = JessycaLocalAgent.get_instance()
    agent.emergency_stop()

    req = JessycaRequest(
        user_input="Jessica abre el bloc de notas",
        modality=InputModality.VOICE,
    )
    res = agent.interact(req)

    assert res.success is False
    assert res.status == AgentExecutionState.STOPPED
    assert "Parada de Emergencia activa" in res.response_text


def test_voice_request_close_application_verified():
    """Flujo de voz para cerrar aplicación con verificación de terminación."""
    agent = JessycaLocalAgent.get_instance()

    fake_proc = MagicMock()
    fake_proc.info = {"name": "notepad.exe", "pid": 1111}

    with patch("psutil.process_iter", side_effect=[[fake_proc], []]):
        req = JessycaRequest(
            user_input="Jessyca, cierra el bloc de notas",
            modality=InputModality.VOICE,
        )
        res = agent.interact(req)

        assert res.success is True
        assert res.intent == "close_application"
        assert res.selected_agent == "desktop_agent"
        assert "Listo, cerré el Bloc de notas." in res.response_text
