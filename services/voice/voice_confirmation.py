"""Evaluador Seguro de Confirmaciones por Voz (voice_confirmation.py - Fase 30).

Garantiza que una confirmación verbal cumpla reglas estrictas:
- Un sonido ambiguo, ruido ambiental o conversación externa NUNCA se acepta como confirmación.
- Requiere umbral mínimo de confianza acústica/lingüística.
- Distingue respuestas afirmativas claras, rechazos explícitos y ambigüedades.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.logger import get_logger
from services.voice.stt_service import TranscriptResult

logger = get_logger("jessyca.voice.confirmation")

AFFIRMATIVE_TOKENS: frozenset[str] = frozenset({
    "sí",
    "si",
    "confirmo",
    "afirmativo",
    "adelante",
    "proceder",
    "de acuerdo",
    "ejecutar",
    "hazlo",
    "correcto",
    "autorizo",
    "sí confirmo",
    "si confirmo",
    "sí adelante",
    "si adelante",
    "sí procede",
    "si procede",
})

NEGATIVE_TOKENS: frozenset[str] = frozenset({
    "no",
    "cancela",
    "cancelar",
    "rechazar",
    "no lo hagas",
    "negativo",
    "para",
    "alto",
    "detén",
    "detente",
    "olvídalo",
    "no cancela",
    "no no",
})

AMBIGUOUS_TOKENS: frozenset[str] = frozenset({
    "mmm",
    "eh",
    "a ver",
    "quizás",
    "quizas",
    "tal vez",
    "hola",
    "no sé",
    "no se",
    "creo que",
    "puede ser",
    "espera",
    "un momento",
    "ya veo",
    "bueno",
    "oye",
})


@dataclass(frozen=True)
class VoiceConfirmationDecision:
    """Decisión inmutable sobre una confirmación recibida por voz."""

    is_confirmed: bool
    is_rejected: bool
    is_ambiguous: bool
    confidence: float
    raw_text: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_confirmed": self.is_confirmed,
            "is_rejected": self.is_rejected,
            "is_ambiguous": self.is_ambiguous,
            "confidence": self.confidence,
            "raw_text": self.raw_text,
            "reason": self.reason,
        }


class VoiceConfirmationEvaluator:
    """Evaluador determinista de seguridad para respuestas de confirmación por voz."""

    MIN_CONFIDENCE_THRESHOLD: float = 0.70

    @classmethod
    def evaluate(cls, transcript: TranscriptResult | str) -> VoiceConfirmationDecision:
        """Evalúa un texto o TranscriptResult para determinar si es una confirmación válida."""
        if isinstance(transcript, str):
            text = transcript.strip()
            confidence = 1.0
        else:
            text = transcript.text.strip()
            confidence = transcript.confidence

        cleaned = cls._clean_text(text)

        # 1. Validación de audio vacío o confianza deficiente
        if not cleaned:
            return VoiceConfirmationDecision(
                is_confirmed=False,
                is_rejected=False,
                is_ambiguous=True,
                confidence=confidence,
                raw_text=text,
                reason="Audio vacío o inaudible.",
            )

        if confidence < cls.MIN_CONFIDENCE_THRESHOLD:
            logger.warning(
                f"[VOICE CONFIRMATION] Rechazado por baja confianza: '{text}' ({confidence:.2f} < {cls.MIN_CONFIDENCE_THRESHOLD})"
            )
            return VoiceConfirmationDecision(
                is_confirmed=False,
                is_rejected=False,
                is_ambiguous=True,
                confidence=confidence,
                raw_text=text,
                reason=f"Confianza de transcripción insuficiente ({confidence:.2f}).",
            )

        # 2. Detección de ruido, muletillas o conversación ambigua
        for amb in AMBIGUOUS_TOKENS:
            if cleaned == amb or cleaned.startswith(amb + " "):
                logger.info(f"[VOICE CONFIRMATION] Detectada respuesta ambigua: '{cleaned}'")
                return VoiceConfirmationDecision(
                    is_confirmed=False,
                    is_rejected=False,
                    is_ambiguous=True,
                    confidence=confidence,
                    raw_text=text,
                    reason="Respuesta ambigua o ruido/muletilla detectada.",
                )

        # 3. Verificación de rechazo explícito
        if cleaned in NEGATIVE_TOKENS:
            logger.info(f"[VOICE CONFIRMATION] Rechazo explícito detectado: '{cleaned}'")
            return VoiceConfirmationDecision(
                is_confirmed=False,
                is_rejected=True,
                is_ambiguous=False,
                confidence=confidence,
                raw_text=text,
                reason="Acción rechazada explícitamente por el usuario.",
            )

        # 4. Verificación de afirmación explícita
        if cleaned in AFFIRMATIVE_TOKENS:
            logger.info(f"[VOICE CONFIRMATION] Confirmación explícita autorizada: '{cleaned}'")
            return VoiceConfirmationDecision(
                is_confirmed=True,
                is_rejected=False,
                is_ambiguous=False,
                confidence=confidence,
                raw_text=text,
                reason="Confirmación explícita recibida y autorizada.",
            )

        # 5. Frases compuestas o no reconocidas se tratan como ambiguas por seguridad
        logger.warning(f"[VOICE CONFIRMATION] Entrada no coincide con catálogo de confirmación: '{cleaned}'")
        return VoiceConfirmationDecision(
            is_confirmed=False,
            is_rejected=False,
            is_ambiguous=True,
            confidence=confidence,
            raw_text=text,
            reason=f"Respuesta no reconocida como token de confirmación unívoco ('{cleaned}').",
        )

    @staticmethod
    def _clean_text(text: str) -> str:
        """Limpia y normaliza el texto eliminando puntuación y acentos discordantes."""
        t = text.lower().strip()
        t = re.sub(r"[^\w\s\sáéíóúÁÉÍÓÚñÑ]", "", t)
        return re.sub(r"\s+", " ", t).strip()
