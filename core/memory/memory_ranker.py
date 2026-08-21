"""Motor de Ranking Multidimensional para Memoria (memory_ranker.py - Fase 21: Memory Intelligence).

Calcula puntuaciones compuestas considerando:
1. Relevancia Semántica y Léxica
2. Nivel de Confianza Epistémica (VERIFIED > HIGH > MEDIUM > LOW > UNVERIFIED)
3. Autoridad de Procedencia (USER > SYSTEM > TOOL > AGENT > LLM > EXTERNAL)
4. Recencia (Decaimiento temporal exponencial)
5. Frecuencia de Uso (Contador de accesos)
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import ClassVar

from core.memory.memory_entry import MemoryEntry
from core.memory.memory_intelligence_models import RankedMemoryItem
from core.memory.memory_provenance import (
    MemoryConfidence,
    ProvenanceSource,
)


class MemoryRanker:
    """Evaluador y clasificador multidimensional para entradas de memoria."""

    # Ponderaciones por defecto (suman 1.0)
    DEFAULT_WEIGHTS: ClassVar[dict[str, float]] = {
        "relevance": 0.35,
        "confidence": 0.25,
        "provenance": 0.20,
        "recency": 0.10,
        "frequency": 0.10,
    }

    CONFIDENCE_SCORES: ClassVar[dict[MemoryConfidence, float]] = {
        MemoryConfidence.VERIFIED: 1.0,
        MemoryConfidence.HIGH: 0.8,
        MemoryConfidence.MEDIUM: 0.6,
        MemoryConfidence.LOW: 0.4,
        MemoryConfidence.UNVERIFIED: 0.2,
    }

    PROVENANCE_SCORES: ClassVar[dict[ProvenanceSource, float]] = {
        ProvenanceSource.USER: 1.0,
        ProvenanceSource.SYSTEM: 0.95,
        ProvenanceSource.TOOL: 0.80,
        ProvenanceSource.AGENT: 0.70,
        ProvenanceSource.LLM: 0.40,
        ProvenanceSource.EXTERNAL: 0.30,
    }

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        recency_half_life_hours: float = 72.0,
    ) -> None:
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)
        self.recency_half_life_hours = max(1.0, recency_half_life_hours)
        self._decay_lambda = math.log(2) / self.recency_half_life_hours

    def rank_entries(
        self,
        entries_with_similarity: list[tuple[MemoryEntry, float]],
        query_text: str | None = None,
        top_k: int = 5,
        min_score: float | None = None,
    ) -> list[RankedMemoryItem]:
        """Calcula el score compuesto para cada entrada y retorna la lista ordenada descendentemente."""
        ranked_list: list[RankedMemoryItem] = []
        now = datetime.now(UTC)

        for entry, sim in entries_with_similarity:
            # 1. Descartar automáticamente memorias expiradas
            if entry.is_expired:
                continue

            # 2. Calcular scores parciales normalizados [0.0, 1.0]
            s_sem = max(0.0, min(1.0, float(sim)))
            if query_text:
                s_lex = self._compute_lexical_similarity(query_text, f"{entry.key} {entry.content}")
                s_rel = max(s_sem, 0.4 * s_sem + 0.6 * s_lex)
            else:
                s_rel = s_sem

            s_conf = self.CONFIDENCE_SCORES.get(entry.confidence, 0.2)
            s_prov = self.PROVENANCE_SCORES.get(entry.provenance.source, 0.3)
            s_rec = self._compute_recency_score(entry.updated_at, now)
            s_freq = self._compute_frequency_score(entry.access_count)

            # 3. Puntuación ponderada total
            total = (
                self.weights.get("relevance", 0.35) * s_rel
                + self.weights.get("confidence", 0.25) * s_conf
                + self.weights.get("provenance", 0.20) * s_prov
                + self.weights.get("recency", 0.10) * s_rec
                + self.weights.get("frequency", 0.10) * s_freq
            )

            if min_score is not None and total < min_score:
                continue

            item = RankedMemoryItem(
                entry=entry,
                total_score=total,
                relevance_score=s_rel,
                confidence_score=s_conf,
                provenance_score=s_prov,
                recency_score=s_rec,
                frequency_score=s_freq,
            )
            ranked_list.append(item)

        # 4. Ordenar descendentemente por total_score
        ranked_list.sort(key=lambda item: item.total_score, reverse=True)
        return ranked_list[:top_k]

    def _compute_lexical_similarity(self, query: str, text: str) -> float:
        """Calcula el overlap léxico normalizado ignorando palabras vacías."""
        import re

        q_words = set(re.findall(r"\w+", query.lower()))
        t_words = set(re.findall(r"\w+", text.lower()))
        stopwords = {"de", "la", "el", "los", "las", "un", "una", "en", "para", "por", "con", "del", "al"}
        meaningful = {w for w in q_words if len(w) > 2 and w not in stopwords}
        if not meaningful:
            return 0.0
        overlap = meaningful.intersection(t_words)
        return len(overlap) / len(meaningful)

    def _compute_recency_score(self, entry_time: datetime, current_time: datetime) -> float:
        """Calcula el decaimiento temporal exponencial de la memoria."""
        delta = current_time - entry_time
        elapsed_hours = max(0.0, delta.total_seconds() / 3600.0)
        return math.exp(-self._decay_lambda * elapsed_hours)

    def _compute_frequency_score(self, access_count: int) -> float:
        """Normaliza la frecuencia de acceso acotada logarítmicamente entre 0.0 y 1.0."""
        count = max(0, access_count)
        if count == 0:
            return 0.1
        # log(1 + count) normalizado con base en 20 accesos como 1.0
        return min(1.0, math.log(1.0 + count) / math.log(1.0 + 20.0))
