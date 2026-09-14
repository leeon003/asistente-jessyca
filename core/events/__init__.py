"""Submódulo de eventos de JESSYCA 4.0.

Expone la clase base Event y el catálogo de eventos tipados fundamentales del sistema.
"""

from __future__ import annotations

from core.events.base import (
    ActionExecuted,
    ActionProposed,
    AudioCaptured,
    ClarificationRequested,
    ErrorOccurred,
    Event,
    IntentClassified,
    SpeakRequested,
    UserInterrupted,
    UtteranceFinal,
    VerificationResult,
    WakeWordDetected,
)

__all__ = [
    "ActionExecuted",
    "ActionProposed",
    "AudioCaptured",
    "ClarificationRequested",
    "ErrorOccurred",
    "Event",
    "IntentClassified",
    "SpeakRequested",
    "UserInterrupted",
    "UtteranceFinal",
    "VerificationResult",
    "WakeWordDetected",
]
