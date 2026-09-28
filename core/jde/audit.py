"""Audit Trail & Trazabilidad de Decisiones para JESSYCA Decision Engine (JDE).

Garantiza la reconstrucción forense completa de cada decisión:
1. Qué pidió el usuario.
2. Qué interpretó el Agent / LLM.
3. Qué decidió JDE.
4. Qué policy se aplicó.
5. Qué herramienta se ejecutó.
6. Qué parámetros recibió.
7. Qué devolvió el executor.
8. Qué verificó el sistema.
9. Qué evidencia obtuvo.
10. Por qué se declaró SUCCESS/FAILED/UNKNOWN/BLOCKED.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.jde.models import DecisionRequest, DecisionResult
from core.jde.receipts import ActionReceipt
from core.logger import get_logger

logger = get_logger("jessyca.jde.audit")


class JDEAuditRecord(BaseModel):
    """Registro inmutable de auditoría forense para una decisión de JDE."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    user_prompt: str
    interpreted_intent: str
    agent_confidence: float
    jde_state: str
    policy_verdict: str
    tool_executed: str
    parameters_passed: dict[str, Any] = Field(default_factory=dict)
    executor_output_status: str
    verifier_strategy: str
    verifier_outcome_status: str
    evidence_collected: list[dict[str, Any]] = Field(default_factory=list)
    final_verdict_reason: str
    receipt_fingerprint: str | None = None
    duration_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_readable_summary(self) -> str:
        """Genera un resumen legible de los 10 puntos forenses obligatorios."""
        return (
            f"[JDE AUDIT TRAIL] Request: {self.request_id}\n"
            f"  1. Usuario pidió: '{self.user_prompt}'\n"
            f"  2. Intención interpretada: {self.interpreted_intent} (Confianza: {self.agent_confidence:.2f})\n"
            f"  3. Decisión JDE: {self.jde_state}\n"
            f"  4. Política aplicada: {self.policy_verdict}\n"
            f"  5. Herramienta ejecutada: {self.tool_executed}\n"
            f"  6. Parámetros: {json.dumps(self.parameters_passed, default=str)}\n"
            f"  7. Retorno ejecutor: {self.executor_output_status}\n"
            f"  8. Verificación: {self.verifier_strategy} -> {self.verifier_outcome_status}\n"
            f"  9. Evidencias: {len(self.evidence_collected)} registros colectados\n"
            f" 10. Veredicto final: {self.final_verdict_reason} (Fingerprint: {self.receipt_fingerprint})"
        )


class JDEAuditTrail:
    """Gestor del rastro de auditoría para JDE. Conecta con el sistema de audit logging central."""

    def __init__(self, system_audit_logger: Any | None = None) -> None:
        self._system_audit_logger = system_audit_logger
        self._in_memory_records: list[JDEAuditRecord] = []

    def record_decision(
        self,
        request: DecisionRequest,
        result: DecisionResult,
        receipt: ActionReceipt | None = None,
    ) -> JDEAuditRecord:
        """Registra formalmente una decisión completada."""
        ev_dicts = [e.model_dump() for e in receipt.evidence] if receipt else []
        record = JDEAuditRecord(
            request_id=request.request_id,
            user_prompt=request.user_request,
            interpreted_intent=request.intent,
            agent_confidence=request.confidence,
            jde_state=result.state.value,
            policy_verdict=receipt.policy_verdict if receipt else "UNKNOWN",
            tool_executed=result.tool_used or request.tool,
            parameters_passed=request.parameters,
            executor_output_status=result.executor_status.value,
            verifier_strategy=receipt.verifier if receipt else "NONE",
            verifier_outcome_status=result.verification_status.value,
            evidence_collected=ev_dicts,
            final_verdict_reason=result.message,
            receipt_fingerprint=receipt.fingerprint if receipt else None,
            duration_ms=result.duration_ms,
        )

        self._in_memory_records.append(record)
        logger.info(record.to_readable_summary())

        # Integración con core.audit_logger si está disponible
        if self._system_audit_logger is not None:
            try:
                from core.audit_logger import AuditEvent, AuditEventType
                self._system_audit_logger.log_audit_event(
                    AuditEvent(
                        event_type=AuditEventType.EXECUTION_VERIFIED if result.success else AuditEventType.EXECUTION_FAILED,
                        request_id=request.request_id,
                        user="user",
                        tool_name=record.tool_executed,
                        operation=request.proposed_action,
                        parameters=request.parameters,
                        metadata={
                            "jde_state": result.state.value,
                            "receipt_fingerprint": record.receipt_fingerprint,
                            "is_verified": result.claims_success,
                        },
                    )
                )
            except Exception as e:
                logger.debug(f"[JDE AUDIT] Error al propagar evento a AuditLogger: {e}")

        return record

    def get_records(self, request_id: str | None = None) -> list[JDEAuditRecord]:
        """Recupera registros de auditoría filtrados opcionalmente por request_id."""
        if request_id:
            return [r for r in self._in_memory_records if r.request_id == request_id]
        return list(self._in_memory_records)
