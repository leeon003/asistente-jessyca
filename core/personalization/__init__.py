"""Paquete de Personalización y Aprendizaje de Preferencias (core/personalization - Fase 62).

Exporta los modelos, validadores, calculadores de confianza, almacenes y motor
de preferencias del JESSYCA EXPERIENCE & LEARNING ENGINE.
"""

from __future__ import annotations

from core.personalization.preference_confidence import (
    ACTIVE_THRESHOLD,
    EVIDENCE_INCREMENT,
    EXPLICIT_CONFIRMATION_CONFIDENCE,
    FORGOTTEN_THRESHOLD,
    INITIAL_CANDIDATE_CONFIDENCE,
    ConfidenceCalculator,
)
from core.personalization.preference_engine import PersonalizationEngine
from core.personalization.preference_models import (
    PreferenceCategory,
    PreferenceSource,
    PreferenceStatus,
    UserPreference,
)
from core.personalization.preference_store import (
    InMemoryPreferenceStore,
    IPreferenceStore,
    SQLitePreferenceStore,
)
from core.personalization.preference_validator import (
    FORBIDDEN_PREFERENCE_TERMS,
    PreferenceValidator,
    normalize_preference_key,
)

__all__ = [
    "ACTIVE_THRESHOLD",
    "ConfidenceCalculator",
    "EVIDENCE_INCREMENT",
    "EXPLICIT_CONFIRMATION_CONFIDENCE",
    "FORBIDDEN_PREFERENCE_TERMS",
    "FORGOTTEN_THRESHOLD",
    "INITIAL_CANDIDATE_CONFIDENCE",
    "InMemoryPreferenceStore",
    "IPreferenceStore",
    "PersonalizationEngine",
    "PreferenceCategory",
    "PreferenceSource",
    "PreferenceStatus",
    "PreferenceValidator",
    "SQLitePreferenceStore",
    "UserPreference",
    "normalize_preference_key",
]
