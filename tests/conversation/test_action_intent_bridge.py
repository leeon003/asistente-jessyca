"""Tests unitarios para el Bridge entre Diálogo/Planificación y Action Intent Contract (Fase 64.1.3).

Verifica exhaustivamente:
A) Conversión correcta de intención existente a ActionIntent.
B) Conservación exacta de la confianza (confidence).
C) Conservación íntegra de parámetros y target inferido.
D) Conservación de la información de aclaración (needs_clarification, clarification_prompt).
E) Conservación de la información de confirmación (needs_confirmation, confirmation_prompt).
F) Conservación del nivel de riesgo precalculado.
G) Invariante Anti-False Success: execution_report permanece estrictamente None.
H) Invariante: post_action_feedback permanece estrictamente None.
I) Aislamiento total: No se ejecuta ninguna Skill durante el puenteo.
J) Caso ambiguo conserva su estado y bloquea ejecución prematura (can_execute=False).
K) Caso que requiere confirmación conserva su estado y bloquea ejecución prematura (can_execute=False).
L) Conversión directa desde ActionPlan mediante bridge_action_plan_to_contract.
M) ExecutionSpec se construye únicamente cuando existen skill_id e idempotency_key legítimos.
"""

from __future__ import annotations

from unittest.mock import patch

from core.dialogue.action_intent_bridge import (
    bridge_action_plan_to_contract,
    bridge_dialogue_to_contract,
)
from core.dialogue.dialogue_models import (
    ActionPlan,
    ActionPlanStep,
    CapabilityLevel,
    DialogueActionType,
    DialogueDecision,
)

# ==============================================================================
# A, B, C) CONVERSIÓN BÁSICA, CONFIANZA Y PARÁMETROS
# ==============================================================================

def test_bridge_direct_action_intent_and_parameters() -> None:
    """A, B, C) Una intención existente directa se convierte fielmente conservando target, params y confianza."""
    decision = DialogueDecision(
        action_type=DialogueActionType.DIRECT_ACTION,
        capability_level=CapabilityLevel.FULL,
        response_text="Claro, te abro el Bloc de notas.",
        pre_action_speech="Claro, te abro el Bloc de notas.",
    )

    contract = bridge_dialogue_to_contract(
        decision=decision,
        user_input="Abre el Bloc de notas",
        intent="open_application",
        params={"app_name": "notepad", "mode": "maximized"},
        confidence=0.92,
        input_modality="voice",
        request_id="req-test-01",
        session_id="session-test-01",
    )

    # A) ActionIntent creado
    assert contract.action_intent.intent_name == "open_application"
    assert contract.action_intent.input_modality == "voice"
    assert contract.action_intent.target == "notepad"
    assert contract.action_intent.is_ambiguous is False

    # B) Confianza conservada
    assert contract.action_intent.confidence == 0.92

    # C) Parámetros conservados
    assert contract.action_intent.parameters == {"app_name": "notepad", "mode": "maximized"}

    # Identificadores
    assert contract.request_id == "req-test-01"
    assert contract.session_id == "session-test-01"

    # Gate debe permitir ejecución
    assert contract.execution_gate.can_execute is True
    assert contract.execution_gate.needs_clarification is False
    assert contract.execution_gate.needs_confirmation is False

    # Pre-action feedback extraído
    assert contract.pre_action_feedback.acknowledgement_speech == "Claro, te abro el Bloc de notas."


# ==============================================================================
# D, J) INFORMACIÓN DE ACLARACIÓN Y CASOS AMBIGUOS
# ==============================================================================

def test_bridge_clarification_preserves_prompt_and_blocks_execution() -> None:
    """D, J) Una aclaración conversacional o caso ambiguo conserva su prompt y bloquea ejecución (can_execute=False)."""
    decision = DialogueDecision(
        action_type=DialogueActionType.CLARIFICATION,
        capability_level=CapabilityLevel.FULL,
        response_text="¿Podrías especificar qué aplicación deseas abrir?",
        clarification_question="¿Podrías especificar qué aplicación deseas abrir?",
        expected_slot="app_name",
        is_terminal=False,
    )

    contract = bridge_dialogue_to_contract(
        decision=decision,
        user_input="Abre la aplicación",
        intent="open_application",
        params={},
        is_ambiguous=True,
    )

    assert contract.action_intent.is_ambiguous is True
    assert contract.action_intent.missing_slots == ["app_name"]
    assert contract.execution_gate.can_execute is False
    assert contract.execution_gate.needs_clarification is True
    assert contract.execution_gate.clarification_prompt == "¿Podrías especificar qué aplicación deseas abrir?"


# ==============================================================================
# E, F, K) INFORMACIÓN DE CONFIRMACIÓN Y RIESGO
# ==============================================================================

def test_bridge_confirmation_and_risk_preservation() -> None:
    """E, F, K) Una acción sensible conserva la necesidad de confirmación, su prompt y su nivel de riesgo."""
    decision = DialogueDecision(
        action_type=DialogueActionType.REQUIRE_CONFIRMATION,
        capability_level=CapabilityLevel.FULL,
        response_text="¿Confirmas que deseas eliminar el archivo temporal?",
        is_terminal=False,
    )

    contract = bridge_dialogue_to_contract(
        decision=decision,
        user_input="Elimina temp.tmp",
        intent="delete_file",
        params={"path": "C:\\temp.tmp"},
        risk_level="HIGH",
    )

    assert contract.execution_gate.can_execute is False
    assert contract.execution_gate.needs_confirmation is True
    assert contract.execution_gate.confirmation_prompt == "¿Confirmas que deseas eliminar el archivo temporal?"
    assert contract.execution_gate.risk_level == "HIGH"


# ==============================================================================
# G, H) REPORT Y POST-ACTION FEEDBACK PERMANECEN STRICTAMENTE NONE
# ==============================================================================

def test_bridge_guarantees_no_premature_execution_report_or_post_feedback() -> None:
    """G, H) Invariantes estrictas: execution_report y post_action_feedback deben ser None antes de ejecutar."""
    decision = DialogueDecision(
        action_type=DialogueActionType.DIRECT_ACTION,
        capability_level=CapabilityLevel.FULL,
        response_text="Listo, voy a reproducir la música.",
    )

    contract = bridge_dialogue_to_contract(
        decision=decision,
        user_input="Pon música",
        intent="play_random_video",
        params={},
    )

    assert contract.execution_report is None, "Invariante violada: execution_report no debe existir antes de la ejecución real."
    assert contract.post_action_feedback is None, "Invariante violada: post_action_feedback no debe existir antes de la ejecución real."


# ==============================================================================
# I) TOTAL AISLAMIENTO DE EJECUCIÓN (NO INVOCA SKILLS)
# ==============================================================================

def test_bridge_does_not_execute_any_skill_or_system_action() -> None:
    """I) El bridge es estrictamente observacional; no invoca subprocess, os, ni ejecutores de skills."""
    with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
        decision = DialogueDecision(
            action_type=DialogueActionType.DIRECT_ACTION,
            capability_level=CapabilityLevel.FULL,
            response_text="Abriendo Bloc de notas...",
        )
        contract = bridge_dialogue_to_contract(
            decision=decision,
            user_input="Abre el Bloc de notas",
            intent="open_application",
            params={"app_name": "notepad"},
        )

        assert contract is not None
        mock_popen.assert_not_called()
        mock_run.assert_not_called()


# ==============================================================================
# L) CONVERSIÓN DESDE ActionPlan DIRECTAMENTE
# ==============================================================================

def test_bridge_action_plan_direct_conversion() -> None:
    """L) Un ActionPlan directo se convierte coherentemente en un ActionIntentContract."""
    step = ActionPlanStep(
        step_number=1,
        intent="open_application",
        skill_id="windows.apps@1.0.0",
        tool_name="windows.launch_app",
        parameters={"accion": "abrir", "nombre_app": "calc"},
        description="Abrir la Calculadora",
    )
    plan = ActionPlan(
        plan_id="plan-calc-1",
        intent="open_application",
        steps=[step],
        summary_speech="Claro, voy a abrir la Calculadora.",
        is_composite=False,
    )

    contract = bridge_action_plan_to_contract(
        plan=plan,
        user_input="Abre la calculadora",
        params={"app_name": "calc"},
        request_id="req-calc-99",
        session_id="session-calc-99",
        idempotency_key="idemp-calc-99",
    )

    assert contract.request_id == "req-calc-99"
    assert contract.session_id == "session-calc-99"
    assert contract.action_intent.intent_name == "open_application"
    assert contract.action_intent.target == "calc"
    assert contract.execution_gate.can_execute is True
    assert contract.pre_action_feedback.acknowledgement_speech == "Claro, voy a abrir la Calculadora."

    # M) ExecutionSpec se construye si se proveen skill_id e idempotency_key
    assert contract.execution_spec is not None
    assert contract.execution_spec.skill_id == "windows.apps@1.0.0"
    assert contract.execution_spec.tool_name == "windows.launch_app"
    assert contract.execution_spec.idempotency_key == "idemp-calc-99"


# ==============================================================================
# M) EXECUTION SPEC PERMANECE NONE SI NO HAY IDEMPOTENCY KEY
# ==============================================================================

def test_bridge_execution_spec_remains_none_without_idempotency_key() -> None:
    """M) Sin una idempotency_key legítima, execution_spec debe permanecer None."""
    plan = ActionPlan(
        intent="open_application",
        steps=[ActionPlanStep(intent="open_application", skill_id="windows.apps", tool_name="launch")],
    )

    contract = bridge_action_plan_to_contract(
        plan=plan,
        user_input="Abre bloc",
        params={"app_name": "notepad"},
        idempotency_key=None,
    )

    assert contract.execution_spec is None, "ExecutionSpec no debe inventar una idempotency_key si no existe una fuente legítima."
