"""Bridge de Verificación y Telemetría para ActionIntentContract (Fase 64.1.5).

Transforma los resultados reales de ejecución y evidencias generadas por
ExecutionVerifier / ExecutionResult en componentes inmutables del contrato:
- ActionExecutionReport
- PostActionFeedback

Aplica estrictamente el principio:
NO EXECUTION EVIDENCE / NO VERIFICATION = NO SUCCESS CLAIM (Anti-False Success).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from core.action_intent_contract import (
    ActionExecutionReport,
    ActionIntentContract,
    PostActionFeedback,
)
from core.execution.execution_verifier import (
    ExecutionEvidence,
    ExecutionResult,
    ExecutionStatus,
    ExecutionVerifier,
    get_execution_verifier,
)

if TYPE_CHECKING:
    from core.system.system_coordinator import SystemResponse


def _evidence_to_dict(evidence: ExecutionEvidence | None) -> dict[str, Any]:
    if evidence is None:
        return {}
    res = evidence.to_dict()
    if isinstance(evidence.details, dict):
        for k, v in evidence.details.items():
            if k not in res:
                res[k] = v
    return res


def build_execution_report(
    execution_result: ExecutionResult | None = None,
    sys_resp: SystemResponse | None = None,
    skill_id: str | None = None,
    tool_name: str | None = None,
    error_code: str | None = None,
) -> ActionExecutionReport | None:
    """Convierte un ExecutionResult o SystemResponse en un ActionExecutionReport.

    Aplica Anti-False Success: claims_success sólo puede ser True si is_verified es True
    y el estado de ejecución fue formalmente exitoso.
    """
    if execution_result is None and sys_resp is None:
        return None

    skill = skill_id
    tool = tool_name
    err = error_code

    if execution_result is not None:
        tool = tool or execution_result.action
        evidence_dict = _evidence_to_dict(execution_result.evidence)
        is_verif = bool(execution_result.evidence and execution_result.evidence.is_verified)
        err = err or execution_result.error_code

        if execution_result.status == ExecutionStatus.SUCCEEDED:
            if is_verif:
                status_str = "success"
                claims_succ = True
            else:
                # Ejecutada pero no verificada (Anti-False Success)
                status_str = "unknown"
                is_verif = False
                claims_succ = False
        elif execution_result.status == ExecutionStatus.VERIFICATION_FAILED:
            status_str = "failed"
            is_verif = bool(execution_result.evidence and execution_result.evidence.is_verified)
            claims_succ = False
            err = err or "VERIFICATION_FAILED"
        elif execution_result.status in (
            ExecutionStatus.FAILED,
            ExecutionStatus.DENIED,
            ExecutionStatus.CANCELLED,
        ):
            status_str = "failed" if execution_result.status == ExecutionStatus.FAILED else execution_result.status.value
            is_verif = bool(execution_result.evidence and execution_result.evidence.is_verified)
            claims_succ = False
        else:
            status_str = execution_result.status.value
            is_verif = bool(execution_result.evidence and execution_result.evidence.is_verified)
            claims_succ = False

        # Invariante absoluta Anti-False Success
        if not is_verif:
            claims_succ = False

        return ActionExecutionReport(
            skill_id=skill,
            tool_name=tool,
            execution_status=status_str,
            is_verified=is_verif,
            claims_success=claims_succ,
            evidence=evidence_dict,
            error_code=err,
        )

    if sys_resp is not None:
        err = err or sys_resp.error
        out = sys_resp.output if isinstance(sys_resp.output, dict) else {}
        raw_evidence = out.get("evidence") if isinstance(out, dict) else None

        is_verif = False
        evidence_dict = {}
        if isinstance(raw_evidence, dict):
            evidence_dict = raw_evidence
            is_verif = bool(raw_evidence.get("is_verified", False))

        if sys_resp.success:
            if is_verif:
                status_str = "success"
                claims_succ = True
            else:
                status_str = "unknown"
                is_verif = False
                claims_succ = False
        else:
            status_str = "failed"
            claims_succ = False

        if not is_verif:
            claims_succ = False

        return ActionExecutionReport(
            skill_id=skill,
            tool_name=tool,
            execution_status=status_str,
            is_verified=is_verif,
            claims_success=claims_succ,
            evidence=evidence_dict,
            error_code=err,
        )

    return None


def verify_and_build_execution_report(
    action: str,
    target: str,
    execution_result: ExecutionResult | None = None,
    verifier: ExecutionVerifier | None = None,
    parameters: dict[str, Any] | None = None,
    skill_id: str | None = None,
    tool_name: str | None = None,
) -> ActionExecutionReport:
    """Ejecuta activamente la verificación sobre el sistema si no hay evidencia previa y genera el reporte."""
    evidence: ExecutionEvidence | None = None
    if execution_result and execution_result.evidence:
        evidence = execution_result.evidence
    else:
        active_verifier = verifier or get_execution_verifier()
        evidence = active_verifier.verify_execution(
            action=action,
            target=target,
            parameters=parameters,
        )

    is_verif = bool(evidence and evidence.is_verified)
    claims_succ = is_verif and (
        execution_result.status == ExecutionStatus.SUCCEEDED if execution_result else is_verif
    )
    status_str = "success" if claims_succ else ("unknown" if not is_verif else "failed")

    # Anti-false success
    if not is_verif:
        claims_succ = False

    return ActionExecutionReport(
        skill_id=skill_id,
        tool_name=tool_name or action,
        execution_status=status_str,
        is_verified=is_verif,
        claims_success=claims_succ,
        evidence=_evidence_to_dict(evidence),
        error_code=execution_result.error_code if execution_result else None,
    )


def build_post_action_feedback(
    execution_report: ActionExecutionReport | None,
    response_text: str | None = None,
    spoken_text: str | None = None,
) -> PostActionFeedback | None:
    """Construye PostActionFeedback tras conocer el resultado real de la ejecución.

    Distingue:
    - Éxito verificado: Locución de éxito.
    - Desconocido / No verificado: Evita declarar 'listo' falsamente.
    - Fallo: Locución de fallo o error descriptivo.
    """
    if execution_report is None:
        return None

    raw_spoken = spoken_text or response_text

    if execution_report.claims_success:
        spoken = raw_spoken or "Operación completada y verificada exitosamente."
        text = response_text or spoken
        return PostActionFeedback(spoken_response=spoken, response_text=text)

    if not execution_report.is_verified or execution_report.execution_status == "unknown":
        # Prevenir false success si el texto crudo afirmaba éxito prematuro
        is_premature_success = bool(
            raw_spoken and re.search(r"\b(listo|abrí|cerré|éxito|completad[oa])\b", raw_spoken, re.IGNORECASE)
        )
        if is_premature_success or not raw_spoken:
            spoken = "La acción se ejecutó, pero no se pudo confirmar su estado en el sistema."
        else:
            spoken = raw_spoken
        text = response_text or spoken
        return PostActionFeedback(spoken_response=spoken, response_text=text)

    # Estado de fallo formal
    spoken = raw_spoken or "La operación no pudo completarse."
    text = response_text or spoken
    return PostActionFeedback(spoken_response=spoken, response_text=text)


def attach_execution_to_contract(
    contract: ActionIntentContract | None,
    execution_result: ExecutionResult | None = None,
    sys_resp: SystemResponse | None = None,
    response_text: str | None = None,
    spoken_text: str | None = None,
    skill_id: str | None = None,
    tool_name: str | None = None,
) -> ActionIntentContract | None:
    """Enlaza el resultado real de ejecución y verificación al ActionIntentContract.

    Si el contrato es None (conversación normal) o la acción no fue ejecutada
    (clarificación o confirmación pendientes), mantiene execution_report y
    post_action_feedback como None.
    """
    if contract is None:
        return None

    # Si la acción está bloqueada por gate
    if contract.execution_gate.needs_clarification or contract.execution_gate.needs_confirmation:
        return contract

    report = build_execution_report(
        execution_result=execution_result,
        sys_resp=sys_resp,
        skill_id=skill_id,
        tool_name=tool_name,
    )
    if report is None:
        return contract

    feedback = build_post_action_feedback(
        execution_report=report,
        response_text=response_text,
        spoken_text=spoken_text,
    )

    return contract.model_copy(
        update={
            "execution_report": report,
            "post_action_feedback": feedback,
        }
    )


__all__ = [
    "attach_execution_to_contract",
    "build_execution_report",
    "build_post_action_feedback",
    "verify_and_build_execution_report",
]
