"""Pruebas unitarias para JDE Shadow Mode (Fase 1 - Observabilidad y Control).

Verifica que el modo Shadow observe el tráfico sin alterar el sistema actual,
detecte divergencias de falsos éxitos y evalúe la postura de seguridad.
"""

from __future__ import annotations

import pytest

from core.jde.models import DecisionRequest, VerificationRequirement
from core.jde.shadow import JDEShadowMode
from core.jde.states import DecisionState


@pytest.fixture
def shadow_mode() -> JDEShadowMode:
    return JDEShadowMode()


def test_shadow_concordance_when_system_verified(shadow_mode: JDEShadowMode) -> None:
    req = DecisionRequest(
        user_request="Abre bloc de notas",
        intent="open_application",
        proposed_action="open",
        tool="windows.apps",
        verification_requirements=[
            VerificationRequirement(strategy="window_visible", target="notepad")
        ],
    )

    eval_result = shadow_mode.evaluate_shadow(
        request=req,
        current_system_success=True,
        current_system_message="Listo, abrí el Bloc de notas.",
        current_system_verified=True,
    )

    assert eval_result.is_divergent is False
    assert eval_result.jde_predicted_state == DecisionState.SUCCESS
    assert eval_result.divergence_reason is None


def test_shadow_detects_false_success_divergence(shadow_mode: JDEShadowMode) -> None:
    """Detecta cuando el sistema actual emite 'éxito' pero NO fue verificado."""
    req = DecisionRequest(
        user_request="Abre YouTube",
        intent="open_browser",
        proposed_action="open_url",
        tool="browser.open",
        verification_requirements=[
            VerificationRequirement(strategy="browser_tab", target="youtube.com")
        ],
    )

    eval_result = shadow_mode.evaluate_shadow(
        request=req,
        current_system_success=True,
        current_system_message="Listo, abrí YouTube.",
        current_system_verified=False,  # ¡No verificado en el SO!
    )

    assert eval_result.is_divergent is True
    assert eval_result.jde_predicted_state == DecisionState.UNKNOWN
    assert "Prevención de Falso Éxito" in (eval_result.divergence_reason or "")


def test_shadow_detects_security_policy_divergence(shadow_mode: JDEShadowMode) -> None:
    """Detecta cuando el sistema actual ejecuta una acción destructiva sin confirmación."""
    req = DecisionRequest(
        user_request="Elimina la carpeta temporal",
        intent="delete_directory",
        proposed_action="delete_recursive",
        tool="windows.files",
        risk_level="HIGH",
    )

    eval_result = shadow_mode.evaluate_shadow(
        request=req,
        current_system_success=True,
        current_system_message="Carpeta eliminada.",
        current_system_verified=True,
    )

    assert eval_result.is_divergent is True
    assert eval_result.jde_predicted_state == DecisionState.BLOCKED
    assert eval_result.jde_requires_confirmation is True
    assert "SECURITY_DIVERGENCE" in (eval_result.divergence_reason or "")


def test_shadow_history_and_divergence_filtering(shadow_mode: JDEShadowMode) -> None:
    req1 = DecisionRequest(
        user_request="Consulta la hora",
        intent="get_time",
        proposed_action="time",
        tool="system.time",
    )
    req2 = DecisionRequest(
        user_request="Mata el proceso CMD",
        intent="kill_process",
        proposed_action="kill",
        tool="windows.process",
        risk_level="HIGH",
    )

    shadow_mode.evaluate_shadow(req1, current_system_success=True, current_system_message="Son las 10:00", current_system_verified=True)
    shadow_mode.evaluate_shadow(req2, current_system_success=True, current_system_message="CMD terminado", current_system_verified=True)

    all_evals = shadow_mode.get_evaluations()
    divergences = shadow_mode.get_divergences()

    assert len(all_evals) == 2
    assert len(divergences) == 1
    assert divergences[0].intent == "kill_process"
