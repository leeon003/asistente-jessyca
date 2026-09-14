"""Execution Gate & Confirmation Bridge para ActionIntentContract (Fase 64.2.2).

Puente desacoplado y determinista entre el Action Planner (ActionIntentContract),
el subsistema de seguridad (SecurityManager, RiskEngine, SecurityPolicy) y el
sistema de confirmación estructurada (ConfirmationManager, ConfirmationStatus, ConfirmationRequest).

REGLAS Y GARANTÍAS DE SEGURIDAD:
1. DESACOPLAMIENTO: No ejecuta acciones del SO, ni skills, ni procesos, ni comandos.
2. DETERMINISMO: Evalúa el ActionIntentContract y produce un ExecutionDecision determinista
   (EXECUTE, ASK_CONFIRMATION, REJECT, CLARIFY).
3. FAIL-SAFE / ANTI-BYPASS:
   - Jamás promueve ASK_CONFIRMATION a EXECUTE sin confirmación previa válida y no expirada.
   - Jamás ejecuta acciones con riesgo no permitido por la política (REJECT).
   - Respeta el umbral de confianza (< 0.70 o needs_clarification) para emitir CLARIFY.
4. BINDING DE FINGERPRINT & REPLAY PROTECTION:
   - La confirmación queda vinculada unívocamente al ActionFingerprint (SHA-256 de tool, operation, params).
   - Toda confirmación consumida queda invalidada para evitar ataques de repetición (ALLOW_ONCE).
5. ANTI-FALSE SUCCESS:
   - Ninguna decisión de gate declara un reporte de ejecución falso ni marca claims_success.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.action_intent_contract import (
    ActionIntent,
    ActionIntentContract,
    ExecutionGate,
    ExecutionSpec,
)
from core.confirmation import (
    ConfirmationManager,
    ConfirmationRequest,
    compute_action_fingerprint,
)
from core.logger import get_logger
from core.security import (
    PermissionAction,
    RiskLevel,
    SecurityDecision,
    SecurityManager,
    SecurityPolicy,
    ToolSecurityProfile,
)

logger = get_logger("jessyca.execution.execution_gate_bridge")


class GateDecisionType(StrEnum):
    """Tipo canónico de decisión emitida por el Execution Gate."""

    EXECUTE = "EXECUTE"
    ASK_CONFIRMATION = "ASK_CONFIRMATION"
    REJECT = "REJECT"
    CLARIFY = "CLARIFY"


class ConfirmationBridgeStatus(StrEnum):
    """Estados del ciclo de vida de una confirmación en el Execution Gate Bridge."""

    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class ExecutionDecision:
    """Decisión estructurada previa a cualquier despacho al executor.

    Transporta toda la información contextual para que las fases posteriores
    conozcan de forma transparente el resultado de las compuertas de seguridad.
    """

    decision_type: GateDecisionType
    contract: ActionIntentContract
    reason: str
    action_intent: ActionIntent
    execution_gate: ExecutionGate
    execution_spec: ExecutionSpec | None
    risk_level: str
    confidence: float
    skill_id: str | None = None
    operation: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    confirmation_request: ConfirmationRequest | None = None
    clarification_prompt: str | None = None
    confirmation_prompt: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def can_proceed_to_execution(self) -> bool:
        """Determina si el ejecutor tiene autorización formal para despachar la acción."""
        return self.decision_type == GateDecisionType.EXECUTE


class ExecutionGateBridge:
    """Puente y evaluador de gobernanza para ActionIntentContract previo a ejecución."""

    # Umbral canónico de confianza (consistente con ActionPlanner e InteractionPolicy)
    CONFIDENCE_THRESHOLD: float = 0.70

    def __init__(
        self,
        security_manager: SecurityManager | None = None,
        confirmation_manager: ConfirmationManager | None = None,
        security_policy: SecurityPolicy | None = None,
    ) -> None:
        self.security_manager = security_manager or SecurityManager()
        if security_policy is not None:
            self.security_manager.set_policy(security_policy)
        self.confirmation_manager = confirmation_manager or ConfirmationManager(
            security_manager=self.security_manager
        )

    def evaluate_intent(
        self,
        contract: ActionIntentContract,
        user: str = "user",
        ttl_seconds: float = 120.0,
    ) -> ExecutionDecision:
        """Evalúa un ActionIntentContract a través del Execution Gate y políticas de seguridad.

        Determina de forma inmutable y determinista si la acción:
        - Requiere aclaración (CLARIFY).
        - Está bloqueada por seguridad o política (REJECT).
        - Requiere confirmación explícita humana (ASK_CONFIRMATION).
        - Está autorizada para ejecución directa (EXECUTE).

        GARANTÍA: NO ejecuta ninguna acción, skill ni proceso del sistema operativo.
        """
        intent = contract.action_intent
        gate = contract.execution_gate
        spec = contract.execution_spec

        skill_id = spec.skill_id if spec else None
        operation = spec.tool_name if spec else intent.intent_name
        params = intent.parameters or {}
        confidence = intent.confidence

        # 1. Regla de Confianza / Aclaración (CLARIFY)
        if confidence < self.CONFIDENCE_THRESHOLD or gate.needs_clarification or intent.is_ambiguous:
            clarif_text = (
                gate.clarification_prompt
                or f"La confianza en la acción '{intent.intent_name}' es baja ({confidence:.2f}). Por favor aclara lo que deseas realizar."
            )
            return ExecutionDecision(
                decision_type=GateDecisionType.CLARIFY,
                contract=contract,
                reason=f"Aclaración requerida por confianza insuficiente ({confidence:.2f} < {self.CONFIDENCE_THRESHOLD:.2f}) o ambigüedad.",
                action_intent=intent,
                execution_gate=gate,
                execution_spec=spec,
                risk_level=gate.risk_level or "SAFE",
                confidence=confidence,
                skill_id=skill_id,
                operation=operation,
                parameters=params,
                clarification_prompt=clarif_text,
            )

        # 2. Evaluación de Seguridad y Riesgo (SecurityManager / RiskEngine)
        tool_name = operation or intent.intent_name
        category = skill_id.split(".")[0] if skill_id else "general"

        raw_risk = (gate.risk_level or "SAFE").upper()
        try:
            sec_risk = RiskLevel(raw_risk)
        except Exception:
            sec_risk = RiskLevel.SAFE

        profile = ToolSecurityProfile(
            name=tool_name,
            category=category,
            risk_level=sec_risk,
            requires_confirmation=gate.needs_confirmation,
        )

        sec_decision: SecurityDecision = self.security_manager.evaluate(
            profile=profile,
            user=user,
            arguments=params,
            action=operation or "execute",
        )

        # 3. Denegación / Bloqueo por Política o Compuerta Previa (REJECT)
        if not gate.can_execute and not gate.needs_confirmation:
            return ExecutionDecision(
                decision_type=GateDecisionType.REJECT,
                contract=contract,
                reason="Acción denegada explícitamente por la compuerta de ejecución (can_execute=False).",
                action_intent=intent,
                execution_gate=gate,
                execution_spec=spec,
                risk_level=sec_risk.value,
                confidence=confidence,
                skill_id=skill_id,
                operation=operation,
                parameters=params,
            )

        if not sec_decision.is_allowed and not sec_decision.requires_user_confirmation:
            return ExecutionDecision(
                decision_type=GateDecisionType.REJECT,
                contract=contract,
                reason=f"Acción denegada por política de seguridad: {sec_decision.reason}",
                action_intent=intent,
                execution_gate=gate,
                execution_spec=spec,
                risk_level=sec_risk.value,
                confidence=confidence,
                skill_id=skill_id,
                operation=operation,
                parameters=params,
            )

        # 4. Solicitud de Confirmación (ASK_CONFIRMATION)
        must_confirm = (
            gate.needs_confirmation
            or sec_decision.requires_user_confirmation
            or sec_risk in (RiskLevel.DANGEROUS, RiskLevel.CRITICAL)
        )

        if must_confirm:
            confirm_msg = (
                gate.confirmation_prompt
                or f"Detecté una acción sensible: '{tool_name}'. ¿Confirmas su ejecución?"
            )
            # Registrar solicitud estructurada en ConfirmationManager para tracking, expiración y binding
            conf_req = self.confirmation_manager.create_request(
                tool_name=tool_name,
                message=confirm_msg,
                risk_level=sec_risk,
                operation=operation or "execute",
                parameters=params,
                correlation_id=contract.request_id,
                session_id=contract.session_id,
                reason=f"Riesgo: {sec_risk.value}",
                ttl_seconds=ttl_seconds,
            )

            return ExecutionDecision(
                decision_type=GateDecisionType.ASK_CONFIRMATION,
                contract=contract,
                reason=f"La acción requiere confirmación explícita del usuario (Nivel de riesgo: {sec_risk.value}).",
                action_intent=intent,
                execution_gate=gate,
                execution_spec=spec,
                risk_level=sec_risk.value,
                confidence=confidence,
                skill_id=skill_id,
                operation=operation,
                parameters=params,
                confirmation_request=conf_req,
                confirmation_prompt=confirm_msg,
            )

        # 5. Autorización Directa (EXECUTE)
        return ExecutionDecision(
            decision_type=GateDecisionType.EXECUTE,
            contract=contract,
            reason=f"Acción autorizada para ejecución directa (Riesgo: {sec_risk.value}, Confianza: {confidence:.2f}).",
            action_intent=intent,
            execution_gate=gate,
            execution_spec=spec,
            risk_level=sec_risk.value,
            confidence=confidence,
            skill_id=skill_id,
            operation=operation,
            parameters=params,
        )

    def process_confirmation_response(
        self,
        request_id: str,
        user_confirmed: bool,
        target_contract: ActionIntentContract,
    ) -> tuple[ConfirmationBridgeStatus, ExecutionDecision | None]:
        """Procesa la respuesta humana a una confirmación previa vinculada a un ActionIntentContract.

        Valida rigurosamente:
        - Existencia de la solicitud en ConfirmationManager.
        - Expiración de TTL.
        - Scope matching / ActionFingerprint (que corresponda exactamente al target_contract).
        - Prevención de repetición (ALLOW_ONCE / consumo único).

        Retorna:
        - (CONFIRMED, ExecutionDecision[EXECUTE]) si fue aprobada válidamente.
        - (REJECTED, ExecutionDecision[REJECT]) si el usuario la rechazó.
        - (EXPIRED, None) si la solicitud caducó.
        - (INVALID, None) si el request_id no existe, no coincide con el contrato o ya fue consumido.
        """
        pending_req = self.confirmation_manager.get_pending_request(request_id)
        if pending_req is None:
            # Comprobar si existe en resueltas o consumidas para diagnosticar estado
            res = self.confirmation_manager.get_result(request_id)
            if res is not None and getattr(res.status, "value", str(res.status)).upper() == "EXPIRED":
                return ConfirmationBridgeStatus.EXPIRED, None
            return ConfirmationBridgeStatus.INVALID, None

        # 1. Comprobación de expiración de tiempo
        if datetime.now(UTC) >= pending_req.expires_at:
            self.confirmation_manager.submit_request(pending_req)  # marca expiración en manager
            return ConfirmationBridgeStatus.EXPIRED, None

        # 2. Scope Matching y Binding de Fingerprint
        expected_spec = target_contract.execution_spec
        expected_op = expected_spec.tool_name if expected_spec else target_contract.action_intent.intent_name
        expected_tool = expected_op or target_contract.action_intent.intent_name
        expected_params = target_contract.action_intent.parameters or {}

        target_fp = compute_action_fingerprint(
            tool_name=expected_tool,
            operation=expected_op or "execute",
            parameters=expected_params,
        )

        if pending_req.fingerprint != target_fp or pending_req.correlation_id != target_contract.request_id:
            logger.warning(
                f"[GATE_BRIDGE] Binding Mismatch: La confirmación [{request_id}] no coincide con el contrato objetivo "
                f"({pending_req.correlation_id} vs {target_contract.request_id})."
            )
            return ConfirmationBridgeStatus.INVALID, None

        # 3. Caso: Rechazo explícito del usuario
        if not user_confirmed:
            self.confirmation_manager.resolve_request(
                request_id=request_id,
                selected_action=PermissionAction.DENY,
            )
            decision = ExecutionDecision(
                decision_type=GateDecisionType.REJECT,
                contract=target_contract,
                reason="El usuario rechazó explícitamente la ejecución de la acción.",
                action_intent=target_contract.action_intent,
                execution_gate=target_contract.execution_gate,
                execution_spec=target_contract.execution_spec,
                risk_level=str(pending_req.risk_level),
                confidence=target_contract.action_intent.confidence,
                skill_id=expected_spec.skill_id if expected_spec else None,
                operation=expected_op,
                parameters=expected_params,
            )
            return ConfirmationBridgeStatus.REJECTED, decision

        # 4. Caso: Aprobación explícita del usuario -> Resolver y Consumir (ALLOW_ONCE)
        self.confirmation_manager.resolve_request(
            request_id=request_id,
            selected_action=PermissionAction.ALLOW_ONCE,
        )

        consumed = self.confirmation_manager.consume_confirmation(
            request_id=request_id,
            tool_name=expected_tool,
            operation=expected_op or "execute",
            parameters=expected_params,
            session_id=target_contract.session_id,
        )

        if not consumed:
            logger.warning(f"[GATE_BRIDGE] No se pudo consumir la confirmación [{request_id}] (posible replay).")
            return ConfirmationBridgeStatus.INVALID, None

        # Actualizar compuerta a can_execute=True inmutable para la decisión
        approved_gate = target_contract.execution_gate.model_copy(
            update={
                "can_execute": True,
                "needs_confirmation": False,
            }
        )
        approved_contract = target_contract.model_copy(
            update={
                "execution_gate": approved_gate,
            }
        )

        decision = ExecutionDecision(
            decision_type=GateDecisionType.EXECUTE,
            contract=approved_contract,
            reason="Acción autorizada tras confirmación válida del usuario.",
            action_intent=approved_contract.action_intent,
            execution_gate=approved_gate,
            execution_spec=approved_contract.execution_spec,
            risk_level=str(pending_req.risk_level),
            confidence=approved_contract.action_intent.confidence,
            skill_id=expected_spec.skill_id if expected_spec else None,
            operation=expected_op,
            parameters=expected_params,
        )

        return ConfirmationBridgeStatus.CONFIRMED, decision

    def evaluate_gate(
        self,
        contract: ActionIntentContract,
        user_confirmed: bool | None = None,
        user: str = "user",
        ttl_seconds: float = 120.0,
    ) -> ExecutionDecision:
        """Evalúa el contrato ante el Execution Gate, soportando resolución directa de confirmación."""
        intent = contract.action_intent
        gate = contract.execution_gate
        spec = contract.execution_spec

        if user_confirmed is True:
            approved_gate = gate.model_copy(
                update={"can_execute": True, "needs_confirmation": False}
            )
            approved_contract = contract.model_copy(update={"execution_gate": approved_gate})
            return ExecutionDecision(
                decision_type=GateDecisionType.EXECUTE,
                contract=approved_contract,
                reason="Acción autorizada tras confirmación explícita del usuario.",
                action_intent=intent,
                execution_gate=approved_gate,
                execution_spec=spec,
                risk_level=gate.risk_level or "SAFE",
                confidence=intent.confidence,
                skill_id=spec.skill_id if spec else None,
                operation=spec.tool_name if spec else intent.intent_name,
                parameters=intent.parameters or {},
            )
        elif user_confirmed is False:
            rejected_gate = gate.model_copy(
                update={"can_execute": False, "needs_confirmation": False}
            )
            rejected_contract = contract.model_copy(update={"execution_gate": rejected_gate})
            return ExecutionDecision(
                decision_type=GateDecisionType.REJECT,
                contract=rejected_contract,
                reason="El usuario rechazó explícitamente la ejecución de la acción.",
                action_intent=intent,
                execution_gate=rejected_gate,
                execution_spec=spec,
                risk_level=gate.risk_level or "SAFE",
                confidence=intent.confidence,
                skill_id=spec.skill_id if spec else None,
                operation=spec.tool_name if spec else intent.intent_name,
                parameters=intent.parameters or {},
            )
        return self.evaluate_intent(contract, user=user, ttl_seconds=ttl_seconds)


__all__ = [
    "ConfirmationBridgeStatus",
    "ExecutionDecision",
    "ExecutionGateBridge",
    "GateDecisionType",
]
