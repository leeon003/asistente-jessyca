"""Almacén persistente y seguro de Perfiles de Usuario (profile_store.py - Fase 22).

Gestiona las preferencias confirmadas del perfil de usuario y los candidatos pendientes de consentimiento.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. PROFILE != AUTHORIZATION
2. Thread-safe: Toda mutación está protegida mediante threading.RLock.
3. Sanitización de secretos antes de persistir.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, ClassVar

from core.command_output import SecretRedactor
from core.logger import get_logger
from core.memory.memory_provenance import (
    MemoryConfidence,
    MemoryProvenance,
    ProvenanceSource,
)
from core.profile.profile_models import (
    ConsentStatus,
    ProfileCategory,
    ProfilePreferenceItem,
)

logger = get_logger("jessyca.profile.store")


class UserProfileStore:
    """Almacén thread-safe para preferencias de perfil y candidatos a personalización."""

    _instance: ClassVar[UserProfileStore | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, storage_path: Path | str = "data/user_profiles.json") -> None:
        self._lock = threading.RLock()
        self.storage_path = Path(storage_path)
        # user_id -> category -> key -> ProfilePreferenceItem
        self._profiles: dict[str, dict[ProfileCategory, dict[str, ProfilePreferenceItem]]] = {}
        # candidate_id -> ProfilePreferenceItem (pendientes de consentimiento)
        self._candidates: dict[str, ProfilePreferenceItem] = {}

        self._load_from_disk()

    @classmethod
    def get_instance(cls, storage_path: Path | str = "data/user_profiles.json") -> UserProfileStore:
        """Obtiene la instancia singleton global del almacén de perfiles."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = UserProfileStore(storage_path=storage_path)
            return cls._instance

    def reset(self) -> None:
        """Restablece el estado en memoria para aislamiento de pruebas."""
        with self._lock:
            self._profiles.clear()
            self._candidates.clear()

    # ── GESTIÓN DE PREFERENCIAS CONFIRMADAS ──

    def set_preference(self, item: ProfilePreferenceItem) -> ProfilePreferenceItem:
        """Registra o actualiza una preferencia confirmada en el perfil del usuario."""
        # Sanitizar valores de texto
        if isinstance(item.value, str):
            sanitized_val, _ = SecretRedactor.redact(item.value)
            clean_item = item.with_value(sanitized_val)
        else:
            clean_item = item

        with self._lock:
            uid = clean_item.user_id
            cat = clean_item.category
            key = clean_item.key

            if uid not in self._profiles:
                self._profiles[uid] = {}
            if cat not in self._profiles[uid]:
                self._profiles[uid][cat] = {}

            self._profiles[uid][cat][key] = clean_item
            self._save_to_disk()

        logger.info(
            f"[USER PROFILE UPDATED] Usuario '{clean_item.user_id}' | Categoría: '{clean_item.category}' | Clave: '{clean_item.key}'"
        )
        return clean_item

    def get_preference(self, user_id: str, category: ProfileCategory, key: str) -> ProfilePreferenceItem | None:
        """Obtiene un ítem de preferencia por usuario, categoría y clave."""
        uid = str(user_id).strip().lower()
        clean_key = str(key).strip().lower()

        with self._lock:
            return self._profiles.get(uid, {}).get(category, {}).get(clean_key)

    def get_preference_value(self, user_id: str, category: ProfileCategory, key: str, default: Any = None) -> Any:
        """Obtiene directamente el valor de una preferencia o retorna el valor por defecto."""
        item = self.get_preference(user_id=user_id, category=category, key=key)
        if item is not None and item.consent_status == ConsentStatus.CONFIRMED_BY_USER:
            return item.value
        return default

    def delete_preference(self, user_id: str, category: ProfileCategory, key: str) -> bool:
        """Elimina una preferencia del perfil del usuario."""
        uid = str(user_id).strip().lower()
        clean_key = str(key).strip().lower()

        with self._lock:
            if uid in self._profiles and category in self._profiles[uid] and clean_key in self._profiles[uid][category]:
                del self._profiles[uid][category][clean_key]
                self._save_to_disk()
                logger.info(f"[USER PROFILE DELETED] Usuario '{uid}' | {category}.{clean_key}")
                return True
            return False

    def list_preferences(self, user_id: str, category: ProfileCategory | None = None) -> list[ProfilePreferenceItem]:
        """Lista todas las preferencias confirmadas del usuario, opcionalmente filtradas por categoría."""
        uid = str(user_id).strip().lower()
        results: list[ProfilePreferenceItem] = []

        with self._lock:
            user_cats = self._profiles.get(uid, {})
            for cat, key_dict in user_cats.items():
                if category is not None and cat != category:
                    continue
                for item in key_dict.values():
                    if item.consent_status == ConsentStatus.CONFIRMED_BY_USER:
                        results.append(item)

        results.sort(key=lambda item: item.updated_at, reverse=True)
        return results

    # ── GESTIÓN DE CANDIDATOS Y PROTOCOLO DE CONSENTIMIENTO ──

    def add_candidate(self, item: ProfilePreferenceItem) -> ProfilePreferenceItem:
        """Registra una preferencia candidata que aguarda consentimiento explícito del usuario."""
        with self._lock:
            self._candidates[item.item_id] = item
        logger.info(f"[PROFILE CANDIDATE REGISTERED] '{item.item_id}' ({item.category}.{item.key})")
        return item

    def confirm_candidate(self, candidate_id: str) -> ProfilePreferenceItem | None:
        """Aprueba formalmente un candidato y lo promueve al perfil persistente."""
        with self._lock:
            candidate = self._candidates.pop(candidate_id, None)
            if not candidate:
                return None

            confirmed = candidate.with_confirmation()
            return self.set_preference(confirmed)

    def reject_candidate(self, candidate_id: str) -> bool:
        """Rechaza y descarta una preferencia candidata."""
        with self._lock:
            if candidate_id in self._candidates:
                del self._candidates[candidate_id]
                logger.info(f"[PROFILE CANDIDATE REJECTED] '{candidate_id}' descartado.")
                return True
            return False

    def list_pending_candidates(self, user_id: str) -> list[ProfilePreferenceItem]:
        """Retorna la lista de candidatos pendientes de confirmación para el usuario."""
        uid = str(user_id).strip().lower()
        with self._lock:
            return [
                item for item in self._candidates.values()
                if item.user_id == uid and item.consent_status == ConsentStatus.PENDING_USER_CONSENT
            ]

    # ── PERSISTENCIA JSON ──

    def _save_to_disk(self) -> None:
        """Serializa las preferencias confirmadas a disco."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, list[dict[str, Any]]] = {}

            for uid, cat_dict in self._profiles.items():
                data[uid] = []
                for key_dict in cat_dict.values():
                    for item in key_dict.values():
                        data[uid].append(item.to_dict())

            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[USER PROFILE PERSISTENCE WARNING] No se pudo guardar a '{self.storage_path}': {e}")

    def _load_from_disk(self) -> None:
        """Carga las preferencias desde disco si existe el archivo."""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                for uid, items in data.items():
                    self._profiles[uid] = {}
                    for it_dict in items:
                        cat = ProfileCategory(it_dict.get("category", "preferences"))
                        key = it_dict.get("key", "")
                        prov_dict = it_dict.get("provenance", {})
                        prov = MemoryProvenance(
                            source=ProvenanceSource(prov_dict.get("source", "user")),
                            creator_id=prov_dict.get("creator_id", uid),
                        )
                        item = ProfilePreferenceItem(
                            item_id=it_dict.get("item_id", ""),
                            user_id=uid,
                            category=cat,
                            key=key,
                            value=it_dict.get("value"),
                            consent_status=ConsentStatus(it_dict.get("consent_status", "confirmed_by_user")),
                            confidence=MemoryConfidence(it_dict.get("confidence", "verified")),
                            provenance=prov,
                            access_count=it_dict.get("access_count", 0),
                            metadata=it_dict.get("metadata", {}),
                        )
                        if cat not in self._profiles[uid]:
                            self._profiles[uid][cat] = {}
                        self._profiles[uid][cat][key] = item
        except Exception as e:
            logger.warning(f"[USER PROFILE LOAD WARNING] Error al leer '{self.storage_path}': {e}")
