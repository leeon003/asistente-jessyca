"""Bridge de compatibilidad entre Diálogo/Planificación y Action Intent Contract (Fase 64.1.3).

Conecta de forma puramente observacional y desacoplada las decisiones dialógicas existentes
(DialogueDecision, ActionPlan) con el contrato fuertemente tipado ActionIntentContract.

INVARIANTES Y REGLAS DE DISEÑO:
1. NO EJECUCIÓN: No invoca Skills, Windows Apps, TTS ni subsistemas de audio.
2. NO EVALUACIÓN DE RIESGO ACTIVA: Solo transporta información de riesgo previamente calculada.
3. ANTI-FALSE SUCCESS: execution_report permanece estrictamente None (la acción aún no ocurre).
4. POST-ACTION FEEDBACK NULO: post_action_feedback permanece estrictamente None previo a ejecución.
5. EXECUTION SPEC ESTRICTO: Solo se construye si skill_id e idempotency_key existen legítimamente;
   de lo contrario permanece None.
6. PRESERVACIÓN DE IDENTIFICADORES: Reutiliza request_id y session_id del contexto si están presentes,
   con fallbacks seguros documentados ("req-unassigned", "session-default").
"""

from __future__ import annotations

from typing import Any

from core.action_intent_contract import (
    ActionIntent,
    ActionIntentContract,
    ExecutionGate,
    ExecutionSpec,
    PreActionFeedback,
)
from core.dialogue.dialogue_models import (
    ActionPlan,
    DialogueActionType,
    DialogueDecision,
)

# Claves candidatas comunes en el diccionario de parámetros para inferir el objetivo de la acción
TARGET_PARAM_KEYS: tuple[str, ...] = (
    "app_name",
    "target",
    "query",
    "topic",
    "path",
    "url",
    "filename",
    "site",
)


def _extract_target(params: dict[str, Any]) -> str | None:
    """Extrae el target semántico principal a partir de los parámetros conocidos."""
    for key in TARGET_PARAM_KEYS:
        val = params.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def bridge_dialogue_to_contract(
    decision: DialogueDecision,
    user_input: str,
    intent: str,
    params: dict[str, Any],
    context: dict[str, Any] | None = None,
    is_ambiguous: bool = False,
    confidence: float = 1.0,
    input_modality: str = "text",
    request_id: str | None = None,
    session_id: str | None = None,
    idempotency_key: str | None = None,
    risk_level: str | None = None,
) -> ActionIntentContract:
    """Convierte una decisión de diálogo y su contexto en un ActionIntentContract inmutable.

    No ejecuta ninguna acción, no evalúa riesgos y no modifica el flujo conversacional existente.
    """
    ctx = context or {}

    # ── 1. Resolución de Identificadores (request_id, session_id) ────────────
    resolved_req_id = (
        request_id
        or ctx.get("request_id")
        or ctx.get("task_id")
        or ctx.get("correlation_id")
        or "req-unassigned"
    )
    resolved_sess_id = (
        session_id
        or ctx.get("session_id")
        or "session-default"
    )

    # ── 2. Mapeo de ActionIntent ─────────────────────────────────────────────
    clean_intent = intent.strip() if intent and intent.strip() else "unknown"
    clamped_confidence = max(0.0, min(1.0, float(confidence)))
    resolved_target = _extract_target(params)
    missing_slots = [decision.expected_slot] if decision.expected_slot else []
    resolved_modality = ctx.get("modality") or input_modality or "text"

    ambiguity_flag = is_ambiguous or (decision.action_type == DialogueActionType.CLARIFICATION)

    action_intent = ActionIntent(
        intent_name=clean_intent,
        confidence=clamped_confidence,
        is_ambiguous=ambiguity_flag,
        input_modality=resolved_modality,
        target=resolved_target,
        parameters=dict(params),
        missing_slots=missing_slots,
    )

    # ── 3. Mapeo de ExecutionGate ────────────────────────────────────────────
    needs_clarif = (
        decision.action_type == DialogueActionType.CLARIFICATION
        or ambiguity_flag
        or bool(params.get("requires_clarification"))
    )
    clarif_prompt = None
    if needs_clarif:
        clarif_prompt = (
            ctx.get("clarification_prompt")
            or decision.clarification_question
            or decision.response_text
            or "¿Podrías aclararme qué deseas hacer?"
        )

    needs_confirm = (
        decision.action_type == DialogueActionType.REQUIRE_CONFIRMATION
        or bool(params.get("requires_confirmation"))
        or bool(ctx.get("requires_confirmation"))
    )
    confirm_prompt = None
    if needs_confirm:
        confirm_prompt = (
            ctx.get("confirmation_prompt")
            or decision.response_text
            or "¿Confirmas la ejecución de esta acción?"
        )

    resolved_risk = (
        risk_level
        or ctx.get("risk_level")
        or params.get("risk_level")
    )
    if resolved_risk is not None:
        resolved_risk = str(resolved_risk)

    can_execute = (
        decision.action_type == DialogueActionType.DIRECT_ACTION
        and not needs_clarif
        and not needs_confirm
        and not decision.is_terminal
    )

    execution_gate = ExecutionGate(
        can_execute=can_execute,
        needs_clarification=needs_clarif,
        clarification_prompt=clarif_prompt,
        needs_confirmation=needs_confirm,
        risk_level=resolved_risk,
        confirmation_prompt=confirm_prompt,
    )

    # ── 4. Mapeo de PreActionFeedback ────────────────────────────────────────
    ack_speech = decision.pre_action_speech
    if not ack_speech and decision.action_plan:
        ack_speech = decision.action_plan.summary_speech or None

    pre_action_feedback = PreActionFeedback(acknowledgement_speech=ack_speech)

    # ── 5. Mapeo de ExecutionSpec (Opcional y Estricto) ───────────────────────
    execution_spec: ExecutionSpec | None = None
    resolved_idemp_key = idempotency_key or ctx.get("idempotency_key")

    # Intentar obtener skill_id del plan de acción o del contexto
    inferred_skill_id: str | None = None
    inferred_tool_name: str | None = None
    if decision.action_plan and decision.action_plan.steps:
        first_step = decision.action_plan.steps[0]
        if first_step.skill_id and first_step.skill_id.strip():
            inferred_skill_id = first_step.skill_id.strip()
        if first_step.tool_name and first_step.tool_name.strip():
            inferred_tool_name = first_step.tool_name.strip()

    if not inferred_skill_id:
        inferred_skill_id = ctx.get("skill_id") or params.get("skill_id")
    if not inferred_tool_name:
        inferred_tool_name = ctx.get("tool_name") or params.get("tool_name")

    if inferred_skill_id and resolved_idemp_key:
        execution_spec = ExecutionSpec(
            skill_id=str(inferred_skill_id),
            tool_name=str(inferred_tool_name) if inferred_tool_name else None,
            idempotency_key=str(resolved_idemp_key),
        )

    # ── 6. Ensamble de ActionIntentContract (Report y PostFeedback = None) ───
    return ActionIntentContract(
        request_id=resolved_req_id,
        session_id=resolved_sess_id,
        action_intent=action_intent,
        execution_gate=execution_gate,
        pre_action_feedback=pre_action_feedback,
        execution_spec=execution_spec,
        execution_report=None,
        post_action_feedback=None,
    )


def bridge_action_plan_to_contract(
    plan: ActionPlan,
    user_input: str,
    params: dict[str, Any],
    context: dict[str, Any] | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    idempotency_key: str | None = None,
) -> ActionIntentContract:
    """Convierte un ActionPlan directo en un ActionIntentContract sin pasar por DialogueDecision."""
    pseudo_decision = DialogueDecision(
        action_type=DialogueActionType.DIRECT_ACTION,
        capability_level=pseudo_decision_cap_level(plan),
        response_text=plan.summary_speech,
        pre_action_speech=plan.summary_speech,
        action_plan=plan,
        is_terminal=False,
    )
    return bridge_dialogue_to_contract(
        decision=pseudo_decision,
        user_input=user_input,
        intent=plan.intent,
        params=params,
        context=context,
        request_id=request_id,
        session_id=session_id,
        idempotency_key=idempotency_key,
    )


def pseudo_decision_cap_level(plan: ActionPlan) -> Any:
    """Helper interno para compatibilidad de tipos con CapabilityLevel."""
    from core.dialogue.dialogue_models import CapabilityLevel
    return CapabilityLevel.FULL


__all__ = [
    "bridge_action_plan_to_contract",
    "bridge_dialogue_to_contract",
]
