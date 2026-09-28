"""Módulo de Promoción y Democión de Capacidades para JDE - Fase 7 (PROGRESSIVE).

Define los contratos y políticas formales para la evaluación de evidencia,
promoción explícita individual y reversión (democión) de capacidades:
    LIMITED -> PROGRESSIVE
    PROGRESSIVE -> LIMITED

REGLAS DE FASE 7:
1. PROGRESSIVE no es global: la autoridad se evalúa por CAPABILITY individual.
2. La promoción exige evidencia objetiva comprobada (mínimo 3 ejecuciones independientes verificadas).
3. UNKNOWN, FALSE_SUCCESS, DOUBLE_EXECUTION o violaciones de política bloquean incondicionalmente la promoción.
4. Las capacidades HIGH risk quedan incondicionalmente excluidas de PROGRESSIVE.
5. El LLM no puede otorgarse autoridad, modificar métricas ni aprobar su propia promoción.
6. La promoción genera un CapabilityPromotionReceipt inmutable con fingerprint criptográfico SHA-256.
7. Si una capacidad promovida presenta fallos críticos (UNKNOWN, false success, doble ejecución),
   se activa democión segura e inmediata: PROGRESSIVE -> LIMITED.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.jde.authority import ActionRiskTier, AuthorityMode, get_authority_gate
from core.jde.capabilities import Capability, get_capability_registry
from core.jde.states import DecisionState
from core.logger import get_logger

logger = get_logger("jessyca.jde.promotion")


class PromotionDecision(StrEnum):
    """Decisiones formales del motor de promoción de capacidades."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_REVIEW = "REQUIRE_REVIEW"


class PromotionStatus(StrEnum):
    """Estado del ciclo de vida de promoción de una capacidad."""

    NOT_PROMOTED = "NOT_PROMOTED"
    ELIGIBLE = "ELIGIBLE"
    PROMOTED = "PROMOTED"
    DEMOTED = "DEMOTED"


def compute_promotion_fingerprint(
    promotion_id: str,
    capability_id: str,
    previous_authority: str,
    requested_authority: str,
    risk_tier: str,
    evidence_count: int,
    verified_successes: int,
    unknown_count: int,
    false_success_count: int,
    double_execution_count: int,
    policy_violations: int,
    decision: str,
    reason: str,
    timestamp: datetime | str,
) -> str:
    """Calcula el hash SHA-256 canónico e inmutable del recibo de promoción."""
    payload = {
        "promotion_id": promotion_id.strip(),
        "capability_id": capability_id.strip().lower(),
        "previous_authority": previous_authority.strip().upper(),
        "requested_authority": requested_authority.strip().upper(),
        "risk_tier": risk_tier.strip().upper(),
        "evidence_count": evidence_count,
        "verified_successes": verified_successes,
        "unknown_count": unknown_count,
        "false_success_count": false_success_count,
        "double_execution_count": double_execution_count,
        "policy_violations": policy_violations,
        "decision": decision.strip().upper(),
        "reason": reason.strip(),
        "timestamp": str(timestamp),
    }
    canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class CapabilityPromotionReceipt(BaseModel):
    """Recibo formal inmutable generado tras una decisión de promoción o democión."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    promotion_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    capability_id: str
    previous_authority: str
    requested_authority: str
    risk_tier: str
    evidence_count: int
    verified_successes: int
    unknown_count: int
    false_success_count: int
    double_execution_count: int
    policy_violations: int
    decision: PromotionDecision
    reason: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    fingerprint: str = ""

    @classmethod
    def create(
        cls,
        capability_id: str,
        previous_authority: str,
        requested_authority: str,
        risk_tier: str,
        evidence_count: int,
        verified_successes: int,
        unknown_count: int,
        false_success_count: int,
        double_execution_count: int,
        policy_violations: int,
        decision: PromotionDecision,
        reason: str,
        promotion_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> CapabilityPromotionReceipt:
        pid = promotion_id or str(uuid.uuid4())
        ts = timestamp or datetime.now(UTC)
        fp = compute_promotion_fingerprint(
            promotion_id=pid,
            capability_id=capability_id,
            previous_authority=previous_authority,
            requested_authority=requested_authority,
            risk_tier=risk_tier,
            evidence_count=evidence_count,
            verified_successes=verified_successes,
            unknown_count=unknown_count,
            false_success_count=false_success_count,
            double_execution_count=double_execution_count,
            policy_violations=policy_violations,
            decision=decision.value,
            reason=reason,
            timestamp=ts,
        )
        return cls(
            promotion_id=pid,
            capability_id=capability_id,
            previous_authority=previous_authority,
            requested_authority=requested_authority,
            risk_tier=risk_tier,
            evidence_count=evidence_count,
            verified_successes=verified_successes,
            unknown_count=unknown_count,
            false_success_count=false_success_count,
            double_execution_count=double_execution_count,
            policy_violations=policy_violations,
            decision=decision,
            reason=reason,
            timestamp=ts,
            fingerprint=fp,
        )

    def verify_integrity(self) -> bool:
        """Comprueba que los datos del recibo no hayan sido alterados."""
        recalculated = compute_promotion_fingerprint(
            promotion_id=self.promotion_id,
            capability_id=self.capability_id,
            previous_authority=self.previous_authority,
            requested_authority=self.requested_authority,
            risk_tier=self.risk_tier,
            evidence_count=self.evidence_count,
            verified_successes=self.verified_successes,
            unknown_count=self.unknown_count,
            false_success_count=self.false_success_count,
            double_execution_count=self.double_execution_count,
            policy_violations=self.policy_violations,
            decision=self.decision.value,
            reason=self.reason,
            timestamp=self.timestamp,
        )
        return self.fingerprint == recalculated


class CapabilityEvaluationRecord(BaseModel):
    """Registro histórico de ejecuciones, evidencias e incidentes para una capacidad."""

    capability_id: str
    verified_successes: int = 0
    failed_executions: int = 0
    unknown_executions: int = 0
    false_success_count: int = 0
    double_execution_count: int = 0
    policy_violations: int = 0
    verified_request_ids: set[str] = Field(default_factory=set)
    total_executions: int = 0
    last_evidence: dict[str, Any] = Field(default_factory=dict)
    promotion_status: PromotionStatus = PromotionStatus.NOT_PROMOTED


class CapabilityPromotionPolicy:
    """Política canónica para determinar la elegibilidad y decisión de promoción."""

    def __init__(self, threshold_verified_successes: int = 3) -> None:
        self.threshold_verified_successes = threshold_verified_successes

    def evaluate_eligibility(
        self,
        cap: Capability,
        record: CapabilityEvaluationRecord,
    ) -> tuple[bool, str]:
        """Evalúa objetivamente si una capacidad cumple los requisitos para ser promovida a PROGRESSIVE."""
        if cap.is_high_risk:
            return False, f"Capacidad '{cap.capability_id}' es de riesgo HIGH; excluida incondicionalmente de PROGRESSIVE."

        if not cap.enabled:
            return False, f"Capacidad '{cap.capability_id}' está deshabilitada en el registro."

        if record.false_success_count > 0:
            return False, f"Capacidad '{cap.capability_id}' presenta {record.false_success_count} falsos éxitos (bloqueo estricto)."

        if record.double_execution_count > 0:
            return False, f"Capacidad '{cap.capability_id}' presenta {record.double_execution_count} dobles ejecuciones (bloqueo estricto)."

        if record.policy_violations > 0:
            return False, f"Capacidad '{cap.capability_id}' presenta {record.policy_violations} violaciones de política."

        if record.unknown_executions > 0:
            return False, f"Capacidad '{cap.capability_id}' presenta {record.unknown_executions} ejecuciones UNKNOWN (bloqueo estricto)."

        unique_verified_count = len(record.verified_request_ids)
        if unique_verified_count < self.threshold_verified_successes:
            return (
                False,
                f"Evidencia insuficiente de éxitos independientes verificados: {unique_verified_count} < {self.threshold_verified_successes}.",
            )

        # Reglas más estrictas para capacidades MEDIUM
        if cap.risk_tier == ActionRiskTier.MEDIUM:
            if cap.external_side_effect:
                return False, f"Capacidad MEDIUM '{cap.capability_id}' posee efectos externos; no promovible en Fase 7."
            if not cap.reversible:
                return False, f"Capacidad MEDIUM '{cap.capability_id}' no es reversible; requiere retención en LIMITED."
            if cap.destructive:
                return False, f"Capacidad MEDIUM '{cap.capability_id}' es destructiva; excluida de PROGRESSIVE."
            if not cap.requires_verification:
                return False, f"Capacidad MEDIUM '{cap.capability_id}' no exige verificación física."

        return True, f"Capacidad '{cap.capability_id}' cumple todos los criterios objetivos para promoción."

    def evaluate_demotion_condition(
        self,
        record: CapabilityEvaluationRecord,
        incident_type: str = "",
    ) -> tuple[bool, str]:
        """Determina si una capacidad promovida a PROGRESSIVE debe ser revertida a LIMITED."""
        if record.false_success_count > 0:
            return True, f"Falso éxito detectado en capacidad '{record.capability_id}'."
        if record.double_execution_count > 0:
            return True, f"Doble ejecución detectada en capacidad '{record.capability_id}'."
        if record.policy_violations > 0:
            return True, f"Violación de política detectada en capacidad '{record.capability_id}'."
        if record.unknown_executions > 0:
            return True, f"Ejecución UNKNOWN detectada en capacidad '{record.capability_id}'."
        if incident_type == "INTEGRITY_FAILURE":
            return True, f"Fallo de integridad criptográfica en recibos de '{record.capability_id}'."
        return False, ""


class CapabilityPromotionManager:
    """Coordinador central de evaluación, evidencia, promoción y democión de capacidades."""

    def __init__(self, policy: CapabilityPromotionPolicy | None = None) -> None:
        self._lock = threading.RLock()
        self.policy = policy or CapabilityPromotionPolicy()
        self._records: dict[str, CapabilityEvaluationRecord] = {}
        self._receipts: list[CapabilityPromotionReceipt] = []

    def get_record(self, capability_id: str) -> CapabilityEvaluationRecord:
        """Obtiene o inicializa el registro histórico de una capacidad."""
        with self._lock:
            if capability_id not in self._records:
                self._records[capability_id] = CapabilityEvaluationRecord(capability_id=capability_id)
            return self._records[capability_id]

    def record_execution(
        self,
        capability_id: str,
        request_id: str,
        final_status: DecisionState,
        is_verified: bool = False,
        execution_count: int = 1,
        is_policy_violation: bool = False,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        """Registra un evento de ejecución para construir evidencia auditable."""
        with self._lock:
            rec = self.get_record(capability_id)
            rec.total_executions += 1
            if evidence:
                rec.last_evidence = evidence

            if execution_count > 1:
                rec.double_execution_count += 1

            if is_policy_violation:
                rec.policy_violations += 1

            if final_status == DecisionState.SUCCESS:
                if is_verified:
                    rec.verified_successes += 1
                    rec.verified_request_ids.add(request_id)
                else:
                    rec.false_success_count += 1
            elif final_status == DecisionState.UNKNOWN:
                rec.unknown_executions += 1
            elif final_status == DecisionState.FAILED:
                rec.failed_executions += 1

            # Comprobar si la capacidad está actualmente promovida y si amerita democión inmediata
            reg = get_capability_registry()
            cap = reg.get(capability_id)
            if cap and cap.promoted_to_progressive:
                should_demote, demote_reason = self.policy.evaluate_demotion_condition(rec)
                if should_demote:
                    logger.warning(
                        f"[JDE PROMOTION ALERT] Activando democión automática de '{capability_id}': {demote_reason}"
                    )
                    self.demote(capability_id=capability_id, reason=demote_reason)

    def check_eligibility(self, capability_id: str) -> tuple[bool, str]:
        """Comprueba si una capacidad califica para ser promovida a PROGRESSIVE."""
        with self._lock:
            reg = get_capability_registry()
            cap = reg.get(capability_id)
            if not cap:
                return False, f"Capacidad '{capability_id}' no existe en CapabilityRegistry."
            rec = self.get_record(capability_id)
            eligible, reason = self.policy.evaluate_eligibility(cap, rec)
            if eligible:
                rec.promotion_status = PromotionStatus.ELIGIBLE
            return eligible, reason

    def promote(
        self,
        capability_id: str,
        target_authority: AuthorityMode = AuthorityMode.PROGRESSIVE,
        approved_by_policy: bool = False,
        caller: str = "",
    ) -> tuple[bool, CapabilityPromotionReceipt]:
        """Ejecuta la promoción formal individual de una capacidad."""
        with self._lock:
            gate = get_authority_gate()
            gate.metrics.record_promotion("REQUEST")

            # 1. Validación de Actor: El LLM nunca puede promoverse a sí mismo
            caller_norm = caller.strip().lower()
            if any(forbidden in caller_norm for forbidden in ("llm", "assistant", "model", "prompt", "user_agent")):
                reason = f"El actor '{caller}' (LLM/Agente) no tiene permiso para autorizar su propia promoción."
                gate.metrics.record_promotion("DENY")
                receipt = CapabilityPromotionReceipt.create(
                    capability_id=capability_id,
                    previous_authority=AuthorityMode.LIMITED.value,
                    requested_authority=target_authority.value,
                    risk_tier=ActionRiskTier.HIGH.value,
                    evidence_count=0,
                    verified_successes=0,
                    unknown_count=0,
                    false_success_count=0,
                    double_execution_count=0,
                    policy_violations=1,
                    decision=PromotionDecision.DENY,
                    reason=reason,
                )
                self._receipts.append(receipt)
                return False, receipt

            reg = get_capability_registry()
            cap = reg.get(capability_id)
            if not cap:
                reason = f"Capacidad '{capability_id}' inexistente en el catálogo."
                gate.metrics.record_promotion("DENY")
                receipt = CapabilityPromotionReceipt.create(
                    capability_id=capability_id,
                    previous_authority=AuthorityMode.LIMITED.value,
                    requested_authority=target_authority.value,
                    risk_tier=ActionRiskTier.LOW.value,
                    evidence_count=0,
                    verified_successes=0,
                    unknown_count=0,
                    false_success_count=0,
                    double_execution_count=0,
                    policy_violations=0,
                    decision=PromotionDecision.DENY,
                    reason=reason,
                )
                self._receipts.append(receipt)
                return False, receipt

            rec = self.get_record(capability_id)

            # 2. Exigir decisión formal de política: La elegibilidad por sí sola no promueve automáticamente
            if not approved_by_policy:
                reason = f"Capacidad '{capability_id}' requiere decisión y aprobación explícita de política administrativa."
                gate.metrics.record_promotion("REQUIRE_REVIEW")
                receipt = CapabilityPromotionReceipt.create(
                    capability_id=capability_id,
                    previous_authority=cap.authority_level.value,
                    requested_authority=target_authority.value,
                    risk_tier=cap.risk_tier.value,
                    evidence_count=rec.total_executions,
                    verified_successes=len(rec.verified_request_ids),
                    unknown_count=rec.unknown_executions,
                    false_success_count=rec.false_success_count,
                    double_execution_count=rec.double_execution_count,
                    policy_violations=rec.policy_violations,
                    decision=PromotionDecision.REQUIRE_REVIEW,
                    reason=reason,
                )
                self._receipts.append(receipt)
                return False, receipt

            # 3. Comprobar criterios objetivos de elegibilidad
            eligible, reason = self.policy.evaluate_eligibility(cap, rec)
            if not eligible:
                gate.metrics.record_promotion("DENY")
                receipt = CapabilityPromotionReceipt.create(
                    capability_id=capability_id,
                    previous_authority=cap.authority_level.value,
                    requested_authority=target_authority.value,
                    risk_tier=cap.risk_tier.value,
                    evidence_count=rec.total_executions,
                    verified_successes=len(rec.verified_request_ids),
                    unknown_count=rec.unknown_executions,
                    false_success_count=rec.false_success_count,
                    double_execution_count=rec.double_execution_count,
                    policy_violations=rec.policy_violations,
                    decision=PromotionDecision.DENY,
                    reason=reason,
                )
                self._receipts.append(receipt)
                return False, receipt

            # 4. Promoción aprobada: elevar capacidad en el CapabilityRegistry
            success = reg.promote_capability(capability_id, target_authority)
            if not success:
                reason = f"Fallo al actualizar el registro de capacidades para '{capability_id}'."
                gate.metrics.record_promotion("DENY")
                receipt = CapabilityPromotionReceipt.create(
                    capability_id=capability_id,
                    previous_authority=cap.authority_level.value,
                    requested_authority=target_authority.value,
                    risk_tier=cap.risk_tier.value,
                    evidence_count=rec.total_executions,
                    verified_successes=len(rec.verified_request_ids),
                    unknown_count=rec.unknown_executions,
                    false_success_count=rec.false_success_count,
                    double_execution_count=rec.double_execution_count,
                    policy_violations=rec.policy_violations,
                    decision=PromotionDecision.DENY,
                    reason=reason,
                )
                self._receipts.append(receipt)
                return False, receipt

            rec.promotion_status = PromotionStatus.PROMOTED
            gate.metrics.record_promotion("ALLOW")

            receipt = CapabilityPromotionReceipt.create(
                capability_id=capability_id,
                previous_authority=cap.authority_level.value,
                requested_authority=target_authority.value,
                risk_tier=cap.risk_tier.value,
                evidence_count=rec.total_executions,
                verified_successes=len(rec.verified_request_ids),
                unknown_count=rec.unknown_executions,
                false_success_count=rec.false_success_count,
                double_execution_count=rec.double_execution_count,
                policy_violations=rec.policy_violations,
                decision=PromotionDecision.ALLOW,
                reason=f"Capacidad '{capability_id}' promovida exitosamente a {target_authority.value}.",
            )
            self._receipts.append(receipt)
            logger.info(f"[JDE PROMOTION] Capacidad '{capability_id}' promovida a {target_authority.value}.")
            return True, receipt

    def demote(
        self,
        capability_id: str,
        target_authority: AuthorityMode = AuthorityMode.LIMITED,
        reason: str = "",
    ) -> tuple[bool, CapabilityPromotionReceipt]:
        """Revierte una capacidad promovida a un nivel seguro (LIMITED). Fail-Safe."""
        with self._lock:
            gate = get_authority_gate()
            gate.metrics.record_demotion()

            reg = get_capability_registry()
            cap = reg.get(capability_id)
            rec = self.get_record(capability_id)

            prev_auth = AuthorityMode.PROGRESSIVE.value if (cap and cap.promoted_to_progressive) else AuthorityMode.LIMITED.value
            risk_val = cap.risk_tier.value if cap else ActionRiskTier.LOW.value

            reg.demote_capability(capability_id, target_authority)
            rec.promotion_status = PromotionStatus.DEMOTED

            demote_reason = reason or f"Democión preventiva de '{capability_id}' a {target_authority.value}."
            receipt = CapabilityPromotionReceipt.create(
                capability_id=capability_id,
                previous_authority=prev_auth,
                requested_authority=target_authority.value,
                risk_tier=risk_val,
                evidence_count=rec.total_executions,
                verified_successes=len(rec.verified_request_ids),
                unknown_count=rec.unknown_executions,
                false_success_count=rec.false_success_count,
                double_execution_count=rec.double_execution_count,
                policy_violations=rec.policy_violations,
                decision=PromotionDecision.DENY,
                reason=demote_reason,
            )
            self._receipts.append(receipt)
            logger.info(f"[JDE DEMOTION] Capacidad '{capability_id}' revertida a {target_authority.value}: {demote_reason}")
            return True, receipt

    def list_receipts(self) -> list[CapabilityPromotionReceipt]:
        """Retorna copia de todos los recibos de promoción/democión emitidos."""
        with self._lock:
            return list(self._receipts)


_GLOBAL_PROMOTION_MANAGER: CapabilityPromotionManager | None = None
_PROMOTION_LOCK = threading.Lock()


def get_promotion_manager() -> CapabilityPromotionManager:
    """Retorna la instancia global singleton de CapabilityPromotionManager."""
    global _GLOBAL_PROMOTION_MANAGER
    with _PROMOTION_LOCK:
        if _GLOBAL_PROMOTION_MANAGER is None:
            _GLOBAL_PROMOTION_MANAGER = CapabilityPromotionManager()
        return _GLOBAL_PROMOTION_MANAGER


def reset_promotion_manager() -> CapabilityPromotionManager:
    """Reinicia la instancia global de CapabilityPromotionManager (útil para tests)."""
    global _GLOBAL_PROMOTION_MANAGER
    with _PROMOTION_LOCK:
        _GLOBAL_PROMOTION_MANAGER = CapabilityPromotionManager()
        return _GLOBAL_PROMOTION_MANAGER
