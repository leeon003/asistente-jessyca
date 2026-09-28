"""Módulo de Evaluación en Modo Sombra (Shadow Mode) para AnyDoc.

Genera contratos de propuesta tipados AnyDocProposal, simula la recomendación del JDE
(ALLOW / DENY) y registra telemetría de comparación sin alterar el comportamiento productivo.
Garantía estricta: SIDE EFFECTS = 0.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.anydoc.adapter import AnyDocAdapter
from core.anydoc.models import AnyDocMode, AnyDocProposal, DocumentFormat
from core.logger import get_logger
from core.security import RiskLevel

logger = get_logger("jessyca.anydoc.shadow")


@dataclass
class AnyDocShadowRecord:
    """Registro estructurado de telemetría de una evaluación documental en modo sombra."""

    record_id: str
    request_text: str
    proposal: AnyDocProposal
    jde_simulated_decision: str
    is_safe: bool
    reasons: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    side_effects: int = 0  # SIEMPRE 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "request_text": self.request_text,
            "proposal": self.proposal.to_dict(),
            "jde_simulated_decision": self.jde_simulated_decision,
            "is_safe": self.is_safe,
            "reasons": self.reasons,
            "latency_ms": self.latency_ms,
            "side_effects": self.side_effects,
        }


class AnyDocShadowEvaluator:
    """Evaluador de modo sombra para AnyDoc bajo gobernanza JDE."""

    def __init__(self, adapter: AnyDocAdapter | None = None) -> None:
        self.adapter = adapter or AnyDocAdapter(mode=AnyDocMode.SHADOW)
        if self.adapter.mode != AnyDocMode.SHADOW:
            self.adapter.set_mode(AnyDocMode.SHADOW)
        self._history: list[AnyDocShadowRecord] = []

    @property
    def history(self) -> list[AnyDocShadowRecord]:
        return list(self._history)

    def evaluate_shadow_request(
        self,
        request_text: str,
        input_path: str,
        target_format: str = "auto",
        require_ocr: bool = False,
    ) -> AnyDocShadowRecord:
        """Genera una propuesta y evalúa la recomendación del JDE sin efectos laterales."""
        start_time = time.perf_counter()
        op_id = f"op_sh_{uuid.uuid4().hex[:8]}"
        prop_id = f"prop_sh_{uuid.uuid4().hex[:8]}"
        dec_id = f"dec_sh_{uuid.uuid4().hex[:8]}"

        reasons: list[str] = []
        is_safe = True

        # Clasificación de riesgo de la operación propuesta
        if require_ocr:
            risk = RiskLevel.CRITICAL
            network_req = True
            is_safe = False
            reasons.append("External hosted OCR requires external network and API dispatch (PROHIBITED in Phase 1)")
        elif any(kw in input_path.lower() for kw in ["windows", "system32", "etc", "passwd", ".."]):
            risk = RiskLevel.CRITICAL
            network_req = False
            is_safe = False
            reasons.append("Input path violates security perimeter or contains path traversal")
        else:
            risk = RiskLevel.SAFE
            network_req = False

        # Veredicto simulado del JDE
        jde_decision = "ALLOW" if is_safe else "DENY"

        proposal = AnyDocProposal(
            proposal_id=prop_id,
            decision_id=dec_id,
            operation_id=op_id,
            input_path=input_path,
            format=target_format,
            operation="document_convert_to_markdown",
            risk_level=risk,
            network_required=network_req,
            requires_review=False,
            metadata={"request_text": request_text},
        )

        record = AnyDocShadowRecord(
            record_id=f"rec_{uuid.uuid4().hex[:8]}",
            request_text=request_text,
            proposal=proposal,
            jde_simulated_decision=jde_decision,
            is_safe=is_safe,
            reasons=reasons,
            latency_ms=(time.perf_counter() - start_time) * 1000.0,
            side_effects=0,
        )

        self._history.append(record)
        return record
