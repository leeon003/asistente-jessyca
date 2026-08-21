"""Modelos de trazabilidad de procedencia y niveles de confianza de memoria (memory_provenance.py - Fase 12).

Garantiza que toda información almacenada conserve su origen verificable y previene que afirmaciones
no verificadas generadas por LLMs se conviertan automáticamente en hechos autorizados.

INVARIANTE DE SEGURIDAD ABSOLUTA:
LLM OUTPUT = UNTRUSTED DATA
Ningún LLM ni herramienta puede auto-validar sus afirmaciones ni elevar su propio nivel de confianza.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.memory.memory_exceptions import InvalidProvenanceError, MemoryPromotionError


class ProvenanceSource(StrEnum):
    """Fuentes originarias de la información almacenada en memoria."""

    USER = "user"            # Entrada directa confirmada por el usuario humano
    SYSTEM = "system"        # Componentes del núcleo y sistema operativo verificado
    AGENT = "agent"          # Agente especializado ejecutando lógica interna
    TOOL = "tool"            # Salida de ejecución de una herramienta verificada
    LLM = "llm"              # Inferencia o afirmación generada por un modelo de lenguaje
    EXTERNAL = "external"    # Datos provenientes de fuentes externas no verificadas


class MemoryConfidence(StrEnum):
    """Niveles formales de confianza epistémica de las entradas de memoria."""

    UNVERIFIED = "unverified"  # Afirmación no corroborada (por defecto para LLM y externas)
    LOW = "low"                # Hecho preliminar con baja evidencia
    MEDIUM = "medium"          # Hecho con evidencia parcial o corroboración simple
    HIGH = "high"              # Hecho con evidencia sólida o verificación de múltiples fuentes
    VERIFIED = "verified"      # Verdad confirmada formalmente por el usuario o subsistema de seguridad


# Fuentes con autoridad para validar y promover hechos a VERIFIED
AUTHORITATIVE_VERIFIER_SOURCES: set[ProvenanceSource] = {
    ProvenanceSource.USER,
    ProvenanceSource.SYSTEM,
}


@dataclass(frozen=True)
class MemoryProvenance:
    """Trazabilidad inmutable de la procedencia y estado de verificación de una entrada de memoria."""

    source: ProvenanceSource
    creator_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    verified_by: str | None = None
    verification_evidence: str | None = None
    is_unverified_claim: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.creator_id or not isinstance(self.creator_id, str) or not self.creator_id.strip():
            raise InvalidProvenanceError("El creator_id de la procedencia de memoria no puede estar vacío.")

    @classmethod
    def create_for_llm(cls, model_id: str, prompt_context: str | None = None) -> MemoryProvenance:
        """Crea una procedencia para inferencias de LLM (estrictamente no verificadas por defecto)."""
        meta = {"prompt_context": prompt_context} if prompt_context else {}
        return cls(
            source=ProvenanceSource.LLM,
            creator_id=str(model_id).strip(),
            is_unverified_claim=True,
            metadata=meta,
        )

    @classmethod
    def create_for_user(cls, user_id: str = "interactive_user") -> MemoryProvenance:
        """Crea una procedencia para entradas explícitas del usuario humano."""
        return cls(
            source=ProvenanceSource.USER,
            creator_id=str(user_id).strip(),
            verified_by=str(user_id).strip(),
            verification_evidence="Direct user input",
            is_unverified_claim=False,
        )

    @classmethod
    def create_for_agent(cls, agent_id: str, is_claim: bool = True) -> MemoryProvenance:
        """Crea una procedencia para observaciones de un agente especializado."""
        return cls(
            source=ProvenanceSource.AGENT,
            creator_id=str(agent_id).strip(),
            is_unverified_claim=is_claim,
        )

    @classmethod
    def create_for_tool(cls, tool_name: str, execution_id: str | None = None) -> MemoryProvenance:
        """Crea una procedencia para resultados de ejecución de herramientas."""
        meta = {"execution_id": execution_id} if execution_id else {}
        return cls(
            source=ProvenanceSource.TOOL,
            creator_id=str(tool_name).strip(),
            is_unverified_claim=False,
            metadata=meta,
        )

    @classmethod
    def create_for_system(cls, component_name: str = "core_system") -> MemoryProvenance:
        """Crea una procedencia para hechos generados por el núcleo de seguridad o sistema."""
        return cls(
            source=ProvenanceSource.SYSTEM,
            creator_id=str(component_name).strip(),
            verified_by="system",
            verification_evidence="System state verification",
            is_unverified_claim=False,
        )

    def promote_to_verified(
        self,
        verifier_id: str,
        verifier_source: ProvenanceSource,
        evidence: str,
    ) -> MemoryProvenance:
        """Promueve la procedencia a estado verificado.

        INVARIANTE DE SEGURIDAD:
        Un LLM o fuente externa NUNCA puede ser el verifier_source.
        """
        if verifier_source not in AUTHORITATIVE_VERIFIER_SOURCES:
            raise MemoryPromotionError(
                f"[SECURITY VIOLATION] La fuente '{verifier_source}' no tiene autoridad para promover hechos a VERIFIED. "
                f"Fuentes autorizadas: {[s.value for s in AUTHORITATIVE_VERIFIER_SOURCES]}"
            )

        if not verifier_id or not str(verifier_id).strip():
            raise MemoryPromotionError("El verifier_id de la promoción no puede estar vacío.")

        if not evidence or not str(evidence).strip():
            raise MemoryPromotionError("Se requiere evidencia explícita para promover una memoria a VERIFIED.")

        updated_meta = dict(self.metadata)
        updated_meta["promoted_at"] = datetime.now(UTC).isoformat()
        updated_meta["previous_unverified_status"] = self.is_unverified_claim

        return MemoryProvenance(
            source=self.source,
            creator_id=self.creator_id,
            created_at=self.created_at,
            verified_by=str(verifier_id).strip(),
            verification_evidence=str(evidence).strip(),
            is_unverified_claim=False,
            metadata=updated_meta,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convierte la procedencia a diccionario estructurado."""
        return {
            "source": str(self.source),
            "creator_id": self.creator_id,
            "created_at": self.created_at.isoformat(),
            "verified_by": self.verified_by,
            "verification_evidence": self.verification_evidence,
            "is_unverified_claim": self.is_unverified_claim,
            "metadata": dict(self.metadata),
        }
