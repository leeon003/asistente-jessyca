"""Pipeline Formal de Inteligencia Proactiva (proactive_pipeline.py - Fase 44).

Orquesta las 7 fases secuenciales del pipeline proactivo:
1. Event Ingestion (Detección y recepción de evento como UNTRUSTED DATA)
2. Context Enrichment (Enriquecimiento contextual con aplicación, archivo y estado)
3. Relevance Evaluation (Evaluación multi-criterio de relevancia, urgencia y confianza)
4. Anti-Spam & Deduplication (Gobernanza de cooldown, deduplicación y cuota)
5. Security & Autonomy Policy (Sanitización, anti-inyección de prompts, RiskEngine y permisos)
6. Suggestion / Action Proposal (Formulación de propuesta respetuosa al usuario)
7. User Interaction & Controlled Execution (Presentación interactiva o ejecución autorizada)
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from core.proactive.anti_spam_engine import AntiSpamEngine
from core.proactive.event_validator import ProactiveEventValidator
from core.proactive.proactive_models import (
    AntiSpamDecision,
    ProactiveActionType,
    ProactiveEvent,
    ProactiveExecutionResult,
    ProactivePolicyDecision,
    ProactiveSuggestion,
    RelevanceAssessment,
)
from core.proactive.proactive_policy import ProactivePolicyEngine
from core.proactive.proactive_security import ProactiveSecurityGuard
from core.proactive.relevance_engine import RelevanceEngine
from core.proactive.user_control import ProactiveUserControl

logger = get_logger("jessyca.proactive.pipeline")


class ProactivePipeline:
    """Motor orquestador del ciclo de vida completo de la inteligencia proactiva."""

    def __init__(
        self,
        relevance_engine: RelevanceEngine | None = None,
        anti_spam_engine: AntiSpamEngine | None = None,
        user_control: ProactiveUserControl | None = None,
        security_guard: ProactiveSecurityGuard | None = None,
        policy_engine: ProactivePolicyEngine | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.relevance_engine = relevance_engine or RelevanceEngine()
        self.anti_spam_engine = anti_spam_engine or AntiSpamEngine()
        self.user_control = user_control or ProactiveUserControl()
        self.security_guard = security_guard or ProactiveSecurityGuard()
        self.policy_engine = policy_engine or ProactivePolicyEngine()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.audit_logger = get_audit_logger()
        self._lock = threading.RLock()

    def execute_pipeline(
        self,
        event: ProactiveEvent,
        current_context: dict[str, Any] | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
        cancellation_token: CancellationToken | None = None,
        user_confirmation_callback: Callable[[ProactiveSuggestion], bool] | None = None,
    ) -> ProactiveExecutionResult:
        """Ejecuta de principio a fin el pipeline proactivo para un evento dado."""
        with self._lock:
            # ── 0. PARADA DE EMERGENCIA Y CANCELACIÓN ──
            if self.emergency_stop.is_stopped():
                logger.warning(f"[PIPELINE ABORTED] Parada de Emergencia activa. Evento '{event.event_id}' descartado.")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message="Parada de Emergencia activa. Acción proactiva descartada.",
                    execution_data={"emergency_stop": True},
                )

            if cancellation_token and cancellation_token.is_cancelled:
                logger.info(f"[PIPELINE CANCELLED] Evento '{event.event_id}' cancelado por token.")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message="Evento proactivo cancelado.",
                    execution_data={"cancelled": True},
                )

            # ── 1. VERIFICACIÓN DE CONTROL DE USUARIO ──
            settings = self.user_control.get_settings()
            if not self.user_control.is_active():
                reason = "deshabilitado" if not settings.enabled else ("silenciado" if self.user_control.is_muted() else "en horario silencioso")
                logger.info(f"[PIPELINE USER CONTROL] Evento '{event.event_id}' omitido porque el motor proactivo está {reason}.")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message=f"Inteligencia proactiva no activa ({reason}).",
                    execution_data={"user_control_active": False, "reason": reason},
                )

            # ── 2. VALIDACIÓN ESTRUCTURAL DE EVENTO ──
            is_valid, val_err = ProactiveEventValidator.validate(event)
            if not is_valid:
                logger.error(f"[PIPELINE EVENT INVALID] Evento '{event.event_id}' rechazado: {val_err}")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message=f"Evento inválido rechazado: {val_err}",
                    execution_data={"validation_error": val_err},
                )

            # ── 3. INSPECCIÓN DE SEGURIDAD Y ANTI-INYECCIÓN (UNTRUSTED DATA) ──
            is_safe, sec_err, sec_meta = self.security_guard.inspect_and_sanitize(event)
            if not is_safe:
                logger.warning(f"[PIPELINE SECURITY VIOLATION] Evento '{event.event_id}' bloqueado por seguridad: {sec_err}")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message=f"Evento bloqueado por seguridad: {sec_err}",
                    execution_data=sec_meta,
                )

            # ── 4. CONTEXT ENRICHMENT & RELEVANCE EVALUATION ──
            relevance_assessment: RelevanceAssessment = self.relevance_engine.evaluate(
                event=event,
                current_context=current_context,
                settings=settings,
            )

            if not relevance_assessment.is_relevant:
                logger.info(f"[PIPELINE IRRELEVANT] Evento '{event.event_id}' descartado por baja relevancia. ({relevance_assessment.reason})")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message=relevance_assessment.reason,
                    execution_data={"relevance": relevance_assessment.to_dict()},
                )

            # ── 5. ANTI-SPAM, COOLDOWN & DEDUPLICATION ──
            anti_spam_decision: AntiSpamDecision = self.anti_spam_engine.check_spam(
                event=event,
                relevance=relevance_assessment,
                settings=settings,
            )

            if not anti_spam_decision.allowed:
                logger.info(f"[PIPELINE SPAM SUPPRESSED] Evento '{event.event_id}' suprimido por anti-spam: {anti_spam_decision.reason}")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message=anti_spam_decision.reason,
                    execution_data={"anti_spam": anti_spam_decision.to_dict()},
                )

            # ── 6. POLICY & AUTONOMY EVALUATION ──
            policy_decision: ProactivePolicyDecision = self.policy_engine.evaluate_event(event)

            if not policy_decision.allowed:
                logger.warning(f"[PIPELINE POLICY DENIED] Evento '{event.event_id}' denegado por política: {policy_decision.reason}")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=False,
                    action_taken=ProactiveActionType.SUPPRESS,
                    user_message=policy_decision.user_message,
                    execution_data={"policy": policy_decision.to_dict()},
                )

            # ── 7. SUGGESTION FORMULATION & USER INTERACTION / EXECUTION ──
            # Registrar emisión para cooldown y deduplicación futura
            self.anti_spam_engine.record_emission(event, anti_spam_decision.fingerprint)

            # Si es notificación informativa
            if policy_decision.action_type == ProactiveActionType.NOTIFY_USER:
                self._audit_execution(event, policy_decision, "NOTIFY_USER", "SUCCESS")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=True,
                    action_taken=ProactiveActionType.NOTIFY_USER,
                    user_message=policy_decision.user_message,
                    execution_data={
                        "notified": True,
                        "relevance": relevance_assessment.to_dict(),
                        "event_type": str(event.event_type),
                    },
                )

            # Si requiere confirmación o es una propuesta de acción interactiva
            # Si requiere confirmación o es una propuesta de acción interactiva
            if policy_decision.action_type in (
                ProactiveActionType.REQUEST_CONFIRMATION,
                ProactiveActionType.SUGGEST_ACTION,
                ProactiveActionType.ASK_USER,
            ):
                # Generar objeto formal de sugerencia proactiva
                suggestion = ProactiveSuggestion(
                    event_id=event.event_id,
                    title=f"Sugerencia: {event.proposed_tool or event.summary}",
                    user_prompt=policy_decision.user_message,
                    proposed_tool=event.proposed_tool,
                    tool_parameters=dict(event.tool_parameters),
                    relevance=relevance_assessment.relevance,
                    urgency=relevance_assessment.urgency,
                    confidence=relevance_assessment.confidence,
                    requires_confirmation=True,
                    risk_level=policy_decision.risk_level,
                )

                # Si hay callback de confirmación interactiva directa provisto
                user_confirmed = False
                if user_confirmation_callback is not None:
                    try:
                        user_confirmed = user_confirmation_callback(suggestion)
                    except Exception as ex:
                        logger.error(f"Error en user_confirmation_callback: {ex}")
                        user_confirmed = False

                if user_confirmed and tool_executor and event.proposed_tool:
                    try:
                        out = tool_executor(event.proposed_tool, event.tool_parameters)
                        self._audit_execution(event, policy_decision, "CONFIRMED_EXECUTION", "SUCCESS")
                        return ProactiveExecutionResult(
                            event_id=event.event_id,
                            success=True,
                            action_taken=ProactiveActionType.SAFE_EXECUTE,
                            user_message=f"Acción confirmada y ejecutada: {event.proposed_tool}",
                            execution_data={"output": out, "confirmed_by_user": True},
                        )
                    except Exception as ex:
                        self._audit_execution(event, policy_decision, "CONFIRMED_EXECUTION", "FAILED")
                        return ProactiveExecutionResult(
                            event_id=event.event_id,
                            success=False,
                            action_taken=ProactiveActionType.SAFE_EXECUTE,
                            user_message=f"Error al ejecutar acción confirmada: {ex}",
                            execution_data={"execution_error": str(ex)},
                        )

                # Si no se ejecutó interactivamente en este paso, devolver la sugerencia/solicitud de confirmación
                self._audit_execution(event, policy_decision, "SUGGESTION_PRESENTED", "PENDING_CONFIRMATION")
                return ProactiveExecutionResult(
                    event_id=event.event_id,
                    success=True,
                    action_taken=ProactiveActionType.REQUEST_CONFIRMATION if policy_decision.action_type == ProactiveActionType.REQUEST_CONFIRMATION else ProactiveActionType.SUGGEST_ACTION,
                    user_message=policy_decision.user_message,
                    execution_data={
                        "confirmation_required": True,
                        "suggestion": suggestion.to_dict(),
                        "relevance": relevance_assessment.to_dict(),
                        "risk_level": str(policy_decision.risk_level),
                    },
                )

            # Si es SAFE_EXECUTE y la política de autonomía lo permite desatendidamente
            exec_data: dict[str, Any] = {"executed": True, "relevance": relevance_assessment.to_dict()}
            if tool_executor and event.proposed_tool:
                try:
                    out = tool_executor(event.proposed_tool, event.tool_parameters)
                    exec_data["output"] = out
                    self._audit_execution(event, policy_decision, "SAFE_EXECUTE", "SUCCESS")
                except Exception as ex:
                    logger.error(f"[PIPELINE TOOL EXECUTION ERROR] {ex}")
                    exec_data["execution_error"] = str(ex)
                    self._audit_execution(event, policy_decision, "SAFE_EXECUTE", "FAILED")

            return ProactiveExecutionResult(
                event_id=event.event_id,
                success=True,
                action_taken=ProactiveActionType.SAFE_EXECUTE,
                user_message=policy_decision.user_message,
                execution_data=exec_data,
            )

    def _audit_execution(
        self,
        event: ProactiveEvent,
        decision: ProactivePolicyDecision,
        action: str,
        status: str,
    ) -> None:
        """Registra el evento de ejecución en el AuditLogger."""
        try:
            event_type = AuditEventType.EXECUTION_SUCCEEDED if status == "SUCCESS" else (
                AuditEventType.EXECUTION_FAILED if status == "FAILED" else AuditEventType.POLICY_EVALUATED
            )
            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=event_type,
                    user=f"proactive_pipeline:{event.source}",
                    tool_name=event.proposed_tool or "",
                    operation=action,
                    security_level=decision.risk_level,
                    reason=decision.reason,
                    metadata={
                        "event_id": event.event_id,
                        "proposed_tool": event.proposed_tool,
                        "action_type": str(decision.action_type),
                        "status": status,
                    },
                )
            )
        except Exception as ex:
            logger.error(f"Error al registrar auditoría en pipeline proactivo: {ex}")
