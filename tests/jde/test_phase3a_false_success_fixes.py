"""Tests obligatorios para JDE Fase 3A: Corrección de False Success Críticos.

Verifica determinísticamente que:
1. EXECUTOR SUCCESS != REAL WORLD SUCCESS
2. UNKNOWN != SUCCESS
3. NOT_VERIFIABLE != SUCCESS
4. claims_success <= is_verified (Invariante estricta de ActionIntentContract)
5. La confianza del LLM (1.0) NUNCA reemplaza la verificación física.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from core.execution.execution_verifier import ExecutionStatus
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest, InputModality


@pytest.fixture
def agent() -> JessycaLocalAgent:
    return JessycaLocalAgent()


# ── TEST 1: browser.open — executor OK pero verificación False -> UNKNOWN ──
def test_browser_open_unverified_produces_unknown_and_no_success(agent: JessycaLocalAgent) -> None:
    """Simular:
    executor → exito=True
    verification → False
    Resultado obligatorio:
    SUCCESS = False
    claims_success = False
    state = UNKNOWN
    Nunca debe producir un mensaje de éxito.
    """
    req = JessycaRequest(
        user_input="abre google",
        modality=InputModality.TEXT,
    )
    with patch.object(
        agent.skill_manager,
        "execute_skill",
        return_value=type(
            "SkillRes",
            (),
            {
                "success": True,
                "error": None,
                "output": {
                    "exito": True,
                    "executed": True,
                    "url": "https://www.google.com",
                    "verified": False,
                    "verification_status": "UNVERIFIED",
                },
            },
        )(),
    ):
        resp = agent.interact(req)

    # SUCCESS = False
    assert resp.success is False
    # state = UNKNOWN
    assert resp.status == AgentExecutionState.UNKNOWN

    # Contrato ActionIntentContract
    contract = resp.action_intent_contract
    assert contract is not None
    assert contract.execution_report is not None
    assert contract.execution_report.is_verified is False
    assert contract.execution_report.claims_success is False
    assert contract.execution_report.execution_status == "unknown"

    # Invariante claims_success <= is_verified
    assert not (contract.execution_report.claims_success and not contract.execution_report.is_verified)

    # Nunca debe producir un mensaje de éxito
    resp_text = resp.response_text.lower()
    assert "listo, abrí" not in resp_text
    assert "abierto correctamente" in resp_text or "no pude confirmar" in resp_text


# ── TEST 2: browser.open — executor falla -> FAILED ──
def test_browser_open_executor_failure_produces_failed(agent: JessycaLocalAgent) -> None:
    """Simular:
    executor → failure
    Resultado:
    FAILED
    """
    req = JessycaRequest(
        user_input="abre google",
        modality=InputModality.TEXT,
    )
    with patch.object(
        agent.skill_manager,
        "execute_skill",
        return_value=type(
            "SkillRes",
            (),
            {
                "success": False,
                "error": "El sistema no puede encontrar el archivo especificado",
                "output": {
                    "exito": False,
                    "mensaje": "Error al abrir la URL: msedge.exe no encontrado",
                    "verified": False,
                },
            },
        )(),
    ):
        resp = agent.interact(req)

    assert resp.success is False
    assert resp.status == AgentExecutionState.FAILED

    contract = resp.action_intent_contract
    assert contract is not None
    assert contract.execution_report is not None
    assert contract.execution_report.is_verified is False
    assert contract.execution_report.claims_success is False
    assert contract.execution_report.execution_status == "failed"

    resp_text = resp.response_text.lower()
    assert "no pude abrir" in resp_text or "error" in resp_text
    assert "listo" not in resp_text


# ── TEST 3: browser.search — executor OK pero no verificable -> UNKNOWN ──
def test_browser_search_unverified_produces_unknown(agent: JessycaLocalAgent) -> None:
    """Simular:
    executor → exito=True
    verification → False / unavailable
    Resultado:
    UNKNOWN
    Nunca: SUCCESS
    """
    req = JessycaRequest(
        user_input="busca python en google",
        modality=InputModality.TEXT,
    )
    with patch.object(
        agent.skill_manager,
        "execute_skill",
        return_value=type(
            "SkillRes",
            (),
            {
                "success": True,
                "error": None,
                "output": {
                    "exito": True,
                    "executed": True,
                    "query": "python",
                    "verified": False,
                    "verification_status": "UNVERIFIED",
                },
            },
        )(),
    ):
        resp = agent.interact(req)

    assert resp.success is False
    assert resp.status == AgentExecutionState.UNKNOWN

    contract = resp.action_intent_contract
    assert contract is not None
    assert contract.execution_report is not None
    assert contract.execution_report.is_verified is False
    assert contract.execution_report.claims_success is False
    assert contract.execution_report.execution_status == "unknown"

    resp_text = resp.response_text.lower()
    assert "listo, busqué" not in resp_text
    assert "no pude confirmar" in resp_text


# ── TEST 4: YouTube — execution accepted pero verification NOT_VERIFIABLE -> UNKNOWN ──
def test_youtube_not_verifiable_produces_unknown_never_success(agent: JessycaLocalAgent) -> None:
    """Simular:
    execution → accepted
    verification → NOT_VERIFIABLE
    Resultado:
    UNKNOWN
    Nunca: SUCCESS
    """
    req = JessycaRequest(
        user_input="reproduce Queen en youtube",
        modality=InputModality.TEXT,
    )
    with patch.object(
        agent.skill_manager,
        "execute_skill",
        return_value=type(
            "SkillRes",
            (),
            {
                "success": True,
                "error": None,
                "output": {
                    "exito": True,
                    "executed": True,
                    "query": "Queen",
                    "verified": False,
                    "verification_status": "NOT_VERIFIABLE",
                    "media_state": "MEDIA_UNKNOWN",
                    "mensaje": "Abrí la página de YouTube para 'Queen', pero no fue posible verificar la reproducción.",
                },
            },
        )(),
    ):
        resp = agent.interact(req)

    assert resp.success is False
    assert resp.status == AgentExecutionState.UNKNOWN

    contract = resp.action_intent_contract
    assert contract is not None
    assert contract.execution_report is not None
    assert contract.execution_report.is_verified is False
    assert contract.execution_report.claims_success is False
    assert contract.execution_report.execution_status == "unknown"

    resp_text = resp.response_text.lower()
    assert "listo, está reproduciendo" not in resp_text
    assert "no pude confirmar" in resp_text or "intenté reproducir" in resp_text


# ── TEST 5: Alta confianza del LLM (1.0) NUNCA reemplaza la verificación ──
def test_llm_high_confidence_never_replaces_verification(agent: JessycaLocalAgent) -> None:
    """Debe continuar pasando:
    LLM confidence = 1.0
    verification = False
    Resultado:
    NO SUCCESS
    La confianza del LLM nunca puede reemplazar la verificación.
    """
    req = JessycaRequest(
        user_input="abre google",
        modality=InputModality.TEXT,
        metadata={"confidence": 1.0, "llm_certainty": "ABSOLUTE"},
    )
    with patch.object(
        agent.skill_manager,
        "execute_skill",
        return_value=type(
            "SkillRes",
            (),
            {
                "success": True,
                "error": None,
                "output": {
                    "exito": True,
                    "executed": True,
                    "verified": False,
                    "verification_status": "UNVERIFIED",
                },
            },
        )(),
    ):
        resp = agent.interact(req)

    assert resp.success is False
    assert resp.status != AgentExecutionState.COMPLETED

    contract = resp.action_intent_contract
    assert contract is not None
    assert contract.action_intent.confidence == 1.0
    assert contract.execution_report is not None
    assert contract.execution_report.is_verified is False
    assert contract.execution_report.claims_success is False


# ── TEST 6: browser.open con verificación positiva real -> SUCCESS ──
def test_browser_open_verified_positive_produces_success(agent: JessycaLocalAgent) -> None:
    """Si existe evidencia real comprobada:
    SUCCESS = True
    claims_success = True
    state = COMPLETED
    JESSYCA puede informar éxito.
    """
    req = JessycaRequest(
        user_input="abre google",
        modality=InputModality.TEXT,
    )
    with patch.object(
        agent.skill_manager,
        "execute_skill",
        return_value=type(
            "SkillRes",
            (),
            {
                "success": True,
                "error": None,
                "output": {
                    "exito": True,
                    "executed": True,
                    "url": "https://www.google.com",
                    "verified": True,
                    "verification_status": "VERIFIED",
                },
            },
        )(),
    ):
        resp = agent.interact(req)

    assert resp.success is True
    assert resp.status == AgentExecutionState.COMPLETED

    contract = resp.action_intent_contract
    assert contract is not None
    assert contract.execution_report is not None
    assert contract.execution_report.is_verified is True
    assert contract.execution_report.claims_success is True

    resp_text = resp.response_text.lower()
    assert "listo, abrí" in resp_text


# ── TEST 7: YouTube con reproducción verificada -> SUCCESS ──
def test_youtube_verified_playback_produces_success(agent: JessycaLocalAgent) -> None:
    """Si la reproducción de YouTube está positivamente verificada:
    SUCCESS = True
    claims_success = True
    state = COMPLETED
    """
    req = JessycaRequest(
        user_input="reproduce Queen en youtube",
        modality=InputModality.TEXT,
    )
    with patch.object(
        agent.skill_manager,
        "execute_skill",
        return_value=type(
            "SkillRes",
            (),
            {
                "success": True,
                "error": None,
                "output": {
                    "exito": True,
                    "executed": True,
                    "query": "Queen",
                    "verified": True,
                    "verification_status": "VERIFIED",
                    "media_state": "PLAYING",
                    "mensaje": "Listo, está reproduciendo Queen en YouTube.",
                },
            },
        )(),
    ):
        resp = agent.interact(req)

    assert resp.success is True
    assert resp.status == AgentExecutionState.COMPLETED

    contract = resp.action_intent_contract
    assert contract is not None
    assert contract.execution_report is not None
    assert contract.execution_report.is_verified is True
    assert contract.execution_report.claims_success is True
    assert "reproduciendo" in resp.response_text.lower()
