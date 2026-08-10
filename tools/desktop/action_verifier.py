"""Verificador seguro de estado post-acción de la fase VERIFY (`windows.desktop` - Subetapa 08.4).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
No realiza re-intentos automáticos no guiados (NO AUTO-RETRY).
No utiliza sleeps fijos arbitrarios (sleep(5) PROHIBIDO). En su lugar utiliza polling controlado
con CancellationToken y comprobación continua de Parada de Emergencia (EmergencyStopManager).
AuditLogger y EventBus registran ÚNICAMENTE METADATOS de la verificación.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from core.action_verification_models import (
    ActionVerificationRequest,
    ExpectedState,
    ObservedState,
    VerificationResult,
    VerificationStatus,
)
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.emergency_stop import CancellationToken, EmergencyStopManager, get_emergency_stop_manager
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.ocr_sanitizer import OCRTextSanitizer
from core.ui_inspection_models import UIElementInfo, UIElementRequest, UIInspectionResult
from tools.desktop.ui_backend import FakeUIInspectionBackend, IUIInspectionBackend, WindowsUIAutomationBackend

logger = get_logger("jessyca.tools.desktop.action_verifier")


class ActionVerifier:
    """Motor de verificación post-acción para la fase VERIFY del pipeline de escritorio."""

    def __init__(
        self,
        ui_backend: IUIInspectionBackend | None = None,
        emergency_stop_manager: EmergencyStopManager | None = None,
        sanitizer: OCRTextSanitizer | None = None,
    ) -> None:
        self.ui_backend = ui_backend or WindowsUIAutomationBackend()
        self.emergency_stop = emergency_stop_manager or get_emergency_stop_manager()
        self.sanitizer = sanitizer or OCRTextSanitizer()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def verify_action_outcome(
        self,
        request: ActionVerificationRequest,
        cancellation_token: CancellationToken | None = None,
    ) -> VerificationResult:
        """Realiza el bucle de polling controlado de la fase VERIFY evaluando el estado observado contra el esperado.

        NUNCA realiza sleeps fijos no cancelables.
        Si la verificación falla o expira, retorna explícitamente VERIFICATION_FAILED o VERIFICATION_TIMEOUT
        permitiendo que la capa superior decida el curso de acción (NO AUTO-RETRY).
        """
        start_t = datetime.now(UTC)
        exp = request.expected_state
        deadline = time.time() + request.timeout_seconds
        last_observed: ObservedState | None = None

        logger.info(f"[ACTION VERIFIER] Iniciando fase VERIFY para acción [{request.action_id}] (timeout={request.timeout_seconds}s)")

        while time.time() < deadline:
            # 1. Comprobación inmediata de Parada de Emergencia
            if self.emergency_stop.is_stopped():
                proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
                res = VerificationResult(
                    status=VerificationStatus.ABORTED_BY_EMERGENCY_STOP,
                    success=False,
                    expected=exp,
                    observed=last_observed,
                    confidence=0.0,
                    processing_time_ms=proc_ms,
                    reason="Verificación abortada: Parada de Emergencia activa.",
                    timestamp=datetime.now(UTC),
                )
                self._log_audit(request.action_id, res)
                return res

            # 2. Comprobación del token de cancelación
            if cancellation_token and cancellation_token.is_cancellation_requested():
                proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
                res = VerificationResult(
                    status=VerificationStatus.CANCELLED,
                    success=False,
                    expected=exp,
                    observed=last_observed,
                    confidence=0.0,
                    processing_time_ms=proc_ms,
                    reason="Verificación cancelada por el usuario o token de cancelación.",
                    timestamp=datetime.now(UTC),
                )
                self._log_audit(request.action_id, res)
                return res

            # 3. Inspección UI de percepción no bloqueante
            try:
                inspect_req = UIElementRequest(
                    window_title=exp.expected_window_title,
                    control_type=exp.expected_control_type,
                    max_depth=10,
                    max_elements=100,
                )
                ui_res = self.ui_backend.inspect_ui(inspect_req)
                is_match, observed_state, match_reason = self._evaluate_state(ui_res, exp, request.min_confidence)
                last_observed = observed_state

                if is_match:
                    proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
                    res = VerificationResult(
                        status=VerificationStatus.VERIFIED_SUCCESS,
                        success=True,
                        expected=exp,
                        observed=observed_state,
                        confidence=observed_state.observed_confidence if observed_state else 1.0,
                        processing_time_ms=proc_ms,
                        reason=match_reason,
                        timestamp=datetime.now(UTC),
                    )
                    self._log_audit(request.action_id, res)
                    return res
            except Exception as e:
                logger.debug(f"[ACTION VERIFIER] Re-inspección intermedia fallida ({e})")

            # 4. Espera no bloqueante no mayor a poll_interval_seconds
            if cancellation_token:
                if cancellation_token.wait_or_cancelled(request.poll_interval_seconds):
                    proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
                    res = VerificationResult(
                        status=VerificationStatus.CANCELLED,
                        success=False,
                        expected=exp,
                        observed=last_observed,
                        confidence=0.0,
                        processing_time_ms=proc_ms,
                        reason="Verificación cancelada durante la espera del intervalo de polling.",
                        timestamp=datetime.now(UTC),
                    )
                    self._log_audit(request.action_id, res)
                    return res
            else:
                time.sleep(min(request.poll_interval_seconds, 0.05))

        # 5. Expiración del tiempo límite (TIMEOUT)
        proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
        fail_status = VerificationStatus.VERIFICATION_TIMEOUT
        fail_reason = f"Tiempo de verificación agotado ({request.timeout_seconds}s) sin observar el estado esperado."

        if last_observed and last_observed.observed_confidence < request.min_confidence:
            fail_status = VerificationStatus.CONFIDENCE_FAILED
            fail_reason = f"Confianza observada insuficiente ({last_observed.observed_confidence:.2f} < {request.min_confidence:.2f})."
        elif last_observed and exp.expected_text and last_observed.observed_text != exp.expected_text:
            fail_status = VerificationStatus.VERIFICATION_FAILED
            fail_reason = f"Discrepancia de estado: El texto observado no coincide con el esperado."

        res = VerificationResult(
            status=fail_status,
            success=False,
            expected=exp,
            observed=last_observed,
            confidence=last_observed.observed_confidence if last_observed else 0.0,
            processing_time_ms=proc_ms,
            reason=fail_reason,
            timestamp=datetime.now(UTC),
        )
        self._log_audit(request.action_id, res)
        return res

    def _evaluate_state(
        self,
        ui_res: UIInspectionResult,
        exp: ExpectedState,
        min_confidence: float,
    ) -> tuple[bool, ObservedState | None, str]:
        """Evalúa si el estado inspeccionado cumple los criterios del estado esperado."""
        elements = ui_res.elements_flat
        now = datetime.now(UTC)

        if exp.expect_disappearance:
            # Si se espera que el elemento/ventana desaparezca (ej. modal cerrado)
            matching = [
                e for e in elements
                if (not exp.expected_window_title or exp.expected_window_title.lower() in e.name.lower())
                and (not exp.expected_control_type or exp.expected_control_type.lower() in e.control_type.value.lower())
            ]
            if not matching:
                obs = ObservedState(
                    observed_window_title=None,
                    observed_control_type=None,
                    observed_text=None,
                    observed_state_hash=None,
                    observed_confidence=1.0,
                    timestamp=now,
                )
                return True, obs, "Verificación exitosa: El elemento ha desaparecido de la pantalla como se esperaba."
            else:
                top = matching[0]
                obs = ObservedState(
                    observed_window_title=top.name,
                    observed_control_type=top.control_type.value,
                    observed_text=top.name,
                    observed_state_hash=None,
                    observed_confidence=0.9,
                    timestamp=now,
                )
                return False, obs, "Verificación fallida: El elemento aún permanece visible en pantalla."

        # Búsqueda de elemento coincidente
        target_elem: UIElementInfo | None = None
        for elem in elements:
            win_match = not exp.expected_window_title or (exp.expected_window_title.lower() in elem.name.lower())
            ctrl_match = not exp.expected_control_type or (exp.expected_control_type.lower() in elem.control_type.value.lower())
            if win_match and ctrl_match:
                target_elem = elem
                break

        if not target_elem:
            return False, None, "Elemento o ventana esperada no encontrada en la inspección visual."

        clean_name, _ = self.sanitizer.sanitize_text(target_elem.name)
        obs_state = ObservedState(
            observed_window_title=clean_name,
            observed_control_type=target_elem.control_type.value,
            observed_text=clean_name,
            observed_state_hash=None,
            observed_confidence=0.95 if target_elem.is_enabled else 0.50,
            timestamp=now,
        )

        if obs_state.observed_confidence < min_confidence:
            return False, obs_state, f"Confianza del elemento observada insuficiente ({obs_state.observed_confidence:.2f})."

        if exp.expected_text and exp.expect_value_match:
            clean_expected, _ = self.sanitizer.sanitize_text(exp.expected_text)
            if clean_expected.lower() not in clean_name.lower():
                return False, obs_state, f"El texto observado no contiene el valor esperado."

        return True, obs_state, "Verificación exitosa: El estado UI observado coincide con el estado esperado."

    def _log_audit(self, action_id: str, res: VerificationResult) -> None:
        """Registra la auditoría y publica eventos en EventBus con privacidad absoluta (METADATOS EXCLUSIVOS)."""
        audit_meta = res.to_dict()
        event_type = AuditEventType.DESKTOP_ACTION_SUCCEEDED if res.success else AuditEventType.DESKTOP_ACTION_FAILED

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=event_type,
                request_id=action_id,
                tool_name="windows.desktop",
                operation="verify_action_outcome",
                duration_ms=res.processing_time_ms,
                reason=res.reason,
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("desktop:action_verification_completed", audit_meta)
