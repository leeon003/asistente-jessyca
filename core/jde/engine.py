"""JESSYCA Decision Engine (JDE) - Motor Central de Decisión y Control (Fase 1).

Orquesta el ciclo determinista de toma de decisiones para JESSYCA:
USER REQUEST -> JDE -> POLICY GATE -> EXECUTOR -> VERIFIER -> EVIDENCE RECEIPT -> RESULT.

INVARIANTES ABSOLUTAS:
1. "tool execution succeeded" != "real-world action succeeded".
2. No evidence = No success claim (Anti-False Success).
3. Fallback y Reintento gobernados determinísticamente.
4. Si la verificación no puede comprobarse -> UNKNOWN (NUNCA SUCCESS).
5. Trazabilidad forense inmutable con fingerprint SHA-256.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from core.execution.idempotency_guard import (
    ExecutionFingerprint,
    ExecutionIdempotencyGuard,
    get_idempotency_guard,
)
from core.jde.audit import JDEAuditTrail
from core.jde.authority import (
    AuthorityDecision,
    AuthorityMode,
    JDEAuthorityGate,
    get_authority_gate,
)
from core.jde.models import DecisionRequest, DecisionResult
from core.jde.policy import JDEPolicyGate
from core.jde.receipts import ActionReceipt, JDEEvidence
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from core.jde.verification import (
    VerifierRegistry,
    get_verifier_registry,
)
from core.logger import get_logger

logger = get_logger("jessyca.jde.engine")


class DecisionEngine:
    """Motor central de decisión, autorización y verificación para JESSYCA."""

    def __init__(
        self,
        policy_gate: JDEPolicyGate | None = None,
        verifier_registry: VerifierRegistry | None = None,
        audit_trail: JDEAuditTrail | None = None,
        authority_gate: JDEAuthorityGate | None = None,
        idempotency_guard: ExecutionIdempotencyGuard | None = None,
        max_retries: int = 2,
    ) -> None:
        self.policy_gate = policy_gate or JDEPolicyGate()
        self.verifier_registry = verifier_registry or get_verifier_registry()
        self.audit_trail = audit_trail or JDEAuditTrail()
        self.authority_gate = authority_gate or get_authority_gate()
        self.idempotency_guard = idempotency_guard or get_idempotency_guard()
        self.max_retries = max_retries

    def decide_and_execute(
        self,
        request: DecisionRequest,
        executor: Callable[[str, dict[str, Any]], tuple[ExecutionStatusType, Any]],
        verifier_override: Callable[[dict[str, Any]], tuple[VerificationStatusType, bool, dict[str, Any]]] | None = None,
    ) -> DecisionResult:
        """Ejecuta el ciclo de vida completo de decisión para una solicitud."""
        t_start = time.perf_counter()
        started_at = datetime.now(UTC)
        logger.info(f"[JDE ENGINE] Recibida solicitud {request.request_id} ('{request.user_request}')")

        # ── 0. IDEMPOTENCIA Y PREVENCIÓN DE DUPLICADOS ──
        sess_id = getattr(request, "session_id", "default_session") or "default_session"
        target_str = str(request.parameters.get("path") or request.parameters.get("target") or "")
        fprint = ExecutionFingerprint(
            session_id=sess_id,
            request_id=request.request_id,
            intent=request.intent or request.proposed_action,
            skill=request.tool,
            action=request.proposed_action,
            target=target_str,
        )
        acquired, exec_record = self.idempotency_guard.acquire_execution(fprint)
        if not acquired:
            finished_at = datetime.now(UTC)
            duration_ms = (time.perf_counter() - t_start) * 1000
            receipt = ActionReceipt.create(
                request_id=request.request_id,
                correlation_id=request.correlation_id,
                user_request=request.user_request,
                action=request.proposed_action,
                tool=request.tool,
                parameters=request.parameters,
                executor="none",
                verifier="none",
                started_at=started_at,
                finished_at=finished_at,
                execution_status=ExecutionStatusType.SKIPPED,
                verification_status=VerificationStatusType.NOT_RUN,
                verified=False,
                final_status=DecisionState.NOT_EXECUTED,
                policy_verdict="DUPLICATE_BLOCKED",
                authority_mode=self.authority_gate.current_mode.value,
                error_message="Ejecución duplicada prevenida por IdempotencyGuard",
            )
            result = DecisionResult(
                request_id=request.request_id,
                state=DecisionState.NOT_EXECUTED,
                success=False,
                claims_success=False,
                message="Ejecución duplicada prevenida por IdempotencyGuard",
                executed_action=request.proposed_action,
                tool_used=request.tool,
                executor_status=ExecutionStatusType.SKIPPED,
                verification_status=VerificationStatusType.NOT_RUN,
                receipt_id=receipt.receipt_id,
                receipt_data=receipt.model_dump(),
                error_code="DUPLICATE_EXECUTION_BLOCKED",
                duration_ms=duration_ms,
            )
            self.authority_gate.metrics.record_canary_action(
                decision="DENY",
                final_state="NOT_EXECUTED",
                is_verified=False,
                execution_count=0,
            )
            self.audit_trail.record_decision(request, result, receipt)
            return result

        # ── 1. ESTADO: RECEIVED & ANALYZING (CONFLICT & AMBIGUITY CHECK) ──
        current_state = DecisionState.RECEIVED
        current_state = DecisionState.ANALYZING

        # Análisis previo de conflicto y ambigüedad (Fase 8)
        from core.jde.conflict import JDEConflictResolver
        conflict_resolver = JDEConflictResolver()
        conflict_res = conflict_resolver.resolve(
            action=request.proposed_action,
            tool=request.tool,
            user_prompt=request.user_request,
            risk_tier=request.risk_level,
            user_confirmed=request.policy_requirements.requires_human_confirmation,
        )

        if not conflict_res.is_allowed and conflict_res.resolved_state in (DecisionState.NO_DECISION, DecisionState.CONFLICT):
            finished_at = datetime.now(UTC)
            duration_ms = (time.perf_counter() - t_start) * 1000
            receipt = ActionReceipt.create(
                request_id=request.request_id,
                correlation_id=request.correlation_id,
                user_request=request.user_request,
                action=request.proposed_action,
                tool=request.tool,
                parameters=request.parameters,
                executor="none",
                verifier="none",
                started_at=started_at,
                finished_at=finished_at,
                execution_status=ExecutionStatusType.SKIPPED,
                verification_status=VerificationStatusType.NOT_RUN,
                verified=False,
                final_status=conflict_res.resolved_state,
                policy_verdict=conflict_res.resolved_state.value,
                authority_mode=self.authority_gate.current_mode.value,
                error_message=conflict_res.reason,
            )
            result = DecisionResult(
                request_id=request.request_id,
                state=conflict_res.resolved_state,
                success=False,
                claims_success=False,
                message=conflict_res.reason,
                executed_action=request.proposed_action,
                tool_used=request.tool,
                executor_status=ExecutionStatusType.SKIPPED,
                verification_status=VerificationStatusType.NOT_RUN,
                receipt_id=receipt.receipt_id,
                receipt_data=receipt.model_dump(),
                error_code=conflict_res.resolved_state.value,
                duration_ms=duration_ms,
            )
            self.audit_trail.record_decision(request, result, receipt)
            return result

        # ── 2. ESTADO: PLANNED ──
        current_state = DecisionState.PLANNED

        # ── 3. AUTHORITY GATE & POLICY ──
        auth_eval = self.authority_gate.evaluate_authority(
            action=request.proposed_action,
            tool=request.tool,
            parameters=request.parameters,
            user_confirmed=request.policy_requirements.requires_human_confirmation,
        )

        # Si el modo activo es CANARY, LIMITED, PROGRESSIVE o FULL, la gobernanza de autoridad controla estrictamente la ejecución
        if self.authority_gate.current_mode in (AuthorityMode.CANARY, AuthorityMode.LIMITED, AuthorityMode.PROGRESSIVE, AuthorityMode.FULL):
            active_auth_mode = self.authority_gate.current_mode.value
            if auth_eval.decision == AuthorityDecision.DENY:
                finished_at = datetime.now(UTC)
                duration_ms = (time.perf_counter() - t_start) * 1000
                receipt = ActionReceipt.create(
                    request_id=request.request_id,
                    correlation_id=request.correlation_id,
                    user_request=request.user_request,
                    action=request.proposed_action,
                    tool=request.tool,
                    parameters=request.parameters,
                    capability=auth_eval.capability_id,
                    executor="none",
                    verifier="none",
                    started_at=started_at,
                    finished_at=finished_at,
                    execution_status=ExecutionStatusType.SKIPPED,
                    verification_status=VerificationStatusType.NOT_RUN,
                    verified=False,
                    final_status=DecisionState.BLOCKED,
                    policy_verdict="DENY",
                    authority_mode=active_auth_mode,
                    risk_tier=auth_eval.risk_tier.value,
                    error_message=auth_eval.reason,
                )
                result = DecisionResult(
                    request_id=request.request_id,
                    state=DecisionState.BLOCKED,
                    success=False,
                    claims_success=False,
                    message=auth_eval.reason,
                    executed_action=request.proposed_action,
                    tool_used=request.tool,
                    executor_status=ExecutionStatusType.SKIPPED,
                    verification_status=VerificationStatusType.NOT_RUN,
                    receipt_id=receipt.receipt_id,
                    receipt_data=receipt.model_dump(),
                    error_code="POLICY_DENIED",
                    duration_ms=duration_ms,
                )
                if self.authority_gate.current_mode == AuthorityMode.CANARY:
                    self.authority_gate.metrics.record_canary_action(
                        decision="DENY",
                        final_state="BLOCKED",
                        is_verified=False,
                        execution_count=0,
                    )
                elif self.authority_gate.current_mode == AuthorityMode.LIMITED:
                    self.authority_gate.metrics.record_limited_action(
                        decision="DENY",
                        final_state="BLOCKED",
                        is_verified=False,
                        execution_count=0,
                    )
                elif self.authority_gate.current_mode == AuthorityMode.PROGRESSIVE:
                    self.authority_gate.metrics.record_progressive_action(
                        decision="DENY",
                        final_state="BLOCKED",
                        is_verified=False,
                        execution_count=0,
                    )
                elif self.authority_gate.current_mode == AuthorityMode.FULL:
                    self.authority_gate.metrics.record_full_action(
                        decision="DENY",
                        final_state="BLOCKED",
                        is_verified=False,
                        execution_count=0,
                    )
                self.audit_trail.record_decision(request, result, receipt)
                return result

            elif auth_eval.decision == AuthorityDecision.REQUIRE_VERIFICATION:
                finished_at = datetime.now(UTC)
                duration_ms = (time.perf_counter() - t_start) * 1000
                receipt = ActionReceipt.create(
                    request_id=request.request_id,
                    correlation_id=request.correlation_id,
                    user_request=request.user_request,
                    action=request.proposed_action,
                    tool=request.tool,
                    parameters=request.parameters,
                    capability=auth_eval.capability_id,
                    executor="none",
                    verifier="none",
                    started_at=started_at,
                    finished_at=finished_at,
                    execution_status=ExecutionStatusType.SKIPPED,
                    verification_status=VerificationStatusType.NOT_RUN,
                    verified=False,
                    final_status=DecisionState.NOT_EXECUTED,
                    policy_verdict="REQUIRE_VERIFICATION",
                    authority_mode=active_auth_mode,
                    risk_tier=auth_eval.risk_tier.value,
                    error_message=auth_eval.reason,
                )
                result = DecisionResult(
                    request_id=request.request_id,
                    state=DecisionState.NOT_EXECUTED,
                    success=False,
                    claims_success=False,
                    message=auth_eval.reason,
                    executed_action=request.proposed_action,
                    tool_used=request.tool,
                    executor_status=ExecutionStatusType.SKIPPED,
                    verification_status=VerificationStatusType.NOT_RUN,
                    receipt_id=receipt.receipt_id,
                    receipt_data=receipt.model_dump(),
                    error_code="REQUIRE_HUMAN_CONFIRMATION",
                    duration_ms=duration_ms,
                )
                if self.authority_gate.current_mode == AuthorityMode.LIMITED:
                    self.authority_gate.metrics.record_limited_action(
                        decision="REQUIRE_VERIFICATION",
                        final_state="NOT_EXECUTED",
                        is_verified=False,
                        execution_count=0,
                    )
                elif self.authority_gate.current_mode == AuthorityMode.PROGRESSIVE:
                    self.authority_gate.metrics.record_progressive_action(
                        decision="DENY",
                        final_state="NOT_EXECUTED",
                        is_verified=False,
                        execution_count=0,
                    )
                elif self.authority_gate.current_mode == AuthorityMode.FULL:
                    self.authority_gate.metrics.record_full_action(
                        decision="DENY",
                        final_state="NOT_EXECUTED",
                        is_verified=False,
                        execution_count=0,
                    )
                self.audit_trail.record_decision(request, result, receipt)
                return result

            elif auth_eval.decision == AuthorityDecision.OBSERVE_ONLY:
                finished_at = datetime.now(UTC)
                duration_ms = (time.perf_counter() - t_start) * 1000
                receipt = ActionReceipt.create(
                    request_id=request.request_id,
                    correlation_id=request.correlation_id,
                    user_request=request.user_request,
                    action=request.proposed_action,
                    tool=request.tool,
                    parameters=request.parameters,
                    capability=auth_eval.capability_id,
                    executor="none",
                    verifier="none",
                    started_at=started_at,
                    finished_at=finished_at,
                    execution_status=ExecutionStatusType.SKIPPED,
                    verification_status=VerificationStatusType.NOT_RUN,
                    verified=False,
                    final_status=DecisionState.NOT_EXECUTED,
                    policy_verdict="OBSERVE_ONLY",
                    authority_mode=active_auth_mode,
                    risk_tier=auth_eval.risk_tier.value,
                    error_message=auth_eval.reason,
                )
                result = DecisionResult(
                    request_id=request.request_id,
                    state=DecisionState.NOT_EXECUTED,
                    success=False,
                    claims_success=False,
                    message=auth_eval.reason,
                    executed_action=request.proposed_action,
                    tool_used=request.tool,
                    executor_status=ExecutionStatusType.SKIPPED,
                    verification_status=VerificationStatusType.NOT_RUN,
                    receipt_id=receipt.receipt_id,
                    receipt_data=receipt.model_dump(),
                    error_code="SCOPE_EXCLUDED",
                    duration_ms=duration_ms,
                )
                if self.authority_gate.current_mode == AuthorityMode.CANARY:
                    self.authority_gate.metrics.record_canary_action(
                        decision="OBSERVE_ONLY",
                        final_state="NOT_EXECUTED",
                        is_verified=False,
                        execution_count=0,
                    )
                elif self.authority_gate.current_mode == AuthorityMode.LIMITED:
                    self.authority_gate.metrics.record_limited_action(
                        decision="OBSERVE_ONLY",
                        final_state="NOT_EXECUTED",
                        is_verified=False,
                        execution_count=0,
                    )
                elif self.authority_gate.current_mode == AuthorityMode.PROGRESSIVE:
                    self.authority_gate.metrics.record_progressive_action(
                        decision="DENY",
                        final_state="NOT_EXECUTED",
                        is_verified=False,
                        execution_count=0,
                    )
                self.audit_trail.record_decision(request, result, receipt)
                return result

        pol_dec = self.policy_gate.evaluate(
            tool=request.tool,
            action=request.proposed_action,
            parameters=request.parameters,
            user_confirmed=request.policy_requirements.requires_human_confirmation,
            declared_risk=request.risk_level,
        )

        if not pol_dec.is_allowed:
            finished_at = datetime.now(UTC)
            duration_ms = (time.perf_counter() - t_start) * 1000
            receipt = ActionReceipt.create(
                request_id=request.request_id,
                correlation_id=request.correlation_id,
                user_request=request.user_request,
                action=request.proposed_action,
                tool=request.tool,
                parameters=request.parameters,
                executor="none",
                verifier="none",
                started_at=started_at,
                finished_at=finished_at,
                execution_status=ExecutionStatusType.SKIPPED,
                verification_status=VerificationStatusType.NOT_RUN,
                verified=False,
                final_status=DecisionState.BLOCKED,
                policy_verdict="DENY" if not pol_dec.requires_confirmation else "REQUIRES_CONFIRMATION",
                authority_mode=self.authority_gate.current_mode.value,
                risk_tier=auth_eval.risk_tier.value,
                error_message=pol_dec.reason,
            )
            result = DecisionResult(
                request_id=request.request_id,
                state=DecisionState.BLOCKED,
                success=False,
                claims_success=False,
                message=pol_dec.reason,
                executed_action=request.proposed_action,
                tool_used=request.tool,
                executor_status=ExecutionStatusType.SKIPPED,
                verification_status=VerificationStatusType.NOT_RUN,
                receipt_id=receipt.receipt_id,
                receipt_data=receipt.model_dump(),
                error_code="POLICY_BLOCKED" if not pol_dec.requires_confirmation else "REQUIRES_CONFIRMATION",
                duration_ms=duration_ms,
            )
            self.audit_trail.record_decision(request, result, receipt)
            return result

        # ── 4. ESTADO: AUTHORIZED ──
        current_state = DecisionState.AUTHORIZED

        # ── 5. EJECUCIÓN (CON SOPORTE DE RETRY Y FALLBACK) ──
        active_tool = request.tool
        active_action = request.proposed_action
        active_params = request.parameters
        used_fallback = False
        retry_count = 0

        exec_status = ExecutionStatusType.PENDING
        exec_output: Any = None
        verif_status = VerificationStatusType.NOT_RUN
        is_verified = False
        evidence_list: list[JDEEvidence] = []
        final_state = DecisionState.FAILED
        final_message = ""

        # En CANARY, LIMITED y PROGRESSIVE no se permiten reintentos automáticos
        effective_max_retries = 0 if auth_eval.mode in (AuthorityMode.CANARY, AuthorityMode.LIMITED, AuthorityMode.PROGRESSIVE) else self.max_retries

        # Bucle de ejecución/reintento
        while retry_count <= effective_max_retries:
            current_state = DecisionState.EXECUTING
            try:
                exec_status, exec_output = executor(active_tool, active_params)
            except Exception as ex:
                logger.error(f"[JDE EXECUTOR ERROR] Error al ejecutar '{active_tool}': {ex}")
                exec_status = ExecutionStatusType.ERROR
                exec_output = {"error": str(ex)}

            # Si el executor falló físicamente
            if exec_status != ExecutionStatusType.OK:
                # Comprobar si hay fallback antes de declarar fallo definitivo
                if request.fallback and not used_fallback:
                    logger.warning(f"[JDE ENGINE] Executor primario falló ({exec_status}). Activando FALLBACK.")
                    current_state = DecisionState.FALLBACK
                    active_tool = request.fallback.tool
                    active_action = request.fallback.action
                    active_params = request.fallback.parameters
                    used_fallback = True
                    continue

                final_state = DecisionState.FAILED
                final_message = f"Fallo en la ejecución de la herramienta '{active_tool}'."
                break

            # ── 6. ESTADO: VERIFYING ──
            current_state = DecisionState.VERIFYING

            # Caso 6.1: Verifier Override (e.g. en tests o callbacks personalizados)
            if verifier_override is not None:
                v_stat, v_ok, v_obs = verifier_override(active_params)
                verif_status = v_stat
                is_verified = v_ok
                ev = JDEEvidence(
                    verification_type="override",
                    target=active_action,
                    is_verified=v_ok,
                    observed_state=v_obs,
                )
                evidence_list.append(ev)
            # Caso 6.2: Verificación declarativa mediante VerifierRegistry
            elif request.verification_requirements:
                all_ok = True
                has_unknown = False
                for req in request.verification_requirements:
                    out = self.verifier_registry.verify_requirement(req, context=active_params)
                    evidence_list.append(out.evidence)
                    if out.status == VerificationStatusType.UNVERIFIABLE:
                        has_unknown = True
                    if not out.is_verified:
                        all_ok = False

                if all_ok:
                    verif_status = VerificationStatusType.VERIFIED_TRUE
                    is_verified = True
                elif has_unknown:
                    verif_status = VerificationStatusType.UNVERIFIABLE
                    is_verified = False
                else:
                    verif_status = VerificationStatusType.VERIFIED_FALSE
                    is_verified = False
            else:
                # Si no se declararon requisitos de verificación:
                # PRINCIPIO ANTI-FALSE SUCCESS: No asumir éxito. Estado UNKNOWN.
                verif_status = VerificationStatusType.UNVERIFIABLE
                is_verified = False
                evidence_list.append(
                    JDEEvidence(
                        verification_type="no_contract_declared",
                        target=active_action,
                        is_verified=False,
                        details={"warning": "La acción no declaró contrato de verificación."},
                    )
                )

            # ── 7. RESOLUCIÓN DE ESTADO FINAL TRAS VERIFICACIÓN ──
            if is_verified and verif_status == VerificationStatusType.VERIFIED_TRUE:
                final_state = DecisionState.SUCCESS
                final_message = f"Acción '{active_action}' ejecutada y verificada exitosamente en el sistema."
                break
            elif verif_status == VerificationStatusType.UNVERIFIABLE:
                # INVARIANTE: NUNCA CONVERTIR UNKNOWN EN SUCCESS
                final_state = DecisionState.UNKNOWN
                final_message = f"Acción '{active_action}' ejecutada, pero no pudo verificarse su efecto real."
                break
            else:
                # Verificación negativa (el efecto real NO ocurrió)
                logger.warning(f"[JDE VERIFIER NEGATIVE] Verificación negativa para '{active_tool}:{active_action}'.")
                # Intentar fallback si está disponible y no se ha usado
                if request.fallback and not used_fallback:
                    logger.warning("[JDE ENGINE] Verificación primaria negativa. Intentando FALLBACK.")
                    current_state = DecisionState.FALLBACK
                    active_tool = request.fallback.tool
                    active_action = request.fallback.action
                    active_params = request.fallback.parameters
                    used_fallback = True
                    continue

                # Intentar reintento controlado si está configurado
                if retry_count < self.max_retries:
                    retry_count += 1
                    logger.info(f"[JDE ENGINE] Reintentando acción ({retry_count}/{self.max_retries})...")
                    current_state = DecisionState.RETRY
                    time.sleep(0.05)
                    continue

                final_state = DecisionState.FAILED
                final_message = f"La acción '{active_action}' fue ejecutada pero la verificación de estado real falló."
                break

        finished_at = datetime.now(UTC)
        duration_ms = (time.perf_counter() - t_start) * 1000

        # Invariante: claims_success solo es True si final_state == SUCCESS
        claims_success = (final_state == DecisionState.SUCCESS)

        # ── 8. GENERACIÓN DE RECIBO CON VINCULACIÓN CRIPTOGRÁFICA ──
        receipt = ActionReceipt.create(
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            user_request=request.user_request,
            action=active_action,
            tool=active_tool,
            parameters=active_params,
            capability=auth_eval.capability_id,
            executor=f"{active_tool}_executor",
            verifier="jde_verifier_registry",
            started_at=started_at,
            finished_at=finished_at,
            execution_status=exec_status,
            verification_status=verif_status,
            verified=is_verified,
            final_status=final_state,
            evidence=evidence_list,
            policy_verdict=pol_dec.rule_matched or "ALLOW",
            authority_mode=self.authority_gate.current_mode.value,
            risk_tier=auth_eval.risk_tier.value,
            error_message=None if claims_success else final_message,
            metadata={"used_fallback": used_fallback, "retry_count": retry_count},
        )

        # Registro de telemetría de promoción en manager
        if auth_eval.capability_id:
            try:
                from core.jde.promotion import get_promotion_manager
                get_promotion_manager().record_execution(
                    capability_id=auth_eval.capability_id,
                    request_id=request.request_id,
                    final_status=final_state,
                    is_verified=is_verified,
                    execution_count=1 if exec_status == ExecutionStatusType.OK else 0,
                    evidence=evidence_list[0].model_dump() if evidence_list else None,
                )
            except Exception as prom_ex:
                logger.debug(f"[JDE ENGINE] No se pudo registrar ejecución en PromotionManager: {prom_ex}")

        if self.authority_gate.current_mode == AuthorityMode.CANARY:
            self.authority_gate.metrics.record_canary_action(
                decision="ALLOW",
                final_state=final_state.value,
                is_verified=is_verified,
                execution_count=1 if exec_status == ExecutionStatusType.OK else 0,
            )
        elif self.authority_gate.current_mode == AuthorityMode.LIMITED:
            self.authority_gate.metrics.record_limited_action(
                decision="ALLOW",
                final_state=final_state.value,
                is_verified=is_verified,
                execution_count=1 if exec_status == ExecutionStatusType.OK else 0,
            )
        elif self.authority_gate.current_mode == AuthorityMode.PROGRESSIVE:
            self.authority_gate.metrics.record_progressive_action(
                decision="ALLOW",
                final_state=final_state.value,
                is_verified=is_verified,
                execution_count=1 if exec_status == ExecutionStatusType.OK else 0,
            )
        elif self.authority_gate.current_mode == AuthorityMode.FULL:
            self.authority_gate.metrics.record_full_action(
                decision="ALLOW",
                final_state=final_state.value,
                is_verified=is_verified,
                execution_count=1 if exec_status == ExecutionStatusType.OK else 0,
            )


        # ── 9. REGISTRO EN AUDIT TRAIL ──
        result = DecisionResult(
            request_id=request.request_id,
            state=final_state,
            success=claims_success,
            claims_success=claims_success,
            message=final_message,
            executed_action=active_action,
            tool_used=active_tool,
            executor_status=exec_status,
            verification_status=verif_status,
            used_fallback=used_fallback,
            retry_count=retry_count,
            receipt_id=receipt.receipt_id,
            receipt_data=receipt.model_dump(),
            error_code=None if claims_success else final_state.value,
            duration_ms=duration_ms,
        )

        self.audit_trail.record_decision(request, result, receipt)
        logger.info(
            f"[JDE ENGINE] Solicitud {request.request_id} completada en {duration_ms:.1f}ms. "
            f"Estado: {final_state.value} (claims_success={claims_success})"
        )
        return result


_GLOBAL_DECISION_ENGINE: DecisionEngine | None = None


def get_decision_engine() -> DecisionEngine:
    global _GLOBAL_DECISION_ENGINE
    if _GLOBAL_DECISION_ENGINE is None:
        _GLOBAL_DECISION_ENGINE = DecisionEngine()
    return _GLOBAL_DECISION_ENGINE
