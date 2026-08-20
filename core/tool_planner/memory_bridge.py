"""Puente de Memoria Semántica para Planificación (Memory-Aware Planning - Etapa 19.2).

AXIOMA FUNDAMENTAL DE SEGURIDAD:
  MEMORY = EVIDENCE, MEMORY ≠ AUTHORITY.

PROHIBICIONES ABSOLUTAS:
  1. Memory -> permission       (La memoria NUNCA concede permisos)
  2. Memory -> authorization    (La memoria NUNCA autoriza acciones)
  3. Memory -> capability       (La memoria NUNCA altera perfiles ni capacidades)

APORTE LEGÍTIMO DE LA MEMORIA:
  - Preferencias de usuario
  - Hechos y constantes de entorno
  - Contexto de sesiones previas
  - Historial de tareas
  - Soluciones anteriores verificadas

DEFENSAS INTEGRADAS:
  - Anti-Memory Poisoning: Detección y neutralización de inyecciones que intenten elevar privilegios.
  - Stale Memory Filtering: Detección y descarte de memorias caducadas u obsoletas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from core.logger import get_logger
from core.semantic_retriever import SemanticMemoryRetriever, SemanticMemoryType
from core.tool_planner.models import MemoryEvidence

logger = get_logger("jessyca.planner.memory_bridge")


# Patrones de envenenamiento de memoria (Memory Poisoning Attacks)
POISONING_INJECTION_PATTERNS = [
    re.compile(r"grant\s+permission", re.IGNORECASE),
    re.compile(r"bypass\s+(?:policy|confirmation|security|pipeline)", re.IGNORECASE),
    re.compile(r"elevate\s+(?:autonomy|privilege|permission)", re.IGNORECASE),
    re.compile(r"set\s+autonomy\s+(?:level|to)", re.IGNORECASE),
    re.compile(r"disable\s+(?:confirmation|audit|checks)", re.IGNORECASE),
    re.compile(r"skip\s+(?:verification|authorization|policy)", re.IGNORECASE),
    re.compile(r"allow\s+all\s+(?:actions|tools|commands)", re.IGNORECASE),
    re.compile(r"ignore\s+(?:restrictions|risk|policy)", re.IGNORECASE),
    re.compile(r"system_admin\s+override", re.IGNORECASE),
]


@dataclass(frozen=True)
class MemoryInspectionResult:
    """Resultado del análisis de seguridad y vigencia de un elemento de memoria."""

    is_valid: bool
    is_poisoned: bool
    is_stale: bool
    evidence: MemoryEvidence | None = None
    rejection_reason: str | None = None


class MemoryEvidenceSanitizer:
    """Sanitiza y evalúa la autenticidad y vigencia de evidencias de memoria."""

    MAX_EVIDENCE_AGE_DAYS: int = 90

    @classmethod
    def inspect_and_sanitize(
        cls,
        evidence_id: str,
        content: str,
        category: str = "general",
        confidence: float = 1.0,
        timestamp: datetime | None = None,
        max_age_days: int = 90,
    ) -> MemoryInspectionResult:
        """Inspecciona una entrada de memoria contra envenenamiento y obsolescencia."""
        clean_content = content.strip()

        # 1. Detección de Memory Poisoning
        for pattern in POISONING_INJECTION_PATTERNS:
            if pattern.search(clean_content):
                reason = f"Intento de envenenamiento de memoria detectado (patrón prohibido: '{pattern.pattern}')."
                logger.error(f"[MEMORY POISONING DEFENSE] {reason} en evidence '{evidence_id}'")
                return MemoryInspectionResult(
                    is_valid=False,
                    is_poisoned=True,
                    is_stale=False,
                    rejection_reason=reason,
                )

        # 2. Detección de Stale Memory (Memoria Obsoleta)
        is_stale = False
        if timestamp is not None:
            now_utc = datetime.now(UTC)
            age = (now_utc - timestamp).total_seconds()
            max_age_sec = max_age_days * 86400.0
            if age > max_age_sec:
                is_stale = True
                reason = f"Memoria obsoleta (edad: {age / 86400.0:.1f} días > límite: {max_age_days} días)."
                logger.warning(f"[STALE MEMORY FILTER] {reason} en evidence '{evidence_id}'")
                return MemoryInspectionResult(
                    is_valid=False,
                    is_poisoned=False,
                    is_stale=True,
                    rejection_reason=reason,
                )

        # Evidencia válida y sanitizada
        evidence = MemoryEvidence(
            evidence_id=evidence_id,
            fact_or_preference=clean_content,
            category=category,
            confidence=max(0.1, min(1.0, confidence)),
            source="semantic_memory",
        )
        return MemoryInspectionResult(
            is_valid=True,
            is_poisoned=False,
            is_stale=False,
            evidence=evidence,
        )


class SemanticMemoryPlannerBridge:
    """Puente entre el motor de memoria semántica y el Controlled Tool Planner."""

    def __init__(self, retriever: SemanticMemoryRetriever | None = None) -> None:
        self.retriever = retriever

    def retrieve_planning_evidence(
        self,
        intent: str,
        top_k: int = 5,
        allowed_types: tuple[SemanticMemoryType, ...] | None = None,
    ) -> list[MemoryEvidence]:
        """Recupera, sanitiza y filtra evidencias de memoria semántica relevantes para planificar una tarea."""
        if self.retriever is None:
            return []

        logger.debug(f"[MEMORY BRIDGE] Consultando memoria semántica para intent: '{intent}'")

        try:
            # Consultar memorias semánticas vía retriever
            raw_memories = self.retriever.retrieve_context(query=intent, top_k=top_k)
        except Exception as exc:
            logger.error(f"[MEMORY BRIDGE] Error al consultar SemanticMemoryRetriever: {exc}")
            return []

        valid_evidences: list[MemoryEvidence] = []

        for mem in raw_memories:
            inspection = MemoryEvidenceSanitizer.inspect_and_sanitize(
                evidence_id=str(getattr(mem, "document_id", getattr(mem, "item_id", "mem_ev"))),
                content=str(getattr(mem, "content", getattr(mem, "text", ""))),
                category=str(getattr(mem, "memory_type", "general")),
                confidence=float(getattr(mem, "similarity_score", 1.0)),
                timestamp=getattr(mem, "timestamp", None),
            )

            if inspection.is_valid and inspection.evidence is not None:
                valid_evidences.append(inspection.evidence)
            else:
                logger.info(f"[MEMORY BRIDGE] Entrada de memoria descartada: {inspection.rejection_reason}")

        return valid_evidences
