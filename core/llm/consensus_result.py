"""Modelos de datos para el motor de consenso Multi-LLM (consensus_result.py - Fase 10: Multi-LLM Consensus Engine).

Define estructuras inmutables para representar los votos individuales de cada modelo y la decisión consolidada final.
INVARIANTE DE SEGURIDAD:
- ConsensusResult representa datos NO CONFIABLES del LLM (Untrusted Data).
- El consenso NO es autorización y NO puede alterar políticas de seguridad.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ConsensusStatus(StrEnum):
    """Estado formal del proceso de consenso entre múltiples modelos."""

    UNANIMOUS = "UNANIMOUS"
    MAJORITY = "MAJORITY"
    DISAGREEMENT = "DISAGREEMENT"
    INSUFFICIENT_RESPONSES = "INSUFFICIENT_RESPONSES"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ModelVote:
    """Voto o análisis individual estructurado producido por un modelo LLM."""

    model_id: str
    decision: str
    answer: str
    confidence: float = 1.0
    reasoning: str = ""
    latency_seconds: float = 0.0
    is_valid: bool = True
    error: str | None = None
    raw_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "decision": self.decision,
            "answer": self.answer,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "latency_seconds": self.latency_seconds,
            "is_valid": self.is_valid,
            "error": self.error,
        }


@dataclass(frozen=True)
class ConsensusResult:
    """Resultado formal consolidado emitido por el ConsensusEngine."""

    task: str
    status: ConsensusStatus
    final_decision: str | None
    final_answer: str
    agreement_ratio: float
    confidence_score: float
    participating_models: tuple[str, ...]
    votes: tuple[ModelVote, ...]
    divergence_notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_consensus_reached(self) -> bool:
        """Indica si se alcanzó un consenso válido (Unánime o Mayoría)."""
        return self.status in (ConsensusStatus.UNANIMOUS, ConsensusStatus.MAJORITY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "status": str(self.status),
            "final_decision": self.final_decision,
            "final_answer": self.final_answer,
            "agreement_ratio": self.agreement_ratio,
            "confidence_score": self.confidence_score,
            "participating_models": list(self.participating_models),
            "votes": [v.to_dict() for v in self.votes],
            "divergence_notes": self.divergence_notes,
            "metadata": dict(self.metadata),
        }
