"""Post-Execution Verification para ActionIntentContract (Fase 64.2.4).

Capa encargada de determinar deterministamente si el efecto esperado de una acción
realmente ocurrió en el sistema operativo tras su ejecución por el Dispatcher/Skill.

PRINCIPIO FUNDAMENTAL:
    "Execution success" != "Real-world success"

    Dispatcher/Skill SUCCESS
              ↓
    Post-Execution Verification
              ↓
    Resultado real observable (VERIFIED_SUCCESS / VERIFIED_FAILURE / UNVERIFIED / ETC.)
              ↓
    Feedback al usuario

ANTI-FALSE SUCCESS:
Bajo ninguna circunstancia se declara éxito si el efecto real no ha sido observado
y verificado positivamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.action_intent_contract import (
    ActionExecutionReport,
    ActionIntent,
    ActionIntentContract,
    PostActionFeedback,
)
from core.execution.execution_dispatcher import (
    DispatchResult,
    DispatchStatus,
)
from core.execution.execution_verifier import (
    ExecutionEvidence,
    ExecutionVerifier,
    get_execution_verifier,
)
from core.logger import get_logger

logger = get_logger("jessyca.execution.post_verifier")


class VerificationReportStatus(StrEnum):
    """Estados canónicos e inequívocos de verificación post-ejecución."""

    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFIED_FAILURE = "VERIFIED_FAILURE"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    UNVERIFIED = "UNVERIFIED"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"


@dataclass(frozen=True)
class VerificationReport:
    """Informe formal e inmutable de la verificación real post-ejecución.

    Conserva la trazabilidad completa de la acción, su efecto esperado y el efecto
    efectivamente observado en el entorno físico o sistema operativo.
    """

    action_id: str
    skill: str
    operation: str
    expected_effect: str
    observed_effect: str
    verification_status: VerificationReportStatus
    verification_method: str
    is_verified: bool
    claims_success: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    feedback_suggestion: str | None = None

    def __post_init__(self) -> None:
        """Aplica la invariante absoluta de Anti-False Success."""
        if self.verification_status != VerificationReportStatus.VERIFIED_SUCCESS and self.claims_success:
            raise ValueError(
                f"Invariante violada (Anti-False Success): claims_success no puede ser True "
                f"cuando verification_status es '{self.verification_status}'."
            )
        if self.verification_status == VerificationReportStatus.VERIFIED_SUCCESS and not self.is_verified:
            raise ValueError(
                "Invariante violada: verification_status='VERIFIED_SUCCESS' exige is_verified=True."
            )

    @property
    def skill_id(self) -> str:
        """Alias para interoperabilidad con esquemas que usan skill_id."""
        return self.skill

    def to_dict(self) -> dict[str, Any]:
        """Serializa el reporte de verificación a diccionario seguro para auditoría."""
        return {
            "action_id": self.action_id,
            "skill": self.skill,
            "operation": self.operation,
            "expected_effect": self.expected_effect,
            "observed_effect": self.observed_effect,
            "verification_status": self.verification_status.value,
            "verification_method": self.verification_method,
            "is_verified": self.is_verified,
            "claims_success": self.claims_success,
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
            "details": self.details,
            "feedback_suggestion": self.feedback_suggestion,
        }

    def to_post_action_feedback(self) -> PostActionFeedback:
        """Genera el PostActionFeedback inmutable para el contrato basado en la verificación real."""
        speech = self.feedback_suggestion or "Operación procesada."
        return PostActionFeedback(
            spoken_response=speech,
            response_text=speech,
        )

    def attach_to_contract(self, contract: ActionIntentContract) -> ActionIntentContract:
        """Actualiza e incrusta el resultado de verificación en el ActionIntentContract de forma inmutable."""
        # Estado canónico alineado con ActionExecutionReport
        exec_status = "success" if self.claims_success else "failed"
        if self.verification_status == VerificationReportStatus.UNVERIFIED:
            exec_status = "unverified"
        elif self.verification_status == VerificationReportStatus.PARTIAL_SUCCESS:
            exec_status = "partial_success"
        elif self.verification_status == VerificationReportStatus.VERIFICATION_ERROR:
            exec_status = "verification_error"

        updated_report = ActionExecutionReport(
            skill_id=self.skill or (contract.execution_spec.skill_id if contract.execution_spec else None),
            tool_name=self.operation or (contract.execution_spec.tool_name if contract.execution_spec else None),
            execution_status=exec_status,
            is_verified=self.is_verified,
            claims_success=self.claims_success,
            evidence={
                "verification_status": self.verification_status.value,
                "verification_method": self.verification_method,
                "expected_effect": self.expected_effect,
                "observed_effect": self.observed_effect,
                "details": self.details,
            },
            error_code=self.error if not self.claims_success else None,
        )

        feedback = self.to_post_action_feedback()
        return contract.model_copy(
            update={
                "execution_report": updated_report,
                "post_action_feedback": feedback,
            }
        )


class PostExecutionVerifier:
    """Verificador central post-ejecución de acciones para JESSYCA.

    Comprueba si las acciones ejecutadas por el Dispatcher realmente produjeron
    el cambio de estado observable esperado en el sistema operativo.
    """

    def __init__(self, verifier: ExecutionVerifier | Any | None = None) -> None:
        self.verifier = verifier or get_execution_verifier()

    def verify(
        self,
        intent: ActionIntent | ActionIntentContract,
        execution: ActionExecutionReport | DispatchResult | dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
        custom_verifier: Any | None = None,
        timeout_seconds: float = 2.5,
    ) -> VerificationReport:
        """Evalúa el efecto esperado frente al efecto real observado.

        Parámetros:
        - intent: ActionIntent o el contrato raíz ActionIntentContract.
        - execution: ActionExecutionReport, DispatchResult o dict de resultado.
        - parameters: Parámetros opcionales explícitos de la operación.
        - custom_verifier: Estrategia o función de verificación personalizada para tests/inyección.
        - timeout_seconds: Tiempo límite para la comprobación determinista.

        Retorna:
        - VerificationReport inmutable con uno de los 5 estados canónicos.
        """
        now = datetime.now(UTC)

        # ── 1. EXTRACCIÓN Y NORMALIZACIÓN DE METADATOS ──
        if isinstance(intent, ActionIntentContract):
            contract = intent
            act_intent = contract.action_intent
            action_id = contract.request_id
            gate_can_execute = contract.execution_gate.can_execute
        else:
            contract = None
            act_intent = intent
            action_id = getattr(act_intent, "request_id", None) or "action_unspecified"
            gate_can_execute = True

        # Extraer skill y operation
        skill_name = ""
        op_name = ""
        dispatch_is_success = False
        dispatch_status: str | None = None
        evidence_dict: dict[str, Any] = {}
        error_msg: str | None = None
        output_dict: dict[str, Any] = {}

        if isinstance(execution, DispatchResult):
            action_id = execution.action_id or action_id
            skill_name = execution.skill_id
            op_name = execution.operation
            dispatch_is_success = execution.is_success
            dispatch_status = execution.status.value
            output_dict = execution.output or {}
            error_msg = execution.error
            if execution.execution_report and execution.execution_report.evidence:
                evidence_dict = dict(execution.execution_report.evidence)
        elif isinstance(execution, ActionExecutionReport):
            skill_name = execution.skill_id or ""
            op_name = execution.tool_name or ""
            dispatch_is_success = execution.claims_success
            dispatch_status = execution.execution_status
            evidence_dict = dict(execution.evidence or {})
            error_msg = execution.error_code
        elif isinstance(execution, dict):
            action_id = str(execution.get("action_id") or action_id)
            skill_name = str(execution.get("skill") or execution.get("skill_id") or "")
            op_name = str(execution.get("operation") or execution.get("tool_name") or "")
            dispatch_is_success = bool(execution.get("is_success", execution.get("exito", False)))
            dispatch_status = str(execution.get("status", "SUCCESS" if dispatch_is_success else "FAILED"))
            output_dict = execution.get("output", execution)
            error_msg = execution.get("error") or execution.get("mensaje")
            if "evidence" in execution and isinstance(execution["evidence"], dict):
                evidence_dict = dict(execution["evidence"])

        # Fallbacks de nombres desde ActionIntent si no vinieron en execution
        if not skill_name and contract and contract.execution_spec:
            skill_name = contract.execution_spec.skill_id
        if not skill_name and hasattr(act_intent, "skill"):
            skill_name = act_intent.skill or ""
        if not op_name and contract and contract.execution_spec and contract.execution_spec.tool_name:
            op_name = contract.execution_spec.tool_name
        if not op_name and hasattr(act_intent, "intent_name"):
            op_name = act_intent.intent_name or ""

        # Parámetros combinados
        combined_params: dict[str, Any] = {}
        if hasattr(act_intent, "parameters") and isinstance(act_intent.parameters, dict):
            combined_params.update(act_intent.parameters)
        if output_dict and isinstance(output_dict, dict):
            combined_params.update(output_dict)
        if parameters:
            combined_params.update(parameters)

        target_name = (
            combined_params.get("nombre_app")
            or combined_params.get("app_name")
            or combined_params.get("app")
            or combined_params.get("target")
            or getattr(act_intent, "target", None)
            or ""
        )

        # ── 2. CASO L: ACCIÓN RECHAZADA POR EXECUTION GATE ──
        if not gate_can_execute or dispatch_status in (DispatchStatus.REJECTED.value, "denied", "blocked"):
            logger.warning(
                f"[VERIFIER REJECTED] Acción [{action_id}] rechazada antes de ejecución. "
                "No llega al verifier como ejecutada."
            )
            return VerificationReport(
                action_id=action_id,
                skill=skill_name,
                operation=op_name,
                expected_effect="No ejecutar la acción por bloqueo de compuerta de seguridad.",
                observed_effect="Acción no ejecutada: rechazada o bloqueada por ExecutionGate.",
                verification_status=VerificationReportStatus.UNVERIFIED,
                verification_method="gate_barrier",
                is_verified=False,
                claims_success=False,
                timestamp=now,
                error="Acción rechazada por ExecutionGate",
                details={"gate_can_execute": gate_can_execute, "dispatch_status": dispatch_status},
                feedback_suggestion="La acción fue bloqueada por razones de seguridad.",
            )

        # ── 3. ANÁLISIS DE EFECTO ESPERADO Y VERIFICABILIDAD ──
        expected_effect, verif_method, is_verifiable = self._determine_expected_effect(
            skill=skill_name,
            operation=op_name,
            target=str(target_name),
            parameters=combined_params,
        )

        # ── 4. CASO C: DISPATCHER / SKILL REPORTÓ FALLO ──
        # Si la skill o el dispatcher ya reportaron fallo o excepción, NUNCA puede ser VERIFIED_SUCCESS.
        if not dispatch_is_success or dispatch_status in (
            DispatchStatus.FAILED.value,
            DispatchStatus.EXCEPTION.value,
            DispatchStatus.TIMEOUT.value,
            DispatchStatus.INVALID_ARGUMENTS.value,
            DispatchStatus.NOT_FOUND.value,
        ):
            logger.info(
                f"[VERIFIER EXECUTION FAILED] Acción [{action_id}] reportó fallo en ejecución "
                f"(status={dispatch_status}, error={error_msg})."
            )
            obs = f"Ejecución fallida reportada por la skill: {error_msg or 'Fallo general'}"
            feedback = self._build_feedback(
                status=VerificationReportStatus.VERIFIED_FAILURE,
                target=str(target_name),
                operation=op_name,
                custom_msg=error_msg,
            )
            return VerificationReport(
                action_id=action_id,
                skill=skill_name,
                operation=op_name,
                expected_effect=expected_effect,
                observed_effect=obs,
                verification_status=VerificationReportStatus.VERIFIED_FAILURE,
                verification_method=verif_method,
                is_verified=True,
                claims_success=False,
                timestamp=now,
                error=error_msg or "La ejecución reportó fallo.",
                details={"dispatch_status": dispatch_status, "evidence": evidence_dict},
                feedback_suggestion=feedback,
            )

        # ── 5. CASO D: ACCIÓN NO VERIFICABLE (UNVERIFIED) ──
        if not is_verifiable:
            logger.info(f"[VERIFIER UNVERIFIED] Operación '{op_name}' no es verificable de forma determinista.")
            feedback = self._build_feedback(
                status=VerificationReportStatus.UNVERIFIED,
                target=str(target_name),
                operation=op_name,
            )
            return VerificationReport(
                action_id=action_id,
                skill=skill_name,
                operation=op_name,
                expected_effect=expected_effect,
                observed_effect="No existe un sensor o mecanismo determinista para observar el efecto real en el sistema.",
                verification_status=VerificationReportStatus.UNVERIFIED,
                verification_method="none",
                is_verified=False,
                claims_success=False,
                timestamp=now,
                error=None,
                details={"reason": "Operation is non-verifiable"},
                feedback_suggestion=feedback,
            )

        # ── 6. COMPROBACIÓN DEL EFECTO REAL OBSERVABLE ──
        # Aquí verificamos activamente si el efecto esperado realmente ocurrió.
        # Soporta custom_verifier inyectado para pruebas o verifier central.
        active_verifier = custom_verifier or self.verifier

        try:
            obs_effect, is_verified_real, is_partial, details_verif = self._inspect_real_effect(
                skill=skill_name,
                operation=op_name,
                target=str(target_name),
                parameters=combined_params,
                evidence=evidence_dict,
                verifier=active_verifier,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            # ── CASO E: ERROR DURANTE LA VERIFICACIÓN (VERIFICATION_ERROR) ──
            logger.error(f"[VERIFIER ERROR] Excepción al verificar [{action_id}]: {exc}", exc_info=True)
            err_str = f"Error durante el proceso de verificación: {exc}"
            feedback = self._build_feedback(
                status=VerificationReportStatus.VERIFICATION_ERROR,
                target=str(target_name),
                operation=op_name,
                custom_msg=err_str,
            )
            return VerificationReport(
                action_id=action_id,
                skill=skill_name,
                operation=op_name,
                expected_effect=expected_effect,
                observed_effect=f"Excepción en el mecanismo de verificación: {exc}",
                verification_status=VerificationReportStatus.VERIFICATION_ERROR,
                verification_method=verif_method,
                is_verified=False,
                claims_success=False,
                timestamp=now,
                error=str(exc),
                details={"exception_type": type(exc).__name__},
                feedback_suggestion=feedback,
            )

        # ── 7. CASO F: RESULTADO PARCIAL (PARTIAL_SUCCESS) ──
        if is_partial:
            logger.info(f"[VERIFIER PARTIAL] Acción [{action_id}] produjo resultado parcial.")
            feedback = self._build_feedback(
                status=VerificationReportStatus.PARTIAL_SUCCESS,
                target=str(target_name),
                operation=op_name,
            )
            return VerificationReport(
                action_id=action_id,
                skill=skill_name,
                operation=op_name,
                expected_effect=expected_effect,
                observed_effect=obs_effect,
                verification_status=VerificationReportStatus.PARTIAL_SUCCESS,
                verification_method=verif_method,
                is_verified=True,
                claims_success=False,  # NO declarar éxito completo
                timestamp=now,
                error="Efecto observado sólo parcialmente.",
                details=details_verif,
                feedback_suggestion=feedback,
            )

        # ── 8. CASOS A Y B: ÉXITO CONFIRMADO VS FALLO CONFIRMADO ──
        if is_verified_real:
            # CASO A: VERIFIED_SUCCESS
            logger.info(f"[VERIFIER SUCCESS] Acción [{action_id}] efecto verificado: {obs_effect}")
            feedback = self._build_feedback(
                status=VerificationReportStatus.VERIFIED_SUCCESS,
                target=str(target_name),
                operation=op_name,
            )
            return VerificationReport(
                action_id=action_id,
                skill=skill_name,
                operation=op_name,
                expected_effect=expected_effect,
                observed_effect=obs_effect,
                verification_status=VerificationReportStatus.VERIFIED_SUCCESS,
                verification_method=verif_method,
                is_verified=True,
                claims_success=True,
                timestamp=now,
                error=None,
                details=details_verif,
                feedback_suggestion=feedback,
            )
        else:
            # CASO B: VERIFIED_FAILURE (ANTI-FALSE SUCCESS)
            # La skill dijo SUCCESS, pero el efecto físico no ocurrió
            logger.warning(
                f"[VERIFIER FAILURE] FALSO ÉXITO EVITADO: Skill reportó éxito pero [{target_name}] no ocurrió."
            )
            fail_reason = f"No se pudo confirmar que el efecto esperado ocurriera: {obs_effect}"
            feedback = self._build_feedback(
                status=VerificationReportStatus.VERIFIED_FAILURE,
                target=str(target_name),
                operation=op_name,
                custom_msg=fail_reason,
            )
            return VerificationReport(
                action_id=action_id,
                skill=skill_name,
                operation=op_name,
                expected_effect=expected_effect,
                observed_effect=obs_effect,
                verification_status=VerificationReportStatus.VERIFIED_FAILURE,
                verification_method=verif_method,
                is_verified=True,
                claims_success=False,
                timestamp=now,
                error=fail_reason,
                details=details_verif,
                feedback_suggestion=feedback,
            )

    def _determine_expected_effect(
        self,
        skill: str,
        operation: str,
        target: str,
        parameters: dict[str, Any],
    ) -> tuple[str, str, bool]:
        """Determina la descripción del efecto esperado, el método y si es verificable."""
        op_norm = operation.lower().replace("_", ".")
        skill_norm = skill.lower()

        # 1. Apertura de aplicación (windows.apps / apps.open / launch)
        if (
            "open" in op_norm
            or "abrir" in op_norm
            or "launch" in op_norm
            or (skill_norm == "windows.apps" and "close" not in op_norm and "inspect" not in op_norm)
        ):
            app_label = target or "la aplicación"
            return (
                f"Proceso de '{app_label}' activo en ejecución en el sistema operativo.",
                "process_inspection",
                True,
            )

        # 2. Cierre de aplicación (windows.apps / apps.close / kill / terminate)
        if "close" in op_norm or "cerrar" in op_norm or "kill" in op_norm or "terminate" in op_norm:
            app_label = target or "la aplicación"
            return (
                f"Proceso de '{app_label}' terminado e inexistente en el sistema operativo.",
                "process_inspection",
                True,
            )

        # 3. Inspección de proceso / aplicación
        if "inspect" in op_norm or "comprobar" in op_norm or "estado" in op_norm:
            app_label = target or "el proceso"
            return (
                f"Estado del proceso '{app_label}' inspeccionado y reportado.",
                "process_inspection",
                True,
            )

        # 4. Operaciones de archivos (create / write / save / delete)
        if any(k in op_norm for k in ("file", "archivo", "create", "write", "crear", "guardar")):
            path_val = target or parameters.get("path") or parameters.get("filename") or "archivo"
            return (
                f"Archivo '{path_val}' confirmado en el sistema de archivos.",
                "filesystem_inspection",
                True,
            )

        # 5. Captura de pantalla (windows.screenshot)
        if "screenshot" in op_norm or "pantalla" in op_norm or skill_norm == "windows.screenshot":
            return (
                "Archivo de captura de pantalla generado y válido en disco.",
                "filesystem_inspection",
                True,
            )

        # 5.1 YouTube / Multimedia Browser (browser.youtube)
        if "youtube" in skill_norm or "youtube" in op_norm:
            q_val = target or parameters.get("query") or "contenido"
            if "play" in op_norm:
                return (
                    f"Reproducción multimedia de '{q_val}' iniciada y verificada en YouTube.",
                    "youtube_inspection",
                    True,
                )
            elif "search" in op_norm:
                return (
                    f"Búsqueda de '{q_val}' realizada y verificada en YouTube.",
                    "browser_inspection",
                    True,
                )
            return (
                "Página de YouTube abierta y verificada en el navegador.",
                "browser_inspection",
                True,
            )

        # 6. Operaciones no verificables de forma determinista
        # (ej: chat conversacional, síntesis de voz, notificaciones sin sensor de retorno)
        return (
            f"Efecto de '{operation}' ejecutado sin sensor de estado observable.",
            "unsupported",
            False,
        )

    def _inspect_real_effect(
        self,
        skill: str,
        operation: str,
        target: str,
        parameters: dict[str, Any],
        evidence: dict[str, Any],
        verifier: Any,
        timeout_seconds: float,
    ) -> tuple[str, bool, bool, dict[str, Any]]:
        """Comprueba el efecto real en el sistema utilizando la estrategia correspondiente.

        Retorna:
        - observed_effect: str
        - is_verified: bool (True si el efecto esperado ocurrió)
        - is_partial: bool (True si sólo se cumplió parcialmente)
        - details: dict[str, Any]
        """
        op_norm = operation.lower().replace("_", ".")

        # Detección explícita de éxito parcial en los parámetros o evidencia previa
        if parameters.get("is_partial") is True or evidence.get("is_partial") is True or parameters.get("partial_success") is True:
            obs = str(parameters.get("partial_details") or evidence.get("details", {}).get("partial_reason") or "Algunos efectos ocurrieron y otros no.")
            return obs, False, True, {"partial": True, "evidence": evidence}

        # ── CASO A: CUSTOM VERIFIER ESPECÍFICO (MOCK / FUNCIÓN / OBJETO) ──
        if hasattr(verifier, "verify_action"):
            res = verifier.verify_action(operation, target, parameters)
            if isinstance(res, tuple):
                obs, ok = res[0], res[1]
                return obs, ok, False, {"custom_verifier": True}
            elif hasattr(res, "is_verified"):
                return f"Verificación personalizada: is_verified={res.is_verified}", res.is_verified, False, getattr(res, "details", {})
            return str(res), bool(res), False, {}

        if hasattr(verifier, "process_exists"):
            # Mock verifier que expone bandera booleana directa process_exists
            exists = bool(verifier.process_exists)
            if "close" in op_norm or "cerrar" in op_norm:
                # Para cerrar, el éxito real es que NO exista
                ok = not exists
                obs = f"Proceso '{target}' no existe (terminado)." if ok else f"Proceso '{target}' sigue existiendo."
            else:
                ok = exists
                obs = f"Proceso '{target}' existe en el sistema." if ok else f"Proceso '{target}' no existe en el sistema."
            return obs, ok, False, {"process_exists": exists}

        # ── CASO B: OPERACIONES DE APERTURA DE APLICACIONES ──
        if "open" in op_norm or "abrir" in op_norm or "launch" in op_norm or skill.lower() == "windows.apps":
            if "close" not in op_norm and "inspect" not in op_norm:
                # Si el verifier provisto es el ExecutionVerifier estándar
                if hasattr(verifier, "verify_execution"):
                    ev = verifier.verify_execution(
                        action="open_application",
                        target=target,
                        parameters=parameters,
                        timeout_seconds=timeout_seconds,
                    )
                    if isinstance(ev, ExecutionEvidence):
                        ok = ev.is_verified
                        pids = ev.details.get("pids", [])
                        obs = f"Proceso '{target}' verificado en ejecución (PIDs: {pids})." if ok else f"Proceso '{target}' no se encontró en ejecución."
                        return obs, ok, False, ev.to_dict()

                # O si la evidencia ya trae verificación positiva previa y no hay verifier alternativo
                if evidence and "is_verified" in evidence:
                    ok = bool(evidence.get("is_verified"))
                    pids = evidence.get("details", {}).get("pids", [])
                    obs = f"Proceso '{target}' verificado en ejecución (PIDs: {pids})." if ok else f"Proceso '{target}' no verificado."
                    return obs, ok, False, evidence

                return f"No se pudo confirmar proceso para '{target}'.", False, False, {}

        # ── CASO C: OPERACIONES DE CIERRE DE APLICACIONES ──
        if "close" in op_norm or "cerrar" in op_norm or "kill" in op_norm:
            if hasattr(verifier, "verify_execution"):
                ev = verifier.verify_execution(
                    action="close_application",
                    target=target,
                    parameters=parameters,
                    timeout_seconds=timeout_seconds,
                )
                if isinstance(ev, ExecutionEvidence):
                    ok = ev.is_verified
                    obs = f"Proceso '{target}' terminado y verificado ausente." if ok else f"Proceso '{target}' sigue activo en el sistema."
                    return obs, ok, False, ev.to_dict()

            if evidence and "is_verified" in evidence:
                ok = bool(evidence.get("is_verified"))
                obs = f"Proceso '{target}' terminado." if ok else f"Proceso '{target}' no se pudo terminar."
                return obs, ok, False, evidence

            return f"No se pudo confirmar terminación de '{target}'.", False, False, {}

        # ── CASO D: ARCHIVOS O CAPTURA DE PANTALLA ──
        if any(k in op_norm for k in ("file", "screenshot", "pantalla", "archivo")):
            if hasattr(verifier, "verify_execution"):
                path_val = target or parameters.get("path") or parameters.get("filename") or parameters.get("ruta") or ""
                ev = verifier.verify_execution(
                    action="file_exists",
                    target=str(path_val),
                    parameters=parameters,
                    timeout_seconds=timeout_seconds,
                )
                if isinstance(ev, ExecutionEvidence):
                    ok = ev.is_verified
                    obs = f"Archivo '{path_val}' verificado en disco." if ok else f"Archivo '{path_val}' no existe en disco."
                    return obs, ok, False, ev.to_dict()

        # ── CASO E: REPRODUCCIÓN / BÚSQUEDA YOUTUBE (FASE 75.1) ──
        if "youtube" in skill.lower() or "youtube" in op_norm:
            is_verif_ev = bool(parameters.get("verified", False) or evidence.get("verified", False) or parameters.get("verification_status") == "VERIFIED")
            status_ev = str(parameters.get("verification_status") or evidence.get("verification_status") or "")
            if status_ev == "NOT_VERIFIABLE":
                return "La página de YouTube se abrió pero la reproducción no es deterministamente verificable.", False, False, {"verification_status": "NOT_VERIFIABLE"}
            if is_verif_ev:
                obs = f"Reproducción de '{target or parameters.get('query')}' verificada en YouTube."
                return obs, True, False, {"verified": True, "media_state": "MEDIA_PLAYING"}
            else:
                obs = f"No se pudo confirmar la reproducción de '{target or parameters.get('query')}' en YouTube."
                return obs, False, False, {"verified": False}

        # Fallback para estrategias genéricas
        if hasattr(verifier, "verify_execution"):
            ev = verifier.verify_execution(action=operation, target=target, parameters=parameters, timeout_seconds=timeout_seconds)
            if isinstance(ev, ExecutionEvidence):
                return f"Verificación genérica: is_verified={ev.is_verified}", ev.is_verified, False, ev.to_dict()

        return f"No se pudo verificar el efecto de '{operation}'.", False, False, {}

    def _build_feedback(
        self,
        status: VerificationReportStatus,
        target: str,
        operation: str,
        custom_msg: str | None = None,
    ) -> str:
        """Construye una sugerencia de retroalimentación natural según el estado de verificación."""
        target_display = target.title() if target else "la aplicación"
        op_lower = operation.lower()

        is_close = any(k in op_lower for k in ("close", "cerrar", "kill"))

        if status == VerificationReportStatus.VERIFIED_SUCCESS:
            if is_close:
                return f"Listo, {target_display} ha sido cerrado correctamente."
            return f"Listo, {target_display} está abierto y disponible."

        elif status == VerificationReportStatus.VERIFIED_FAILURE:
            if is_close:
                return f"No pude confirmar que {target_display} se haya cerrado."
            return f"No pude confirmar que {target_display} esté abierto."

        elif status == VerificationReportStatus.PARTIAL_SUCCESS:
            return f"La acción sobre {target_display} se completó parcialmente; algunos efectos no pudieron confirmarse."

        elif status == VerificationReportStatus.UNVERIFIED:
            return "La acción fue ejecutada, pero no pude verificar el resultado."

        elif status == VerificationReportStatus.VERIFICATION_ERROR:
            return "La acción se ejecutó, pero tuve un problema al comprobar el resultado."

        return custom_msg or "Resultado de la acción procesado."
