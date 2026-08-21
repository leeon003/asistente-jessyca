"""Políticas de agregación y resolución de consenso Multi-LLM (consensus_policy.py - Fase 10).

Define las estrategias y umbrales matemáticos para consolidar votos independientes de múltiples modelos.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

from core.llm.consensus_result import ConsensusResult, ConsensusStatus, ModelVote


class ConsensusStrategy(StrEnum):
    """Estrategias de resolución de consenso."""

    MAJORITY_VOTE = "MAJORITY_VOTE"
    UNANIMOUS_REQUIRED = "UNANIMOUS_REQUIRED"
    WEIGHTED_CONFIDENCE = "WEIGHTED_CONFIDENCE"


@dataclass(frozen=True)
class ConsensusPolicy:
    """Configuración inmutable de la política de evaluación de consenso."""

    min_participating_models: int = 2
    min_agreement_threshold: float = 0.51
    strategy: ConsensusStrategy = ConsensusStrategy.MAJORITY_VOTE
    model_weights: dict[str, float] = field(
        default_factory=lambda: {
            "qwen3:8b": 1.2,
            "gemma4:e4b": 1.0,
            "llama3.1:latest": 1.0,
            "llama3.2:latest": 0.9,
        }
    )

    def evaluate_votes(self, votes: list[ModelVote], task: str) -> ConsensusResult:
        """Evalúa determinísticamente la lista de votos producidos por los modelos."""
        valid_votes = [v for v in votes if v.is_valid and not v.error]
        participating_models = tuple(v.model_id for v in votes)

        # 1. Comprobar quórum mínimo de respuestas válidas
        if len(valid_votes) < self.min_participating_models:
            return ConsensusResult(
                task=task,
                status=ConsensusStatus.INSUFFICIENT_RESPONSES,
                final_decision=None,
                final_answer="No se alcanzaron suficientes respuestas válidas de los modelos convocados.",
                agreement_ratio=0.0,
                confidence_score=0.0,
                participating_models=participating_models,
                votes=tuple(votes),
                divergence_notes=f"Solo {len(valid_votes)} modelo(s) respondieron válidamente (mínimo requerido: {self.min_participating_models}).",
            )

        # 2. Agrupar decisiones normalizadas
        decision_counts = Counter(v.decision.strip().lower() for v in valid_votes)
        total_valid = len(valid_votes)

        # 3. Evaluar Unanimidad
        if len(decision_counts) == 1:
            winning_decision_key = next(iter(decision_counts.keys()))
            matching_votes = [v for v in valid_votes if v.decision.strip().lower() == winning_decision_key]
            avg_confidence = sum(v.confidence for v in matching_votes) / len(matching_votes)

            return ConsensusResult(
                task=task,
                status=ConsensusStatus.UNANIMOUS,
                final_decision=matching_votes[0].decision,
                final_answer=matching_votes[0].answer,
                agreement_ratio=1.0,
                confidence_score=avg_confidence,
                participating_models=participating_models,
                votes=tuple(votes),
                divergence_notes=None,
            )

        # Si se exige unanimidad estricta y hubo divergencia
        if self.strategy == ConsensusStrategy.UNANIMOUS_REQUIRED:
            return ConsensusResult(
                task=task,
                status=ConsensusStatus.DISAGREEMENT,
                final_decision=None,
                final_answer="Desacuerdo entre modelos bajo política de unanimidad estricta.",
                agreement_ratio=decision_counts.most_common(1)[0][1] / total_valid,
                confidence_score=0.0,
                participating_models=participating_models,
                votes=tuple(votes),
                divergence_notes=f"Divergencia detectada entre decisiones: {dict(decision_counts)}",
            )

        # 4. Estrategia Ponderada o Mayoría Simple
        if self.strategy == ConsensusStrategy.WEIGHTED_CONFIDENCE:
            weighted_scores: dict[str, float] = {}
            for v in valid_votes:
                key = v.decision.strip().lower()
                weight = self.model_weights.get(v.model_id, 1.0)
                score = v.confidence * weight
                weighted_scores[key] = weighted_scores.get(key, 0.0) + score

            sorted_scores = sorted(weighted_scores.items(), key=lambda x: x[1], reverse=True)
            top_decision_key, top_score = sorted_scores[0]
            second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

            if top_score == second_score:
                return ConsensusResult(
                    task=task,
                    status=ConsensusStatus.DISAGREEMENT,
                    final_decision=None,
                    final_answer="Empate ponderado exacto entre múltiples modelos sin decisión concluyente.",
                    agreement_ratio=0.5,
                    confidence_score=0.5,
                    participating_models=participating_models,
                    votes=tuple(votes),
                    divergence_notes=f"Empate de puntajes: {weighted_scores}",
                )

            winning_votes = [v for v in valid_votes if v.decision.strip().lower() == top_decision_key]
            agreement_ratio = len(winning_votes) / total_valid
            avg_conf = sum(v.confidence for v in winning_votes) / len(winning_votes)

            return ConsensusResult(
                task=task,
                status=ConsensusStatus.MAJORITY,
                final_decision=winning_votes[0].decision,
                final_answer=winning_votes[0].answer,
                agreement_ratio=agreement_ratio,
                confidence_score=avg_conf,
                participating_models=participating_models,
                votes=tuple(votes),
                divergence_notes=f"Consenso por mayoría ponderada ({len(winning_votes)}/{total_valid}).",
            )

        # Mayoría por conteo de votos
        most_common = decision_counts.most_common()
        top_decision_key, top_count = most_common[0]
        second_count = most_common[1][1] if len(most_common) > 1 else 0
        agreement_ratio = top_count / total_valid

        if top_count == second_count or agreement_ratio < self.min_agreement_threshold:
            return ConsensusResult(
                task=task,
                status=ConsensusStatus.DISAGREEMENT,
                final_decision=None,
                final_answer="Desacuerdo: Ninguna decisión alcanzó el umbral mínimo de mayoría requerida.",
                agreement_ratio=agreement_ratio,
                confidence_score=0.0,
                participating_models=participating_models,
                votes=tuple(votes),
                divergence_notes=f"Distribución de votos: {dict(decision_counts)} (ratio máximo: {agreement_ratio:.2f} < {self.min_agreement_threshold:.2f})",
            )

        winning_votes = [v for v in valid_votes if v.decision.strip().lower() == top_decision_key]
        avg_conf = sum(v.confidence for v in winning_votes) / len(winning_votes)

        return ConsensusResult(
            task=task,
            status=ConsensusStatus.MAJORITY,
            final_decision=winning_votes[0].decision,
            final_answer=winning_votes[0].answer,
            agreement_ratio=agreement_ratio,
            confidence_score=avg_conf,
            participating_models=participating_models,
            votes=tuple(votes),
            divergence_notes=f"Mayoría alcanzada ({top_count}/{total_valid} modelos a favor).",
        )
