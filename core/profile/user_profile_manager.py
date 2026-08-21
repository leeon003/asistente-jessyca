"""Gestor Orquestador de Perfiles de Usuario y Personalización (user_profile_manager.py - Fase 22).

Orquesta la distinción entre información transitoria y preferencias persistentes,
el protocolo de consentimiento explícito ("¿Quieres que recuerde esto?") y el
suministro de contexto personalizado a los agentes y LLMs.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. PROFILE != AUTHORIZATION
2. Ningún perfil puede auto-otorgarse roles de seguridad ni evadir confirmaciones requeridas.
3. Tratamiento estricto como UNTRUSTED DATA.
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar

from core.logger import get_logger
from core.memory.memory_provenance import (
    MemoryConfidence,
    MemoryProvenance,
    ProvenanceSource,
)
from core.profile.preference_detector import PreferenceDetector
from core.profile.profile_models import (
    ConsentStatus,
    InformationScopeType,
    ProfileCategory,
    ProfilePreferenceItem,
)
from core.profile.profile_store import UserProfileStore

logger = get_logger("jessyca.profile.manager")


class UserProfileManager:
    """Orquestador central para la personalización y perfil del usuario."""

    _instance: ClassVar[UserProfileManager | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, store: UserProfileStore | None = None) -> None:
        self._lock = threading.RLock()
        self.store = store or UserProfileStore.get_instance()
        self.detector = PreferenceDetector()

    @classmethod
    def get_instance(cls, store: UserProfileStore | None = None) -> UserProfileManager:
        """Obtiene la instancia singleton global de UserProfileManager."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = UserProfileManager(store=store)
            return cls._instance

    # ── ANÁLISIS DE ENTRADAS Y PROTOCOLO DE CONSENTIMIENTO ──

    def process_statement(
        self,
        user_id: str,
        user_text: str,
    ) -> tuple[ProfilePreferenceItem | None, str | None]:
        """Analiza una entrada y actualiza el perfil directamente o solicita consentimiento si es un candidato."""
        scope_type, category, key, value, prompt = self.detector.analyze_statement(user_text)

        if scope_type == InformationScopeType.ONE_TIME_FACT or category is None or key is None:
            return None, None

        if scope_type == InformationScopeType.EXPLICIT_PREFERENCE:
            # Declaración directa del usuario -> Guardar directamente en el perfil
            item = ProfilePreferenceItem.create(
                user_id=user_id,
                category=category,
                key=key,
                value=value,
                consent_status=ConsentStatus.CONFIRMED_BY_USER,
                confidence=MemoryConfidence.VERIFIED,
                provenance=MemoryProvenance.create_for_user(user_id=user_id),
            )
            saved = self.store.set_preference(item)
            return saved, None

        if scope_type == InformationScopeType.PREFERENCE_CANDIDATE:
            # Preferencia implícita -> Registrar candidato y solicitar confirmación
            candidate = ProfilePreferenceItem.create(
                user_id=user_id,
                category=category,
                key=key,
                value=value,
                consent_status=ConsentStatus.PENDING_USER_CONSENT,
                confidence=MemoryConfidence.UNVERIFIED,
                provenance=MemoryProvenance(source=ProvenanceSource.AGENT, creator_id="preference_detector"),
                confirmation_prompt=prompt,
            )
            registered = self.store.add_candidate(candidate)
            return registered, prompt

        return None, None

    def confirm_candidate(self, candidate_id: str) -> ProfilePreferenceItem | None:
        """Confirma y promueve formalmente un candidato a preferencia persistente."""
        return self.store.confirm_candidate(candidate_id)

    def reject_candidate(self, candidate_id: str) -> bool:
        """Rechaza y elimina una preferencia candidata."""
        return self.store.reject_candidate(candidate_id)

    # ── ACCESO Y CONSULTA DIRECTA DE PREFERENCIAS ──

    def set_preference(
        self,
        user_id: str,
        category: ProfileCategory,
        key: str,
        value: Any,
        provenance: MemoryProvenance | None = None,
    ) -> ProfilePreferenceItem:
        """Establece explícitamente una preferencia confirmada."""
        prov = provenance or MemoryProvenance.create_for_user(user_id=user_id)
        item = ProfilePreferenceItem.create(
            user_id=user_id,
            category=category,
            key=key,
            value=value,
            consent_status=ConsentStatus.CONFIRMED_BY_USER,
            confidence=MemoryConfidence.VERIFIED,
            provenance=prov,
        )
        return self.store.set_preference(item)

    def get_preference_value(
        self,
        user_id: str,
        category: ProfileCategory,
        key: str,
        default: Any = None,
    ) -> Any:
        """Obtiene el valor de una preferencia del usuario."""
        return self.store.get_preference_value(user_id=user_id, category=category, key=key, default=default)

    def delete_preference(self, user_id: str, category: ProfileCategory, key: str) -> bool:
        """Elimina una preferencia del perfil del usuario."""
        return self.store.delete_preference(user_id=user_id, category=category, key=key)

    def list_preferences(
        self,
        user_id: str,
        category: ProfileCategory | None = None,
    ) -> list[ProfilePreferenceItem]:
        """Lista todas las preferencias activas del perfil."""
        return self.store.list_preferences(user_id=user_id, category=category)

    # ── INYECCIÓN DE CONTEXTO PERSONALIZADO ──

    def build_profile_context(
        self,
        user_id: str,
        categories: tuple[ProfileCategory, ...] | None = None,
    ) -> str:
        """Construye un bloque de contexto formateado para el orquestador o LLMs."""
        items = self.store.list_preferences(user_id=user_id)
        if not items:
            return ""

        lines: list[str] = ["=== PERFIL Y PREFERENCIAS DEL USUARIO ==="]
        for item in items:
            if categories is not None and item.category not in categories:
                continue
            cat_label = item.category.value.upper()
            lines.append(f"• [{cat_label}] {item.key}: {item.value}")

        lines.append("=========================================")
        return "\n".join(lines)


def get_user_profile_manager() -> UserProfileManager:
    """Acceso helper al singleton global de UserProfileManager."""
    return UserProfileManager.get_instance()
