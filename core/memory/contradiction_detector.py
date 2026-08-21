"""Detector y Evaluador de Contradicciones en Memoria (contradiction_detector.py - Fase 21: Memory Intelligence).

Identifica inconsistencias lógicas, discrepancias de atributos y conflictos de preferencias entre recuerdos.

INVARIANTE DE SEGURIDAD EPISTÉMICA:
1. Una inferencia de LLM (UNVERIFIED) NUNCA puede sobrescribir una verdad confirmada por el usuario (USER / VERIFIED).
2. Contradicciones importantes entre entradas del usuario no se resuelven en silencio; se marcan como REQUIRES_USER_CLARIFICATION.
"""

from __future__ import annotations

import re
from typing import ClassVar

from core.logger import get_logger
from core.memory.memory_entry import MemoryEntry
from core.memory.memory_intelligence_models import (
    ContradictionReport,
    ContradictionResolution,
    ContradictionType,
)
from core.memory.memory_provenance import (
    MemoryConfidence,
    ProvenanceSource,
)

logger = get_logger("jessyca.memory.contradiction")

# Pares de términos y estados mutuamente excluyentes para detección determinista
MUTUALLY_EXCLUSIVE_PAIRS: tuple[tuple[str, str], ...] = (
    ("oscuro", "claro"),
    ("dark", "light"),
    ("activado", "desactivado"),
    ("habilitado", "deshabilitado"),
    ("enabled", "disabled"),
    ("permitido", "bloqueado"),
    ("permitido", "denegado"),
    ("verdadero", "falso"),
    ("true", "false"),
    ("si", "no"),
    ("yes", "no"),
    ("español", "inglés"),
    ("spanish", "english"),
)


class ContradictionDetector:
    """Motor de detección y gobernanza de contradicciones en memoria."""

    KEY_OVERLAP_THRESHOLD: ClassVar[float] = 0.60

    def detect_contradiction(
        self,
        new_entry: MemoryEntry,
        existing_entries: list[MemoryEntry] | tuple[MemoryEntry, ...],
    ) -> ContradictionReport:
        """Evalúa si una nueva entrada de memoria entra en conflicto lógico o semántico con memorias existentes."""
        for old in existing_entries:
            if old.entry_id == new_entry.entry_id:
                continue

            # 1. Comprobar colisión directa por clave exacta
            if old.key.lower() == new_entry.key.lower() and old.content.strip().lower() != new_entry.content.strip().lower():
                return self._evaluate_conflict(old, new_entry, reason="Misma clave con contenido discrepante")

            # 2. Comprobar contradicción en preferencias del usuario o afirmaciones semánticas
            conflict_detected, pair_found = self._check_semantic_opposition(old.content, new_entry.content)
            if conflict_detected:
                explanation = f"Conflicto semántico directo detectado ({pair_found[0]} vs {pair_found[1]})"
                return self._evaluate_conflict(old, new_entry, reason=explanation)

        return ContradictionReport(has_contradiction=False)

    def _check_semantic_opposition(self, text_a: str, text_b: str) -> tuple[bool, tuple[str, str]]:
        """Verifica si dos textos contienen términos mutuamente excluyentes compartiendo un contexto común."""
        norm_a = text_a.lower()
        norm_b = text_b.lower()

        # Palabras compartidas como contexto (ej. 'prefiere', 'tema', 'modo', 'idioma')
        words_a = set(re.findall(r"\w+", norm_a))
        words_b = set(re.findall(r"\w+", norm_b))
        common_words = words_a.intersection(words_b)

        # Si comparten al menos 2 términos de contexto significativo
        meaningful_common = [w for w in common_words if len(w) > 3 and w not in ("para", "como", "este", "esta", "todo")]
        if len(meaningful_common) >= 1:
            for term_1, term_2 in MUTUALLY_EXCLUSIVE_PAIRS:
                if (term_1 in norm_a and term_2 in norm_b) or (term_2 in norm_a and term_1 in norm_b):
                    return True, (term_1, term_2)

        return False, ("", "")

    def _evaluate_conflict(
        self,
        existing: MemoryEntry,
        new_entry: MemoryEntry,
        reason: str,
    ) -> ContradictionReport:
        """Aplica la política epistémica de seguridad para determinar la resolución adecuada."""
        # REGLA 1: Intento de LLM / UNVERIFIED de sobrescribir verdad del USUARIO / VERIFIED
        if (
            existing.provenance.source in (ProvenanceSource.USER, ProvenanceSource.SYSTEM)
            and existing.confidence == MemoryConfidence.VERIFIED
            and new_entry.provenance.source == ProvenanceSource.LLM
        ):
            logger.warning(
                f"[CONTRADICTION DETECTED] Intento de LLM '{new_entry.provenance.creator_id}' de contradecir memoria VERIFIED '{existing.key}'"
            )
            return ContradictionReport(
                has_contradiction=True,
                contradiction_type=ContradictionType.DIRECT_CONTRADICTION,
                existing_entry=existing,
                new_entry=new_entry,
                similarity_key=existing.key,
                resolution=ContradictionResolution.REJECTED_UNVERIFIED,
                explanation=f"{reason}. Rechazado: Inferencias de LLM no pueden sobrescribir memorias confirmadas del usuario.",
                requires_user_clarification=False,
            )

        # REGLA 2: Actualización legítima del usuario sobre afirmación previa no verificada del LLM
        if (
            existing.provenance.source == ProvenanceSource.LLM
            and new_entry.provenance.source == ProvenanceSource.USER
        ):
            return ContradictionReport(
                has_contradiction=True,
                contradiction_type=ContradictionType.TEMPORAL_SUPERSEDED,
                existing_entry=existing,
                new_entry=new_entry,
                similarity_key=existing.key,
                resolution=ContradictionResolution.SUPERSEDED,
                explanation=f"{reason}. Aprobado: La entrada directa del usuario supera afirmaciones previas del LLM.",
                requires_user_clarification=False,
            )

        # REGLA 3: Ambas entradas provienen del usuario
        if existing.provenance.source == ProvenanceSource.USER and new_entry.provenance.source == ProvenanceSource.USER:
            # Si es una actualización explícita por la misma clave, se asume cambio de preferencia (SUPERSEDED)
            if existing.key.lower() == new_entry.key.lower():
                return ContradictionReport(
                    has_contradiction=True,
                    contradiction_type=ContradictionType.PREFERENCE_CONFLICT,
                    existing_entry=existing,
                    new_entry=new_entry,
                    similarity_key=existing.key,
                    resolution=ContradictionResolution.SUPERSEDED,
                    explanation=f"{reason}. Actualización de preferencia del usuario por misma clave.",
                    requires_user_clarification=False,
                )

            # Si es por texto semántico divergente con claves distintas, requiere clarificación
            return ContradictionReport(
                has_contradiction=True,
                contradiction_type=ContradictionType.PREFERENCE_CONFLICT,
                existing_entry=existing,
                new_entry=new_entry,
                similarity_key=existing.key,
                resolution=ContradictionResolution.REQUIRES_USER_CLARIFICATION,
                explanation=f"{reason}. Se detectaron dos preferencias contradictorias del usuario.",
                requires_user_clarification=True,
            )

        # Por defecto: Inconsistencia no resuelta
        return ContradictionReport(
            has_contradiction=True,
            contradiction_type=ContradictionType.VALUE_MISMATCH,
            existing_entry=existing,
            new_entry=new_entry,
            similarity_key=existing.key,
            resolution=ContradictionResolution.UNRESOLVED,
            explanation=reason,
            requires_user_clarification=True,
        )
