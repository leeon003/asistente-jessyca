"""Modelos de datos inmutables para el Perfil de Usuario y Personalización (profile_models.py - Fase 22).

Define la jerarquía estructurada para:
SESSION MEMORY -> LONG TERM MEMORY -> USER PROFILE

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. PROFILE != AUTHORIZATION (El perfil contiene evidencia informativa, jamás autoridad de seguridad).
2. UNTRUSTED DATA: Todo dato del perfil se procesa como datos no confiables.
3. No auto-promoción: Afirmaciones del LLM requieren consentimiento explícito antes de guardarse en el perfil.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.memory.memory_provenance import (
    MemoryConfidence,
    MemoryProvenance,
    ProvenanceSource,
)


class ProfileCategory(StrEnum):
    """Categorías tipadas de preferencias y personalización del usuario."""

    PREFERENCES = "preferences"                  # Preferencias generales (idioma, tema visual, unidades)
    COMMUNICATION_STYLE = "communication_style"  # Estilo de diálogo (conciso, técnico, formal, explicativo)
    FREQUENT_APPS = "frequent_apps"              # Aplicaciones de uso habitual (VS Code, Edge, Terminal)
    PROJECTS = "projects"                        # Proyectos activos y contextos de trabajo
    FREQUENT_TASKS = "frequent_tasks"            # Flujos y tareas repetitivas autorizadas
    CONFIGURATIONS = "configurations"            # Parámetros y opciones operativas del usuario
    INTERACTION_HABITS = "interaction_habits"    # Hábitos de interacción (atajos, feedback preferido)


class InformationScopeType(StrEnum):
    """Clasificación de temporalidad y persistencia de la información observada."""

    ONE_TIME_FACT = "one_time_fact"                        # Dato transitorio de la sesión actual (no guardar en perfil)
    PREFERENCE_CANDIDATE = "preference_candidate"          # Posible preferencia que requiere confirmación
    EXPLICIT_PREFERENCE = "explicit_preference"            # Preferencia expresada y confirmada directamente por el usuario


class ConsentStatus(StrEnum):
    """Estado formal del consentimiento del usuario sobre una preferencia persistente."""

    CONFIRMED_BY_USER = "confirmed_by_user"                # Confirmado explícitamente por el usuario humano
    PENDING_USER_CONSENT = "pending_user_consent"          # Requiere confirmación ("¿Quieres que recuerde esto?")
    REJECTED_BY_USER = "rejected_by_user"                  # El usuario rechazó almacenar la preferencia
    AUTO_DERIVED_EPHEMERAL = "auto_derived_ephemeral"      # Inferido por LLM sin confirmar (descartado para perfil)


@dataclass(frozen=True)
class ProfilePreferenceItem:
    """Elemento individual inmutable de preferencia en el perfil de usuario."""

    item_id: str
    user_id: str
    category: ProfileCategory
    key: str
    value: Any
    consent_status: ConsentStatus
    confidence: MemoryConfidence = MemoryConfidence.UNVERIFIED
    provenance: MemoryProvenance = field(
        default_factory=lambda: MemoryProvenance(source=ProvenanceSource.USER, creator_id="user")
    )
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    access_count: int = 0
    confirmation_prompt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        user_id: str,
        category: ProfileCategory,
        key: str,
        value: Any,
        consent_status: ConsentStatus = ConsentStatus.CONFIRMED_BY_USER,
        confidence: MemoryConfidence = MemoryConfidence.VERIFIED,
        provenance: MemoryProvenance | None = None,
        confirmation_prompt: str | None = None,
        item_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProfilePreferenceItem:
        """Constructor seguro para crear un nuevo ítem de preferencia de perfil."""
        iid = item_id or f"prof_{uuid.uuid4().hex[:10]}"
        now = datetime.now(UTC)
        prov = provenance or MemoryProvenance.create_for_user(user_id=user_id)

        # Regla de seguridad: Inferencias de LLM sin validar nunca pueden crearse directamente como CONFIRMED
        resolved_status = consent_status
        resolved_conf = confidence
        if prov.source in (ProvenanceSource.LLM, ProvenanceSource.EXTERNAL) and consent_status == ConsentStatus.CONFIRMED_BY_USER:
            resolved_status = ConsentStatus.PENDING_USER_CONSENT
            resolved_conf = MemoryConfidence.UNVERIFIED

        return cls(
            item_id=iid,
            user_id=str(user_id).strip().lower(),
            category=category,
            key=str(key).strip().lower(),
            value=value,
            consent_status=resolved_status,
            confidence=resolved_conf,
            provenance=prov,
            created_at=now,
            updated_at=now,
            confirmation_prompt=confirmation_prompt,
            metadata=dict(metadata or {}),
        )

    def with_confirmation(self) -> ProfilePreferenceItem:
        """Retorna una copia inmutable formalmente promovida a CONFIRMED_BY_USER y VERIFIED."""
        return ProfilePreferenceItem(
            item_id=self.item_id,
            user_id=self.user_id,
            category=self.category,
            key=self.key,
            value=self.value,
            consent_status=ConsentStatus.CONFIRMED_BY_USER,
            confidence=MemoryConfidence.VERIFIED,
            provenance=self.provenance.promote_to_verified(
                verifier_id=self.user_id,
                verifier_source=ProvenanceSource.USER,
                evidence="Consentimiento explícito otorgado por el usuario",
            ),
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            access_count=self.access_count,
            confirmation_prompt=None,
            metadata={**self.metadata, "confirmed_at": datetime.now(UTC).isoformat()},
        )

    def with_rejection(self) -> ProfilePreferenceItem:
        """Retorna una copia inmutable marcada como REJECTED_BY_USER."""
        return ProfilePreferenceItem(
            item_id=self.item_id,
            user_id=self.user_id,
            category=self.category,
            key=self.key,
            value=self.value,
            consent_status=ConsentStatus.REJECTED_BY_USER,
            confidence=MemoryConfidence.LOW,
            provenance=self.provenance,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            access_count=self.access_count,
            confirmation_prompt=None,
            metadata={**self.metadata, "rejected_at": datetime.now(UTC).isoformat()},
        )

    def with_value(self, new_value: Any, new_confidence: MemoryConfidence | None = None) -> ProfilePreferenceItem:
        """Retorna una copia inmutable con el valor actualizado."""
        return ProfilePreferenceItem(
            item_id=self.item_id,
            user_id=self.user_id,
            category=self.category,
            key=self.key,
            value=new_value,
            consent_status=self.consent_status,
            confidence=new_confidence if new_confidence is not None else self.confidence,
            provenance=self.provenance,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            access_count=self.access_count + 1,
            confirmation_prompt=self.confirmation_prompt,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa el ítem a un diccionario seguro."""
        return {
            "item_id": self.item_id,
            "user_id": self.user_id,
            "category": str(self.category),
            "key": self.key,
            "value": self.value,
            "consent_status": str(self.consent_status),
            "confidence": str(self.confidence),
            "provenance": self.provenance.to_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "access_count": self.access_count,
            "confirmation_prompt": self.confirmation_prompt,
            "metadata": dict(self.metadata),
        }
