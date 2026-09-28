"""Pruebas de aplicación estricta (enforcement) en JessycaLocalAgent con JDE Runtime Binding.

Verifica:
- DENY impide al 100% que la herramienta o skill sea despachada (cero side effects).
- REQUIRE_REVIEW detiene el flujo y solicita confirmación sin ejecutar la herramienta.
- ALLOW permite el flujo continuo hacia el ejecutor y el verificador.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeMode,
    JDERuntimeVerdict,
    JDERuntimeVerdictType,
)
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest


@pytest.fixture
def mock_skill_manager():
    mgr = MagicMock()
    mgr.execute_skill.return_value = MagicMock(
        success=True,
        output={"exito": True, "mensaje": "Skill ejecutada con éxito."},
        error=None,
    )
    return mgr


def test_agent_enforces_jde_deny_blocks_side_effect(mock_skill_manager):
    """Verifica que un veredicto DENY impida rotundamente que skill_manager.execute_skill sea llamado."""
    mock_binding = MagicMock(spec=JDERuntimeBinding)
    mock_binding.evaluate.return_value = JDERuntimeVerdict(
        verdict=JDERuntimeVerdictType.DENY,
        reason="Operación bloqueada por política de seguridad JDE.",
        action="open_application",
        tool="windows.apps",
        risk_level="HIGH",
        runtime_mode=JDERuntimeMode.CONTROLLED,
        is_blocked=True,
    )

    agent = JessycaLocalAgent(
        skill_manager=mock_skill_manager,
        jde_runtime_binding=mock_binding,
    )

    req = JessycaRequest(user_input="abre el bloc de notas", session_id="test_deny_sess")
    resp = agent.interact(req)

    # 1. El veredicto de seguridad debe ser DENY
    assert resp.security_verdict == "DENY"
    assert resp.status == AgentExecutionState.FAILED
    assert not resp.success
    assert "Acción denegada por gobernanza JDE" in resp.response_text

    # 2. CERO SIDE EFFECTS: la skill NUNCA fue ejecutada
    mock_skill_manager.execute_skill.assert_not_called()


def test_agent_enforces_jde_require_review(mock_skill_manager):
    """Verifica que un veredicto REQUIRE_REVIEW solicite confirmación y no ejecute la skill."""
    mock_binding = MagicMock(spec=JDERuntimeBinding)
    mock_binding.evaluate.return_value = JDERuntimeVerdict(
        verdict=JDERuntimeVerdictType.REQUIRE_REVIEW,
        reason="Requiere confirmación explícita del usuario.",
        action="open_application",
        tool="windows.apps",
        risk_level="MEDIUM",
        runtime_mode=JDERuntimeMode.CONTROLLED,
        is_blocked=True,
        requires_human_confirmation=True,
    )

    agent = JessycaLocalAgent(
        skill_manager=mock_skill_manager,
        jde_runtime_binding=mock_binding,
    )

    req = JessycaRequest(user_input="abre el bloc de notas", session_id="test_review_sess")
    resp = agent.interact(req)

    assert resp.status == AgentExecutionState.AWAITING_CONFIRMATION
    assert resp.requires_confirmation is True
    assert "JDE requiere confirmación" in resp.response_text

    # CERO SIDE EFFECTS: la skill no se ejecuta
    mock_skill_manager.execute_skill.assert_not_called()


def test_agent_proceeds_on_jde_allow(mock_skill_manager):
    """Verifica que un veredicto ALLOW permita continuar hacia la ejecución de la skill y verificación."""
    mock_binding = MagicMock(spec=JDERuntimeBinding)
    mock_binding.evaluate.return_value = JDERuntimeVerdict(
        verdict=JDERuntimeVerdictType.ALLOW,
        reason="Acción autorizada por JDE.",
        action="open_application",
        tool="windows.apps",
        risk_level="SAFE",
        runtime_mode=JDERuntimeMode.CONTROLLED,
        is_blocked=False,
    )

    mock_skill_manager.execute_skill.return_value = MagicMock(
        success=True,
        output={
            "exito": True,
            "mensaje": "Notepad abierto.",
            "evidence": {"verification_type": "process", "target": "notepad", "is_verified": True},
        },
        error=None,
    )

    agent = JessycaLocalAgent(
        skill_manager=mock_skill_manager,
        jde_runtime_binding=mock_binding,
    )

    req = JessycaRequest(user_input="abre el bloc de notas", session_id="test_allow_sess")
    resp = agent.interact(req)

    # La skill fue invocada
    mock_skill_manager.execute_skill.assert_called_once()
    assert resp.success is True
    assert resp.status == AgentExecutionState.COMPLETED
