"""Motor Central de Personalización y Aprendizaje de Preferencias (preference_engine.py - Fase 62).

Orquesta:
1. Aprendizaje de aliases de comandos y mapeos contextuales.
2. Acumulación de evidencia vs penalización por contradicción.
3. Confirmación explícita del usuario para preferencias de alta confianza.
4. Resolución determinista de conflictos entre valores alternativos.
5. Aislamiento absoluto: una preferencia NUNCA otorga permisos ni altera la seguridad.
6. Olvido voluntario y decaimiento temporal determinista.
"""

from __future__ import annotations

import threading
from typing import Any

from core.logger import get_logger
from core.personalization.preference_confidence import (
    EXPLICIT_CONFIRMATION_CONFIDENCE,
    INITIAL_CANDIDATE_CONFIDENCE,
    ConfidenceCalculator,
)
from core.personalization.preference_models import (
    PreferenceCategory,
    PreferenceSource,
    PreferenceStatus,
    UserPreference,
)
from core.personalization.preference_store import (
    IPreferenceStore,
    SQLitePreferenceStore,
)
from core.personalization.preference_validator import (
    PreferenceValidator,
    normalize_preference_key,
)

logger = get_logger("jessyca.personalization.engine")


class PersonalizationEngine:
    """Motor central para la gestión de preferencias y personalización contextual."""

    def __init__(self, store: IPreferenceStore | None = None) -> None:
        self._store = store or SQLitePreferenceStore()
        self._lock = threading.RLock()

    @property
    def store(self) -> IPreferenceStore:
        return self._store

    def record_observation(
        self,
        category: PreferenceCategory,
        key: str,
        value: Any,
        is_explicit: bool = False,
    ) -> UserPreference:
        """Registra una interacción y actualiza la confianza y estado de la preferencia."""
        with self._lock:
            norm_key = normalize_preference_key(key)

            # 1. Crear instancia para validación inicial de seguridad
            temp_pref = UserPreference(
                category=category,
                key=norm_key,
                value=value,
                confidence=EXPLICIT_CONFIRMATION_CONFIDENCE if is_explicit else INITIAL_CANDIDATE_CONFIDENCE,
            )
            is_valid, errors = PreferenceValidator.validate_preference(temp_pref)
            if not is_valid:
                raise ValueError(f"Preferencia inválida o rechazada por seguridad: {'; '.join(errors)}")

            # 2. Buscar preferencias existentes para la misma categoría y clave
            existing_prefs = self._store.get_by_key(category, norm_key)

            target_pref: UserPreference | None = None
            for p in existing_prefs:
                if str(p.value).lower().strip() == str(value).lower().strip():
                    target_pref = p
                    break

            if target_pref:
                # Actualizar evidencia de la preferencia coincidente
                updated = ConfidenceCalculator.calculate_observation(
                    target_pref,
                    matched=True,
                    is_explicit=is_explicit,
                )
                self._store.save(updated)
                logger.info(
                    f"[PERSONALIZATION] Preferencia actualizada: '{norm_key}' -> '{value}' "
                    f"(Confianza: {updated.confidence:.2f}, Evidencias: {updated.evidence_count})."
                )
                return updated

            # 3. Si existían otras opciones para la misma clave, registrar contradicción sobre ellas
            for other_p in existing_prefs:
                if other_p.status in (PreferenceStatus.ACTIVE, PreferenceStatus.CANDIDATE):
                    degraded = ConfidenceCalculator.calculate_observation(other_p, matched=False)
                    self._store.save(degraded)

            # 4. Crear nueva preferencia
            src = PreferenceSource.USER_EXPLICIT if is_explicit else PreferenceSource.INFERRED
            st = PreferenceStatus.ACTIVE if is_explicit else PreferenceStatus.CANDIDATE
            conf = EXPLICIT_CONFIRMATION_CONFIDENCE if is_explicit else INITIAL_CANDIDATE_CONFIDENCE

            new_pref = UserPreference(
                category=category,
                key=norm_key,
                value=value,
                confidence=conf,
                evidence_count=1,
                source=src,
                status=st,
            )
            self._store.save(new_pref)
            logger.info(
                f"[PERSONALIZATION] Nueva preferencia registrada: '{norm_key}' -> '{value}' "
                f"({st.value}, Confianza: {conf:.2f})."
            )
            return new_pref

    def record_contradiction(
        self,
        category: PreferenceCategory,
        key: str,
        contradicted_value: Any,
    ) -> UserPreference | None:
        """Registra una contradicción o corrección del usuario sobre una preferencia existente."""
        with self._lock:
            norm_key = normalize_preference_key(key)
            existing_prefs = self._store.get_by_key(category, norm_key)

            for p in existing_prefs:
                if str(p.value).lower().strip() == str(contradicted_value).lower().strip():
                    updated = ConfidenceCalculator.calculate_observation(p, matched=False)
                    self._store.save(updated)
                    logger.warning(
                        f"[PERSONALIZATION] Contradicción registrada en '{norm_key}' -> '{contradicted_value}'. "
                        f"Nueva confianza: {updated.confidence:.2f} ({updated.status.value})."
                    )
                    return updated
            return None

    def confirm_preference(self, preference_id: str) -> UserPreference:
        """Confirma explícitamente una preferencia ambigua elevándola a ACTIVE."""
        with self._lock:
            pref = self._store.get(preference_id)
            if not pref:
                raise ValueError(f"No se encontró la preferencia con ID '{preference_id}'.")

            confirmed = ConfidenceCalculator.calculate_observation(
                pref,
                matched=True,
                is_explicit=True,
            )
            self._store.save(confirmed)
            logger.info(f"[PERSONALIZATION] Preferencia {preference_id} confirmada explícitamente.")
            return confirmed

    def get_preferred_value(
        self,
        category: PreferenceCategory,
        key: str,
        min_confidence: float = 0.70,
    ) -> Any | None:
        """Recupera el valor preferido activo para una clave si supera el umbral de confianza."""
        with self._lock:
            norm_key = normalize_preference_key(key)
            candidates = self._store.get_by_key(category, norm_key)

            for p in candidates:
                if p.status == PreferenceStatus.ACTIVE and p.confidence >= min_confidence:
                    return p.value
            return None

    def resolve_conflicts(
        self,
        category: PreferenceCategory,
        key: str,
    ) -> UserPreference | None:
        """Resuelve conflictos de alias/preferencias seleccionando la opción con mayor confianza y evidencia."""
        with self._lock:
            norm_key = normalize_preference_key(key)
            candidates = self._store.get_by_key(category, norm_key)

            valid_candidates = [
                p for p in candidates
                if p.status in (PreferenceStatus.ACTIVE, PreferenceStatus.CANDIDATE)
            ]
            if not valid_candidates:
                return None

            # Ordenar por confianza descendente y luego por conteo de evidencias
            best = sorted(
                valid_candidates,
                key=lambda p: (p.confidence, p.evidence_count),
                reverse=True,
            )[0]
            return best

    def forget_preference(self, preference_id: str, reason: str = "Petición explícita del usuario") -> UserPreference:
        """Olvida o retira definitivamente una preferencia registrada."""
        with self._lock:
            pref = self._store.get(preference_id)
            if not pref:
                raise ValueError(f"No se encontró la preferencia con ID '{preference_id}'.")

            pref_dict = pref.to_dict()
            pref_dict["status"] = PreferenceStatus.FORGOTTEN.value
            pref_dict["confidence"] = 0.0
            pref_dict.setdefault("metadata", {})["forget_reason"] = reason

            forgotten = UserPreference.from_dict(pref_dict)
            self._store.save(forgotten)
            logger.info(f"[PERSONALIZATION] Preferencia {preference_id} olvidada. Motivo: {reason}.")
            return forgotten

    def cleanup_expired_preferences(self, decay_days: float = 30.0) -> int:
        """Aplica decaimiento temporal y actualiza el estado de preferencias en desuso."""
        with self._lock:
            all_prefs = self._store.query()
            updated_count = 0

            for p in all_prefs:
                decayed = ConfidenceCalculator.apply_time_decay(p, days_elapsed=decay_days)
                if decayed.status != p.status or decayed.confidence != p.confidence:
                    self._store.save(decayed)
                    updated_count += 1

            return updated_count
