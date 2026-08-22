"""Cálculo y Dinámica de Confianza de Preferencias (preference_confidence.py - Fase 62).

Gobierna:
1. Acumulación progresiva de evidencia para elevar candidatos a estado ACTIVE (>= 0.70).
2. Confirmación explícita por parte del usuario (salto directo a >= 0.95).
3. Penalización por contradicciones y degradación a CANDIDATE / FORGOTTEN (< 0.25).
4. Decaimiento temporal determinista por desuso prolongado (time decay).
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.personalization.preference_models import (
    PreferenceSource,
    PreferenceStatus,
    UserPreference,
)

# Umbrales y factores de cálculo
INITIAL_CANDIDATE_CONFIDENCE: float = 0.35
EVIDENCE_INCREMENT: float = 0.15
EXPLICIT_CONFIRMATION_CONFIDENCE: float = 0.95
CONTRADICTION_DECREMENT: float = 0.25
ACTIVE_THRESHOLD: float = 0.70
FORGOTTEN_THRESHOLD: float = 0.25
DAILY_DECAY_RATE: float = 0.01  # 1% diario de decaimiento por inactividad


class ConfidenceCalculator:
    """Calculador de dinámica de confianza y transiciones de estado para preferencias."""

    @staticmethod
    def calculate_observation(
        current: UserPreference,
        matched: bool,
        is_explicit: bool = False,
    ) -> UserPreference:
        """Actualiza la confianza, conteos de evidencia y estado ante una nueva interacción."""
        now = datetime.now(UTC)
        pref_dict = current.to_dict()
        pref_dict["last_observed"] = now.isoformat()
        pref_dict["updated_at"] = now.isoformat()

        if matched:
            pref_dict["evidence_count"] = current.evidence_count + 1
            if is_explicit:
                pref_dict["confidence"] = max(current.confidence, EXPLICIT_CONFIRMATION_CONFIDENCE)
                pref_dict["last_confirmed"] = now.isoformat()
                pref_dict["source"] = PreferenceSource.USER_EXPLICIT.value
            else:
                pref_dict["confidence"] = min(1.0, current.confidence + EVIDENCE_INCREMENT)

            # Promover a ACTIVE si alcanza el umbral
            if pref_dict["confidence"] >= ACTIVE_THRESHOLD and current.status != PreferenceStatus.ACTIVE:
                pref_dict["status"] = PreferenceStatus.ACTIVE.value

        else:
            # Contradicción / Corrección
            pref_dict["contradiction_count"] = current.contradiction_count + 1
            new_conf = max(0.0, current.confidence - CONTRADICTION_DECREMENT)
            pref_dict["confidence"] = new_conf

            if new_conf < FORGOTTEN_THRESHOLD:
                pref_dict["status"] = PreferenceStatus.FORGOTTEN.value
            elif new_conf < ACTIVE_THRESHOLD and current.status == PreferenceStatus.ACTIVE:
                pref_dict["status"] = PreferenceStatus.CANDIDATE.value

        return UserPreference.from_dict(pref_dict)

    @staticmethod
    def apply_time_decay(
        preference: UserPreference,
        days_elapsed: float,
    ) -> UserPreference:
        """Aplica decaimiento temporal sobre preferencias no observadas recientemente."""
        if days_elapsed <= 0.0 or preference.status in (PreferenceStatus.FORGOTTEN, PreferenceStatus.EXPIRED):
            return preference

        decay = days_elapsed * DAILY_DECAY_RATE
        new_conf = max(0.0, preference.confidence - decay)

        pref_dict = preference.to_dict()
        pref_dict["confidence"] = new_conf
        pref_dict["updated_at"] = datetime.now(UTC).isoformat()

        if new_conf < FORGOTTEN_THRESHOLD:
            pref_dict["status"] = PreferenceStatus.EXPIRED.value
        elif new_conf < ACTIVE_THRESHOLD and preference.status == PreferenceStatus.ACTIVE:
            pref_dict["status"] = PreferenceStatus.CANDIDATE.value

        return UserPreference.from_dict(pref_dict)
