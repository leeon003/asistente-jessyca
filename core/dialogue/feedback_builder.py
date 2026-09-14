"""Feedback Builder y Generador de Respuestas Naturales (Fase 64.2.5).

Transforma los resultados estructurados del sistema (VerificationReport, ActionIntent,
ActionExecutionReport, ExecutionGate) en respuestas en lenguaje natural concisas,
claras y humanas para el usuario final (vocal y textual).

PRINCIPIO FUNDAMENTAL:
    La respuesta al usuario se basa en el RESULTADO REAL VERIFICADO,
    no únicamente en el resultado de ejecución técnica.

ANTI-FALSE SUCCESS:
    Bajo ninguna circunstancia se responde "Listo." ni se afirma éxito
    si la acción no fue efectivamente comprobada como VERIFIED_SUCCESS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from core.action_intent_contract import (
    ActionExecutionReport,
    ActionIntent,
    ActionIntentContract,
    PostActionFeedback,
)
from core.execution.post_execution_verifier import (
    VerificationReport,
    VerificationReportStatus,
)
from core.logger import get_logger

logger = get_logger("jessyca.dialogue.feedback_builder")


class FeedbackStatus(StrEnum):
    """Estados canónicos del generador de feedback para el usuario."""

    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFIED_FAILURE = "VERIFIED_FAILURE"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    UNVERIFIED = "UNVERIFIED"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"
    REJECTED = "REJECTED"
    CLARIFY = "CLARIFY"
    ASK_CONFIRMATION = "ASK_CONFIRMATION"


@dataclass(frozen=True)
class NaturalFeedbackResponse:
    """Respuesta formal en lenguaje natural lista para TTS y UI."""

    spoken_response: str
    response_text: str
    status: FeedbackStatus
    action_id: str | None = None
    target: str | None = None
    operation: str | None = None
    is_success: bool = False
    requires_user_action: bool = False

    def to_post_action_feedback(self) -> PostActionFeedback:
        """Convierte la respuesta a PostActionFeedback inmutable para el contrato."""
        return PostActionFeedback(
            spoken_response=self.spoken_response,
            response_text=self.response_text,
        )


class FeedbackBuilder:
    """Constructor determinista de respuestas naturales para el usuario.

    IMPORTANTE:
    - Es un componente puramente presentacional.
    - NO ejecuta ninguna acción ni invoca ninguna skill.
    - Filtra cualquier jerga interna o técnica (ActionIntent, ExecutionGate, etc.).
    - Aplica rigurosamente Anti-False Success.
    """

    # Términos técnicos internos que nunca deben exponerse al usuario
    FORBIDDEN_INTERNAL_TERMS: tuple[str, ...] = (
        "actionintent",
        "executiongate",
        "dispatcher",
        "executiondispatcher",
        "verificationreport",
        "postexecutionverifier",
        "skillregistry",
        "baseskill",
        "skill",
        "plugin",
        "confidence",
        "idempotency_key",
        "request_id",
        "session_id",
        "traceback",
        "exception",
    )

    # Mapeo de nombres comunes a formato display natural
    DISPLAY_NAMES: dict[str, str] = {
        "notepad": "Bloc de notas",
        "notepad.exe": "Bloc de notas",
        "bloc de notas": "Bloc de notas",
        "bloc de nota": "Bloc de notas",
        "calc": "la Calculadora",
        "calc.exe": "la Calculadora",
        "calculadora": "la Calculadora",
        "calculatorapp.exe": "la Calculadora",
        "paint": "Paint",
        "paint.exe": "Paint",
        "mspaint": "Paint",
        "mspaint.exe": "Paint",
        "explorer": "el Explorador de archivos",
        "explorer.exe": "el Explorador de archivos",
        "explorador": "el Explorador de archivos",
        "cmd": "la Terminal",
        "cmd.exe": "la Terminal",
        "terminal": "la Terminal",
        "powershell": "PowerShell",
        "edge": "Edge",
        "msedge": "Edge",
        "msedge.exe": "Edge",
        "chrome": "Chrome",
        "chrome.exe": "Chrome",
        "youtube": "YouTube",
    }

    def format_target_display(self, target: str | None) -> str:
        """Normaliza el nombre del objetivo a una representación natural para el habla."""
        if not target or not target.strip():
            return "la aplicación"

        clean = target.strip()
        low = clean.lower()

        if low in self.DISPLAY_NAMES:
            return self.DISPLAY_NAMES[low]

        if low.endswith(".exe"):
            clean = clean[:-4].strip()

        # Si ya tiene artículo o preposición, no duplicar
        if clean.lower().startswith(("el ", "la ", "los ", "las ", "un ", "una ")):
            return clean

        return clean.capitalize()

    def sanitize_text(self, text: str) -> str:
        """Elimina referencias a arquitectura interna y jerga técnica."""
        if not text:
            return ""

        cleaned = text
        for term in self.FORBIDDEN_INTERNAL_TERMS:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            cleaned = pattern.sub("", cleaned)

        # Limpiar espacios múltiples y puntuación rota tras la sustitución
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"\s+([.,;:?])", r"\1", cleaned)
        return cleaned

    def build_feedback(
        self,
        verification_report: VerificationReport | None = None,
        intent: ActionIntent | ActionIntentContract | None = None,
        execution_report: ActionExecutionReport | None = None,
        status: FeedbackStatus | None = None,
        target: str | None = None,
        operation: str | None = None,
        reason: str | None = None,
    ) -> NaturalFeedbackResponse:
        """Construye la respuesta natural para el usuario integrando verificación e intención.

        Garantía:
        - Si verification_report está presente, el resultado se deriva de él.
        - Si el contrato indica necesidad de confirmación o aclaración, formula la pregunta directa.
        - Anti-False Success garantizado.
        """
        action_id: str | None = None
        contract: ActionIntentContract | None = None

        # ── 1. EXTRACCIÓN DE CONTRATO O INTENCIÓN ──
        if isinstance(intent, ActionIntentContract):
            contract = intent
            action_id = contract.request_id
            act_intent = contract.action_intent
            if not target:
                target = getattr(act_intent, "target", None) or (
                    act_intent.parameters.get("nombre_app")
                    or act_intent.parameters.get("app_name")
                    or act_intent.parameters.get("target")
                    if isinstance(act_intent.parameters, dict)
                    else None
                )
            if not operation:
                operation = (
                    contract.execution_spec.tool_name
                    if contract.execution_spec and contract.execution_spec.tool_name
                    else act_intent.intent_name
                )
        elif isinstance(intent, ActionIntent):
            act_intent = intent
            if not target:
                target = getattr(act_intent, "target", None) or (
                    act_intent.parameters.get("nombre_app")
                    or act_intent.parameters.get("app_name")
                    or act_intent.parameters.get("target")
                    if isinstance(act_intent.parameters, dict)
                    else None
                )
            if not operation:
                operation = act_intent.intent_name

        # ── 2. EXTRACCIÓN DESDE VERIFICATION REPORT ──
        if verification_report is not None:
            action_id = verification_report.action_id or action_id
            if not operation:
                operation = verification_report.operation
            if not target:
                target = str(verification_report.details.get("target") or "")

        # ── 3. DETERMINACIÓN DEL ESTADO CANÓNICO ──
        resolved_status = status
        if resolved_status is None:
            if verification_report is not None:
                # Mapear estado desde VerificationReport
                v_stat = verification_report.verification_status
                if v_stat == VerificationReportStatus.VERIFIED_SUCCESS:
                    resolved_status = FeedbackStatus.VERIFIED_SUCCESS
                elif v_stat == VerificationReportStatus.VERIFIED_FAILURE:
                    resolved_status = FeedbackStatus.VERIFIED_FAILURE
                elif v_stat == VerificationReportStatus.PARTIAL_SUCCESS:
                    resolved_status = FeedbackStatus.PARTIAL_SUCCESS
                elif v_stat == VerificationReportStatus.UNVERIFIED:
                    resolved_status = FeedbackStatus.UNVERIFIED
                elif v_stat == VerificationReportStatus.VERIFICATION_ERROR:
                    resolved_status = FeedbackStatus.VERIFICATION_ERROR
            elif contract is not None:
                # Mapear desde ExecutionGate del contrato si no se ejecutó aún
                gate = contract.execution_gate
                if gate.needs_confirmation:
                    resolved_status = FeedbackStatus.ASK_CONFIRMATION
                elif gate.needs_clarification:
                    resolved_status = FeedbackStatus.CLARIFY
                elif not gate.can_execute:
                    resolved_status = FeedbackStatus.REJECTED
                elif contract.execution_report:
                    if contract.execution_report.claims_success:
                        resolved_status = FeedbackStatus.VERIFIED_SUCCESS
                    else:
                        resolved_status = FeedbackStatus.VERIFIED_FAILURE
            elif execution_report is not None:
                if execution_report.claims_success:
                    resolved_status = FeedbackStatus.VERIFIED_SUCCESS
                else:
                    resolved_status = FeedbackStatus.VERIFIED_FAILURE

        if resolved_status is None:
            resolved_status = FeedbackStatus.UNVERIFIED

        # ── 4. SÍNTESIS DE LA RESPUESTA EN LENGUAJE NATURAL ──
        target_display = self.format_target_display(target)
        op_clean = (operation or "").lower()

        is_open = any(k in op_clean for k in ("open", "abrir", "launch"))
        is_close = any(k in op_clean for k in ("close", "cerrar", "kill", "terminate"))

        response_speech = ""
        requires_user_action = False
        is_success = False

        if resolved_status == FeedbackStatus.VERIFIED_SUCCESS:
            is_success = True
            if is_close:
                response_speech = f"Listo, cerré {target_display}."
            elif is_open:
                response_speech = f"Listo, abrí {target_display}."
            elif "search" in op_clean or "buscar" in op_clean:
                response_speech = f"Listo, encontré los resultados para {target_display}."
            elif "screenshot" in op_clean or "pantalla" in op_clean:
                response_speech = "Listo, capturé la pantalla."
            else:
                response_speech = f"Listo, completé la acción sobre {target_display}."

        elif resolved_status == FeedbackStatus.VERIFIED_FAILURE:
            # ANTI-FALSE SUCCESS: Prohibido decir "Listo" o afirmar éxito
            if is_close:
                response_speech = f"No pude confirmar que {target_display} se haya cerrado."
            elif is_open:
                response_speech = f"No pude confirmar que {target_display} se haya abierto."
            else:
                response_speech = f"No pude completar la acción sobre {target_display}."

        elif resolved_status == FeedbackStatus.PARTIAL_SUCCESS:
            response_speech = "Parte de la acción se completó, pero no pude confirmar el resultado completo."

        elif resolved_status == FeedbackStatus.UNVERIFIED:
            response_speech = "La acción se ejecutó, pero no pude verificar el resultado."

        elif resolved_status == FeedbackStatus.VERIFICATION_ERROR:
            response_speech = "La acción se ejecutó, pero tuve un problema al comprobar el resultado."

        elif resolved_status == FeedbackStatus.REJECTED:
            sanitized_reason = self.sanitize_text(reason or "")
            if sanitized_reason and not any(t in sanitized_reason.lower() for t in self.FORBIDDEN_INTERNAL_TERMS):
                response_speech = f"No puedo realizar esa acción: {sanitized_reason}."
            else:
                response_speech = "No puedo ejecutar esa acción porque no está autorizada."

        elif resolved_status == FeedbackStatus.CLARIFY:
            requires_user_action = True
            if contract and contract.execution_gate.clarification_prompt:
                response_speech = self.sanitize_text(contract.execution_gate.clarification_prompt)
            elif is_close:
                response_speech = "¿Qué aplicación quieres que cierre?"
            elif is_open:
                response_speech = "¿Qué aplicación quieres que abra?"
            else:
                response_speech = "¿Podrías darme más detalles sobre lo que deseas hacer?"

        elif resolved_status == FeedbackStatus.ASK_CONFIRMATION:
            requires_user_action = True
            if contract and contract.execution_gate.confirmation_prompt:
                response_speech = self.sanitize_text(contract.execution_gate.confirmation_prompt)
            elif is_close:
                response_speech = f"Voy a cerrar {target_display}. ¿Quieres que lo haga?"
            elif is_open:
                response_speech = f"Voy a abrir {target_display}. ¿Quieres que lo haga?"
            else:
                response_speech = f"Voy a realizar una acción sobre {target_display}. ¿Deseas continuar?"

        # ── 5. HIGIENE Y SANITIZACIÓN FINAL DE SEGURIDAD ──
        final_speech = self.sanitize_text(response_speech)

        # Regla Anti-False Success estricta en el texto emitido
        if resolved_status != FeedbackStatus.VERIFIED_SUCCESS:
            low_final = final_speech.lower()
            if "listo," in low_final or low_final.startswith("listo") or "éxito" in low_final or "cerré correctamente" in low_final or "abrí correctamente" in low_final:
                logger.error(
                    f"[ANTI-FALSE-SUCCESS VIOLATION INTERCEPTED] Se intentó emitir éxito en estado {resolved_status}. "
                    "Reemplazando por respuesta honesta de no confirmación."
                )
                final_speech = "No pude confirmar el resultado de la acción."

        return NaturalFeedbackResponse(
            spoken_response=final_speech,
            response_text=final_speech,
            status=resolved_status,
            action_id=action_id,
            target=target,
            operation=operation,
            is_success=is_success,
            requires_user_action=requires_user_action,
        )

    def build_confirmation_prompt(self, operation: str, target: str) -> str:
        """Genera una pregunta directa y humana para solicitar confirmación."""
        resp = self.build_feedback(
            status=FeedbackStatus.ASK_CONFIRMATION,
            target=target,
            operation=operation,
        )
        return resp.spoken_response

    def build_clarification_prompt(self, operation: str, slot_name: str | None = None) -> str:
        """Genera una pregunta de aclaración cuando faltan datos obligatorios."""
        resp = self.build_feedback(
            status=FeedbackStatus.CLARIFY,
            operation=operation,
        )
        return resp.spoken_response

    def build_rejection_response(self, reason: str | None = None) -> str:
        """Genera una respuesta natural de rechazo sin exponer nombres de clases o módulos."""
        resp = self.build_feedback(
            status=FeedbackStatus.REJECTED,
            reason=reason,
        )
        return resp.spoken_response


# Instancia singleton predeterminada
_default_feedback_builder = FeedbackBuilder()


def get_feedback_builder() -> FeedbackBuilder:
    """Obtiene la instancia compartida de FeedbackBuilder."""
    return _default_feedback_builder
