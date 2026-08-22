"""Suite de Pruebas de Verificación Real de Ejecución e Invariantes Anti-Falsos Positivos.

Valida:
1. NO EXECUTION EVIDENCE = NO SUCCESS CLAIM.
2. Manejo de 'Jessica abre el bloc de notas' con éxito y con fallo de verificación.
3. Detección de transcripciones defectuosas ('pre calculadora').
4. Detección de frases incompletas ('Jessica dame un informe de lo').
5. Respuestas descriptivas para consultas de capacidades generales.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.execution.execution_verifier import (
    ExecutionEvidence,
    ExecutionResult,
    ExecutionStatus,
    ProcessExistsVerificationStrategy,
    ProcessTerminatedVerificationStrategy,
)
from core.local_agent.local_agent import (
    AgentExecutionState,
    JessycaLocalAgent,
    JessycaRequest,
)
from core.local_agent.quality_analyzer import (
    IntentCompleteness,
    IntentCompletenessChecker,
    SafeTextNormalizer,
    TranscriptQuality,
    TranscriptQualityAnalyzer,
)


@pytest.fixture(autouse=True)
def reset_local_agent():
    agent = JessycaLocalAgent.get_instance()
    agent.reset()
    yield
    agent.reset()


# ── 1. PRUEBAS DEL MODELO DE RESULTADO Y EVIDENCIA ──


def test_success_requires_execution_evidence():
    """Valida que claims_success solo sea True si status es SUCCEEDED y la evidencia está verificada."""
    # Sin evidencia
    res_no_ev = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        action="open_application",
        target="notepad",
        evidence=None,
    )
    assert not res_no_ev.claims_success

    # Con evidencia no verificada
    ev_unverified = ExecutionEvidence(
        verification_type="process_exists",
        target="notepad",
        is_verified=False,
    )
    res_unverified = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        action="open_application",
        target="notepad",
        evidence=ev_unverified,
    )
    assert not res_unverified.claims_success

    # Con evidencia verificada
    ev_verified = ExecutionEvidence(
        verification_type="process_exists",
        target="notepad",
        is_verified=True,
    )
    res_verified = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        action="open_application",
        target="notepad",
        evidence=ev_verified,
    )
    assert res_verified.claims_success


def test_failed_execution_cannot_report_success():
    """Un estado FAILED o VERIFICATION_FAILED nunca debe declarar éxito."""
    ev_verified = ExecutionEvidence(
        verification_type="process_exists",
        target="notepad",
        is_verified=True,
    )
    res_failed = ExecutionResult(
        status=ExecutionStatus.FAILED,
        action="open_application",
        target="notepad",
        evidence=ev_verified,
    )
    assert not res_failed.claims_success

    res_verif_failed = ExecutionResult(
        status=ExecutionStatus.VERIFICATION_FAILED,
        action="open_application",
        target="notepad",
        evidence=ev_verified,
    )
    assert not res_verif_failed.claims_success


# ── 2. PRUEBAS DE ESTRATEGIAS DE VERIFICACIÓN ──


def test_process_exists_strategy_success():
    """Verifica que la estrategia detecte un proceso simulado."""
    strat = ProcessExistsVerificationStrategy()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 1234, "name": "notepad.exe"}

    with patch("psutil.process_iter", return_value=[fake_proc]):
        evidence = strat.verify("open_application", "notepad", timeout_seconds=0.1)
        assert evidence.is_verified is True
        assert evidence.details["pids"] == [1234]


def test_process_exists_strategy_failure():
    """Verifica que la estrategia informe fallo si el proceso no existe."""
    strat = ProcessExistsVerificationStrategy()
    with patch("psutil.process_iter", return_value=[]):
        evidence = strat.verify("open_application", "notepad", timeout_seconds=0.1)
        assert evidence.is_verified is False


def test_process_terminated_strategy():
    """Verifica que la estrategia de terminación confirme cuando el proceso no está corriendo."""
    strat = ProcessTerminatedVerificationStrategy()
    with patch("psutil.process_iter", return_value=[]):
        evidence = strat.verify("close_application", "notepad", timeout_seconds=0.1)
        assert evidence.is_verified is True


# ── 3. PRUEBAS DE CALIDAD DE TRANSCRIPCIÓN Y COMPLETITUD ──


def test_defective_transcript_handling():
    """La transcripción defectuosa 'pre calculadora' debe marcarse como ambigua y solicitar aclaración."""
    analyzer = TranscriptQualityAnalyzer()
    res = analyzer.analyze("pre calculadora")
    assert res.quality == TranscriptQuality.AMBIGUOUS
    assert not res.is_acceptable
    assert any(phrase in (res.suggested_prompt or "").lower() for phrase in ("repetirlo", "abriera una aplicación", "no te entendí"))


def test_incomplete_phrase_handling():
    """La frase 'Jessica dame un informe de lo' debe detectarse como incompleta."""
    checker = IntentCompletenessChecker()
    cleaned, _ = SafeTextNormalizer.normalize_wake_prefix("Jessica dame un informe de lo")
    res = checker.check_completeness(cleaned)
    assert res.completeness == IntentCompleteness.INCOMPLETE
    assert res.missing_slot == "topic"
    assert "¿De qué tema quieres el informe?" in (res.clarification_question or "")


def test_name_variation_handling():
    """Variaciones del nombre deben removerse como prefijo sin alterar el resto."""
    for prefix in ("Jessica", "Jessyca", "Jessi", "Jessy", "oye jessica"):
        cleaned, had = SafeTextNormalizer.normalize_wake_prefix(f"{prefix}, abre el bloc de notas")
        assert had is True
        assert cleaned.lower() == "abre el bloc de notas"


# ── 4. PRUEBA END-TO-END DE APERTURA DE BLOC DE NOTAS ──


def test_notepad_verified_execution_flow():
    """Flujo exitoso: 'Jessica abre el bloc de notas' con proceso verificado."""
    agent = JessycaLocalAgent.get_instance()

    # Simular que subprocess lanza y psutil encuentra el proceso
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 9999, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", return_value=[fake_proc]):
        req = JessycaRequest(user_input="Jessica abre el bloc de notas")
        res = agent.interact(req)

        assert res.success is True
        assert res.status == AgentExecutionState.COMPLETED
        assert res.intent == "open_application"
        assert res.selected_agent == "desktop_agent"
        assert res.selected_skill == "windows.apps@1.0.0"
        assert "Listo, abrí el Bloc de notas." in res.response_text
        mock_popen.assert_called_once()


def test_notepad_verification_failure_flow():
    """Flujo fallido: 'Jessica abre el bloc de notas' donde el proceso NUNCA aparece."""
    agent = JessycaLocalAgent.get_instance()

    # Subprocess es llamado pero psutil NO encuentra ningún proceso notepad.exe
    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[]):
        req = JessycaRequest(user_input="Jessica abre el bloc de notas")
        res = agent.interact(req)

        # Regla: NO EXECUTION EVIDENCE = NO SUCCESS CLAIM
        assert res.success is False
        assert res.status == AgentExecutionState.FAILED
        assert "no confirmó que se haya abierto" in res.response_text
        assert "Listo, abrí" not in res.response_text


def test_incomplete_phrase_end_to_end():
    """Flujo incompleto: 'Jessica dame un informe de lo' solicita aclaración."""
    agent = JessycaLocalAgent.get_instance()

    req = JessycaRequest(user_input="Jessica dame un informe de lo")
    res = agent.interact(req)

    assert res.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert res.requires_clarification is True
    assert "¿De qué tema quieres el informe?" in res.response_text


def test_defective_transcript_end_to_end():
    """Flujo defectuoso: 'pre calculadora' solicita repetición sin ejecutar nada."""
    agent = JessycaLocalAgent.get_instance()

    with patch("subprocess.Popen") as mock_popen:
        req = JessycaRequest(user_input="pre calculadora")
        res = agent.interact(req)

        assert res.status == AgentExecutionState.AWAITING_CLARIFICATION
        assert res.requires_clarification is True
        mock_popen.assert_not_called()


def test_capability_query_response():
    """Flujo descriptivo: 'Hola Jessica Qué puedes hacer' describe capacidades reales."""
    agent = JessycaLocalAgent.get_instance()

    req = JessycaRequest(user_input="Hola Jessica Qué puedes hacer")
    res = agent.interact(req)

    assert res.success is True
    assert "Soy Jessyca, tu asistente local e inteligente para Windows" in res.response_text
    assert "abrir y cerrar aplicaciones" in res.response_text
    assert res.response_text != "He completado tu solicitud con éxito."
