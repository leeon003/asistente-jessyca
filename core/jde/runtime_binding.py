"""JESSYCA Decision Engine (JDE) - Runtime Binding (Fase 1).

Conecta de forma centralizada el motor determinista de decisión JDE al punto
real de ejecución en el agente principal, ANTES de que cualquier herramienta
o acción produzca efectos secundarios en el sistema operativo.

Arquitectura canónica:
Intent
↓
Planner / Agent
↓
JDE Runtime Binding (ALLOW / DENY / REQUIRE_REVIEW)
↓
RiskEngine
↓
PermissionManager
↓
IdempotencyGuard
↓
ExecutionBoundary
↓
Tool / Skill / Adapter
↓
ExecutionVerifier
↓
Receipt / Audit

INVARIANTES ABSOLUTAS:
1. "Tool execution succeeded" != "Real-world action succeeded" (Anti-False Success).
2. JDE Runtime Binding NUNCA salta RiskEngine, PermissionManager, IdempotencyGuard,
   ExecutionBoundary ni ExecutionVerifier.
3. El modo por defecto es estrictamente CONTROLLED.
4. ACTIVE está categóricamente PROHIBIDO en Fase 1 y protegido contra activación accidental.
5. Kill Switch activo impone bloqueo inmediato (DENY) en CONTROLLED.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.execution.idempotency_guard import (
    ExecutionIdempotencyGuard,
    get_idempotency_guard,
)
from core.jde.audit import JDEAuditTrail
from core.jde.authority import (
    ActionRiskTier,
    AuthorityDecision,
    JDEAuthorityGate,
    classify_action_risk,
    get_authority_gate,
)
from core.jde.confirmation import (
    JDEConfirmationManager,
    get_confirmation_manager,
)
from core.jde.conflict import JDEConflictResolver
from core.jde.contract import DecisionContract
from core.jde.policy import JDEPolicyGate
from core.jde.receipts import ActionReceipt
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from core.logger import get_logger

logger = get_logger("jessyca.jde.runtime_binding")


class JDERuntimeMode(StrEnum):
    """Modos operativos del JDE Runtime Binding."""

    SHADOW = "SHADOW"
    CONTROLLED = "CONTROLLED"
    ACTIVE = "ACTIVE"


class JDERuntimeVerdictType(StrEnum):
    """Veredictos formales de autorización del JDE Runtime Binding."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_REVIEW = "REQUIRE_REVIEW"


class JDERuntimeVerdict(BaseModel):
    """Veredicto inmutable emitido por el JDE Runtime Binding antes del despacho."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: JDERuntimeVerdictType
    reason: str
    action: str
    tool: str
    risk_level: str = "SAFE"
    runtime_mode: JDERuntimeMode = JDERuntimeMode.CONTROLLED
    is_blocked: bool = False
    requires_human_confirmation: bool = False
    contract: DecisionContract | None = None
    receipt: ActionReceipt | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    execution_fingerprint: str | None = None

    @property
    def can_proceed_to_execution(self) -> bool:
        """Indica si el flujo puede continuar hacia las capas de seguridad y ejecución física."""
        return self.verdict == JDERuntimeVerdictType.ALLOW and not self.is_blocked


class JDERuntimeBinding:
    """Enlace centralizado de gobernanza del JDE para el tiempo de ejecución."""

    _instance: JDERuntimeBinding | None = None
    _lock: threading.Lock = threading.Lock()

    # Invariante de seguridad: ACTIVE está bloqueado en Fase 1
    PHASE1_ALLOW_ACTIVE: bool = False

    def __init__(
        self,
        mode: JDERuntimeMode | str | None = None,
        authority_gate: JDEAuthorityGate | None = None,
        idempotency_guard: ExecutionIdempotencyGuard | None = None,
        audit_trail: JDEAuditTrail | None = None,
        conflict_resolver: JDEConflictResolver | None = None,
        policy_gate: JDEPolicyGate | None = None,
        confirmation_manager: JDEConfirmationManager | None = None,
    ) -> None:
        self._mutex = threading.RLock()
        self.authority_gate = authority_gate or get_authority_gate()
        self.idempotency_guard = idempotency_guard or get_idempotency_guard()
        self.audit_trail = audit_trail or JDEAuditTrail()
        self.conflict_resolver = conflict_resolver or JDEConflictResolver()
        self.policy_gate = policy_gate or JDEPolicyGate()
        self.confirmation_manager = confirmation_manager or get_confirmation_manager()
        self._mode = self._resolve_runtime_mode(mode)

    @classmethod
    def _resolve_runtime_mode(cls, raw_input: Any) -> JDERuntimeMode:
        """Resuelve el modo aplicando las restricciones de seguridad inmutables."""
        candidate = raw_input
        if candidate is None:
            candidate = os.getenv("JDE_RUNTIME_MODE", "CONTROLLED")

        cleaned = str(getattr(candidate, "value", candidate)).strip().upper()

        if cleaned == "ACTIVE":
            if not cls.PHASE1_ALLOW_ACTIVE:
                logger.critical(
                    "[JDE SECURITY ALERT] Intento de activación de 'ACTIVE' bloqueado. "
                    "Fase 1 prohíbe ACTIVE categóricamente. Forzando CONTROLLED."
                )
                return JDERuntimeMode.CONTROLLED
            return JDERuntimeMode.ACTIVE

        if cleaned == "SHADOW":
            return JDERuntimeMode.SHADOW

        if cleaned == "CONTROLLED":
            return JDERuntimeMode.CONTROLLED

        logger.warning(
            f"[JDE RUNTIME BINDING] Modo '{cleaned}' no reconocido. Fail-Safe: forzando CONTROLLED."
        )
        return JDERuntimeMode.CONTROLLED

    @property
    def current_mode(self) -> JDERuntimeMode:
        """Modo de runtime actualmente activo."""
        with self._mutex:
            return self._mode

    def set_mode(self, mode: JDERuntimeMode | str) -> tuple[bool, str]:
        """Cambia el modo de runtime respetando las invariantes de Fase 1."""
        with self._mutex:
            resolved = self._resolve_runtime_mode(mode)
            cleaned = str(getattr(mode, "value", mode)).strip().upper()
            if cleaned == "ACTIVE" and not self.PHASE1_ALLOW_ACTIVE:
                return False, "ACTIVE no está permitido en Fase 1 (protección contra activación accidental)."
            self._mode = resolved
            logger.info(f"[JDE RUNTIME BINDING] Modo actualizado a {resolved.value}.")
            return True, f"Modo actualizado a {resolved.value}."

    def evaluate(
        self,
        intent: str,
        action: str,
        tool: str,
        parameters: dict[str, Any] | None = None,
        user_confirmed: bool = False,
        session_id: str = "default_session",
        request_id: str = "",
        risk_level: str = "SAFE",
        user_id: str = "default_user",
    ) -> JDERuntimeVerdict:
        """Evalúa determinísticamente si una acción puede proceder ANTES de cualquier efecto secundario.

        Veredictos posibles:
        - ALLOW: Proceder a RiskEngine, PermissionManager, IdempotencyGuard y despacho.
        - DENY: Interceptar y abortar sin producir ningún efecto secundario.
        - REQUIRE_REVIEW: Pausar y exigir aprobación explícita del usuario.
        """
        raw_params = parameters or {}
        # Invariante de seguridad: NUNCA aceptar is_confirmed o confirmed inyectados por LLM o parámetros crudos
        cleaned_params = {k: v for k, v in raw_params.items() if k not in ("is_confirmed", "confirmed")}
        req_id = request_id or f"jde-rt-{int(datetime.now(UTC).timestamp()*1000)}"
        t_now = datetime.now(UTC)

        # ── 0. VERIFICACIÓN DE CONFIRMACIÓN HUMANA VINCULADA ESTRICTAMENTE ──
        # Solo se considera confirmado si el gestor de confirmación vinculado valida y consume el token
        # para esta sesión, acción, parámetros e identidad, O si fue validado por callback confiable.
        has_bound_confirmation = self.confirmation_manager.verify_and_consume(
            session_id=session_id,
            action=action,
            parameters=cleaned_params,
            user_id=user_id,
        )
        effective_user_confirmed = bool(has_bound_confirmation or user_confirmed)

        # ── 1. VERIFICACIÓN DE KILL SWITCH DE EMERGENCIA ──
        if self.authority_gate.is_kill_switch_active:
            reason = "Kill Switch activo en JDE Authority Gate. Operaciones bloqueadas por seguridad."
            logger.critical(f"[JDE RUNTIME BINDING] {reason} [Action: {action}, Tool: {tool}]")

            contract = DecisionContract.create(
                intent=intent,
                selected_action=action,
                reason=reason,
                decision_id=req_id,
                session_id=session_id,
                context=cleaned_params,
                risk_level=risk_level,
                permission_status="DENIED",
                idempotency_status="NOT_ACQUIRED",
                authority_level=self.authority_gate.current_mode.value,
                decision_status=DecisionState.BLOCKED,
                timestamp=t_now,
            )

            receipt = ActionReceipt.create(
                request_id=req_id,
                correlation_id=req_id,
                user_request=intent,
                action=action,
                tool=tool,
                parameters=cleaned_params,
                executor="none",
                verifier="none",
                started_at=t_now,
                finished_at=t_now,
                execution_status=ExecutionStatusType.SKIPPED,
                verification_status=VerificationStatusType.NOT_RUN,
                verified=False,
                final_status=DecisionState.BLOCKED,
                policy_verdict="KILL_SWITCH_ACTIVE",
                authority_mode=self.authority_gate.current_mode.value,
                error_message=reason,
            )

            return JDERuntimeVerdict(
                verdict=JDERuntimeVerdictType.DENY,
                reason=reason,
                action=action,
                tool=tool,
                risk_level=risk_level,
                runtime_mode=self.current_mode,
                is_blocked=True,
                requires_human_confirmation=False,
                contract=contract,
                receipt=receipt,
                timestamp=t_now,
            )

        # ── 2. VERIFICACIÓN DETERMINISTA DE CONFLICTOS Y POLÍTICAS (JDEConflictResolver) ──
        conflict_res = self.conflict_resolver.resolve(
            action=action,
            tool=tool,
            user_prompt=intent,
            risk_tier=risk_level,
            user_confirmed=effective_user_confirmed,
        )

        if not conflict_res.is_allowed and conflict_res.resolved_state in (DecisionState.NO_DECISION, DecisionState.CONFLICT):
            reason = f"Conflicto determinista detectado por JDE: {conflict_res.reason}"
            logger.warning(f"[JDE RUNTIME BINDING] {reason} [Action: {action}]")

            if self.current_mode == JDERuntimeMode.CONTROLLED:
                contract = DecisionContract.create(
                    intent=intent,
                    selected_action=action,
                    reason=reason,
                    decision_id=req_id,
                    session_id=session_id,
                    context=cleaned_params,
                    risk_level=risk_level,
                    permission_status="DENIED",
                    idempotency_status="NOT_ACQUIRED",
                    authority_level=self.authority_gate.current_mode.value,
                    decision_status=conflict_res.resolved_state,
                    timestamp=t_now,
                )
                receipt = ActionReceipt.create(
                    request_id=req_id,
                    correlation_id=req_id,
                    user_request=intent,
                    action=action,
                    tool=tool,
                    parameters=cleaned_params,
                    executor="none",
                    verifier="none",
                    started_at=t_now,
                    finished_at=t_now,
                    execution_status=ExecutionStatusType.SKIPPED,
                    verification_status=VerificationStatusType.NOT_RUN,
                    verified=False,
                    final_status=conflict_res.resolved_state,
                    policy_verdict="CONFLICT_DENIED",
                    authority_mode=self.authority_gate.current_mode.value,
                    error_message=reason,
                )
                return JDERuntimeVerdict(
                    verdict=JDERuntimeVerdictType.DENY,
                    reason=reason,
                    action=action,
                    tool=tool,
                    risk_level=risk_level,
                    runtime_mode=self.current_mode,
                    is_blocked=True,
                    requires_human_confirmation=False,
                    contract=contract,
                    receipt=receipt,
                    timestamp=t_now,
                )

        # ── 3. EVALUACIÓN MEDIANTE EL AUTHORITY GATE Y POLICY GATE ──
        auth_eval = self.authority_gate.evaluate_authority(
            action=action,
            tool=tool,
            parameters=cleaned_params,
            user_confirmed=effective_user_confirmed,
        )

        pol_dec = self.policy_gate.evaluate(
            tool=tool,
            action=action,
            parameters=cleaned_params,
            user_confirmed=effective_user_confirmed,
            declared_risk=risk_level,
        )

        # ── 4. RESOLUCIÓN SEGÚN JDE_RUNTIME_MODE ──

        # MODO SHADOW: Evalúa, registra, emite contrato, pero NUNCA bloquea
        if self.current_mode == JDERuntimeMode.SHADOW:
            contract = DecisionContract.create(
                intent=intent,
                selected_action=action,
                reason=f"Evaluación Shadow: veredicto original={auth_eval.decision.value}. {auth_eval.reason}",
                decision_id=req_id,
                session_id=session_id,
                context=cleaned_params,
                risk_level=auth_eval.risk_tier.value,
                permission_status="ALLOW",
                idempotency_status="ACQUIRED",
                authority_level="SHADOW",
                decision_status=DecisionState.AUTHORIZED,
                timestamp=t_now,
            )
            return JDERuntimeVerdict(
                verdict=JDERuntimeVerdictType.ALLOW,
                reason=f"Shadow mode activo: observación pasiva ({auth_eval.reason}).",
                action=action,
                tool=tool,
                risk_level=auth_eval.risk_tier.value,
                runtime_mode=JDERuntimeMode.SHADOW,
                is_blocked=False,
                requires_human_confirmation=False,
                contract=contract,
                timestamp=t_now,
            )

        # MODO CONTROLLED (Obligatorio en Fase 1)
        policy_denied = (not pol_dec.is_allowed and not pol_dec.requires_confirmation)
        is_denied = (
            auth_eval.decision == AuthorityDecision.DENY
            or risk_level.upper() == "CRITICAL"
            or policy_denied
        )

        if is_denied:
            deny_reason = auth_eval.reason if auth_eval.decision == AuthorityDecision.DENY else (
                pol_dec.reason if policy_denied else (
                    f"Acción crítica/destructiva '{action}' en herramienta '{tool}' denegada por gobernanza JDE."
                )
            )
            reason = f"Acción denegada por gobernanza JDE: {deny_reason}"
            logger.warning(f"[JDE RUNTIME BINDING - DENIED] {reason}")
            contract = DecisionContract.create(
                intent=intent,
                selected_action=action,
                reason=reason,
                decision_id=req_id,
                session_id=session_id,
                context=cleaned_params,
                risk_level=auth_eval.risk_tier.value,
                permission_status="DENIED",
                idempotency_status="NOT_ACQUIRED",
                authority_level=self.authority_gate.current_mode.value,
                decision_status=DecisionState.DENIED,
                timestamp=t_now,
            )
            receipt = ActionReceipt.create(
                request_id=req_id,
                correlation_id=req_id,
                user_request=intent,
                action=action,
                tool=tool,
                parameters=cleaned_params,
                executor="none",
                verifier="none",
                started_at=t_now,
                finished_at=t_now,
                execution_status=ExecutionStatusType.SKIPPED,
                verification_status=VerificationStatusType.NOT_RUN,
                verified=False,
                final_status=DecisionState.DENIED,
                policy_verdict="DENY",
                authority_mode=self.authority_gate.current_mode.value,
                risk_tier=auth_eval.risk_tier.value,
                error_message=reason,
            )
            return JDERuntimeVerdict(
                verdict=JDERuntimeVerdictType.DENY,
                reason=reason,
                action=action,
                tool=tool,
                risk_level=auth_eval.risk_tier.value,
                runtime_mode=JDERuntimeMode.CONTROLLED,
                is_blocked=True,
                requires_human_confirmation=False,
                contract=contract,
                receipt=receipt,
                timestamp=t_now,
            )

        needs_review = (
            auth_eval.decision == AuthorityDecision.REQUIRE_VERIFICATION
            or auth_eval.requires_human_confirmation
            or pol_dec.requires_confirmation
            or auth_eval.risk_tier == ActionRiskTier.HIGH
            or classify_action_risk(action, tool) == ActionRiskTier.HIGH
            or risk_level.upper() in ("HIGH", "CRITICAL")
        )

        if needs_review:
            if effective_user_confirmed:
                # Confirmado explícitamente: autorizar a continuar
                contract = DecisionContract.create(
                    intent=intent,
                    selected_action=action,
                    reason=f"Acción autorizada tras confirmación humana válida: {auth_eval.reason}",
                    decision_id=req_id,
                    session_id=session_id,
                    context=cleaned_params,
                    risk_level=auth_eval.risk_tier.value,
                    permission_status="ALLOW",
                    idempotency_status="ACQUIRED",
                    authority_level=self.authority_gate.current_mode.value,
                    decision_status=DecisionState.AUTHORIZED,
                    timestamp=t_now,
                )
                return JDERuntimeVerdict(
                    verdict=JDERuntimeVerdictType.ALLOW,
                    reason=f"Confirmación humana verificada. {auth_eval.reason}",
                    action=action,
                    tool=tool,
                    risk_level=auth_eval.risk_tier.value,
                    runtime_mode=JDERuntimeMode.CONTROLLED,
                    is_blocked=False,
                    requires_human_confirmation=False,
                    contract=contract,
                    timestamp=t_now,
                )
            else:
                # Sin confirmación: registrar confirmación vinculada estrictamente y BLOQUEAR el side effect
                review_reason = pol_dec.reason if pol_dec.requires_confirmation else auth_eval.reason
                reason = f"Revisión humana requerida por JDE: {review_reason}"
                logger.info(f"[JDE RUNTIME BINDING - REQUIRE_REVIEW] {reason}")

                # Registrar en ConfirmationManager para permitir validación vinculada posterior
                self.confirmation_manager.register_pending_confirmation(
                    session_id=session_id,
                    action=action,
                    tool=tool,
                    parameters=cleaned_params,
                    user_id=user_id,
                )

                contract = DecisionContract.create(
                    intent=intent,
                    selected_action=action,
                    reason=reason,
                    decision_id=req_id,
                    session_id=session_id,
                    context=cleaned_params,
                    risk_level=auth_eval.risk_tier.value,
                    permission_status="REQUIRE_CONFIRMATION",
                    idempotency_status="NOT_ACQUIRED",
                    authority_level=self.authority_gate.current_mode.value,
                    decision_status=DecisionState.REQUIRES_CONFIRMATION,
                    timestamp=t_now,
                )
                return JDERuntimeVerdict(
                    verdict=JDERuntimeVerdictType.REQUIRE_REVIEW,
                    reason=reason,
                    action=action,
                    tool=tool,
                    risk_level=auth_eval.risk_tier.value,
                    runtime_mode=JDERuntimeMode.CONTROLLED,
                    is_blocked=True,
                    requires_human_confirmation=True,
                    contract=contract,
                    timestamp=t_now,
                )

        # AuthorityDecision.ALLOW: autorizada para proceder a las capas de seguridad física
        contract = DecisionContract.create(
            intent=intent,
            selected_action=action,
            reason=f"Acción autorizada por JDE: {auth_eval.reason}",
            decision_id=req_id,
            session_id=session_id,
            context=cleaned_params,
            risk_level=auth_eval.risk_tier.value,
            permission_status="ALLOW",
            idempotency_status="ACQUIRED",
            authority_level=self.authority_gate.current_mode.value,
            decision_status=DecisionState.AUTHORIZED,
            timestamp=t_now,
        )

        return JDERuntimeVerdict(
            verdict=JDERuntimeVerdictType.ALLOW,
            reason=auth_eval.reason,
            action=action,
            tool=tool,
            risk_level=auth_eval.risk_tier.value,
            runtime_mode=JDERuntimeMode.CONTROLLED,
            is_blocked=False,
            requires_human_confirmation=False,
            contract=contract,
            timestamp=t_now,
        )


_GLOBAL_RUNTIME_BINDING: JDERuntimeBinding | None = None
_GLOBAL_RUNTIME_BINDING_LOCK = threading.Lock()


def get_jde_runtime_binding() -> JDERuntimeBinding:
    """Retorna la instancia global singleton del JDE Runtime Binding."""
    global _GLOBAL_RUNTIME_BINDING
    with _GLOBAL_RUNTIME_BINDING_LOCK:
        if _GLOBAL_RUNTIME_BINDING is None:
            _GLOBAL_RUNTIME_BINDING = JDERuntimeBinding()
        return _GLOBAL_RUNTIME_BINDING


def reset_jde_runtime_binding() -> None:
    """Restablece el singleton global de JDE Runtime Binding (útil en pruebas)."""
    global _GLOBAL_RUNTIME_BINDING
    with _GLOBAL_RUNTIME_BINDING_LOCK:
        _GLOBAL_RUNTIME_BINDING = None
