"""Módulo de Evaluación en Modo Sombra (Shadow Mode) para ORCA + ADE.

Permite procesar solicitudes de manera no invasiva, generando propuestas
teóricas de trabajo agéntico y comparándolas contra las decisiones del JDE.
Garantía estricta: SIDE EFFECTS = 0.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger
from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import (
    OrcaAdeEvaluationResult,
    OrcaAdeMode,
    OrcaAdeProposal,
    ProposalActionType,
)
from core.security import RiskLevel

logger = get_logger("jessyca.orca_ade.shadow")


@dataclass
class ShadowEvaluationRecord:
    """Registro estructurado de telemetría de una evaluación en modo sombra."""

    record_id: str
    request: dict[str, Any]
    orca_proposal: OrcaAdeProposal
    jde_expected_decision: str
    existing_behavior: str
    differences: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    errors: list[str] = field(default_factory=list)
    side_effects: int = 0  # SIEMPRE 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "request": self.request,
            "orca_proposal": self.orca_proposal.to_dict(),
            "jde_expected_decision": self.jde_expected_decision,
            "existing_behavior": self.existing_behavior,
            "differences": self.differences,
            "latency_ms": self.latency_ms,
            "errors": self.errors,
            "side_effects": self.side_effects,
        }


class OrcaAdeShadowEvaluator:
    """Motor de experimentación Shadow para ORCA + ADE."""

    def __init__(self, adapter: OrcaAdeAdapter | None = None) -> None:
        self.adapter = adapter or OrcaAdeAdapter(mode=OrcaAdeMode.SHADOW)
        if self.adapter.mode != OrcaAdeMode.SHADOW:
            self.adapter.set_mode(OrcaAdeMode.SHADOW)
        self._history: list[ShadowEvaluationRecord] = []

    @property
    def history(self) -> list[ShadowEvaluationRecord]:
        return list(self._history)

    def evaluate_shadow_request(
        self,
        request_text: str,
        jde_decision: str = "ALLOW",
        existing_handler_output: str = "Standard JESSYCA Core Response",
        metadata: dict[str, Any] | None = None,
    ) -> ShadowEvaluationRecord:
        """Ejecuta una evaluación en sombra sin efectos colaterales en el sistema."""
        start_time = time.perf_counter()
        meta = metadata or {}

        # Generar propuesta simulada de descomposición agéntica
        action_type = ProposalActionType.CREATE_WORKTREE
        if "test" in request_text.lower():
            action_type = ProposalActionType.RUN_TESTS
        elif "ui" in request_text.lower() or "diseño" in request_text.lower():
            action_type = ProposalActionType.INSPECT_UI
        elif "paralelo" in request_text.lower():
            action_type = ProposalActionType.COORDINATE_SUBTASKS

        proposal = self.adapter.create_proposal(
            capability="worktree_isolation",
            action_type=action_type,
            title=f"Shadow Proposal for: {request_text[:40]}",
            description=request_text,
            estimated_risk=RiskLevel.WARNING if "test" in request_text.lower() else RiskLevel.SAFE,
            metadata=meta,
        )

        eval_res = self.adapter.evaluate_proposal(proposal, jde_decision_override=jde_decision)

        # Analizar diferencias frente al comportamiento nativo existente
        differences: list[str] = []
        if eval_res.status == "ALLOWED" and jde_decision == "ALLOW":
            differences.append("Orca propone aislamiento en worktree paralelo; Core ejecuta secuencialmente.")
        elif eval_res.status == "DENIED":
            differences.append(f"Orca/JDE rechaza la solicitud de forma preventiva: {eval_res.errors}")

        duration = (time.perf_counter() - start_time) * 1000.0

        record = ShadowEvaluationRecord(
            record_id=f"shadow_{len(self._history) + 1:04d}",
            request={"text": request_text, "metadata": meta},
            orca_proposal=proposal,
            jde_expected_decision=jde_decision,
            existing_behavior=existing_handler_output,
            differences=differences,
            latency_ms=duration,
            errors=eval_res.errors,
            side_effects=0,  # Cero efectos físicos
        )

        self._history.append(record)
        return record
