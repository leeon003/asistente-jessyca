"""Analizador de Calidad de Transcripción y Completitud de Intenciones (quality_analyzer.py).

Garantiza:
1. LOW CONFIDENCE => NO UNSAFE ACTION
2. INCOMPLETE INTENT => CLARIFICATION
3. AMBIGUOUS TRANSCRIPT => ASK REPEAT
4. Variaciones del nombre (Jessica / Jessyca / Jessi / Jessy) normalizadas de forma segura.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.local_agent.quality_analyzer")


class TranscriptQuality(StrEnum):
    """Niveles de calidad de una transcripción STT."""

    VALID = "VALID"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    EMPTY = "EMPTY"
    NOISE = "NOISE"


class IntentCompleteness(StrEnum):
    """Estado de completitud de una intención expresada por el usuario."""

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class QualityAnalysisResult:
    """Resultado estructurado del análisis de calidad de transcripción."""

    quality: TranscriptQuality
    normalized_text: str
    raw_text: str
    confidence: float
    is_acceptable: bool
    reason: str
    suggested_prompt: str | None = None


@dataclass(frozen=True)
class CompletenessResult:
    """Resultado estructurado de la evaluación de completitud de la orden."""

    completeness: IntentCompleteness
    intent_category: str
    missing_slot: str | None = None
    clarification_question: str | None = None
    extracted_slots: dict[str, Any] = field(default_factory=dict)


class SafeTextNormalizer:
    """Normalizador seguro de texto de entrada sin alteraciones arbitrarias de vocabulario."""

    # Variantes comunes de wake/command prefix
    WAKE_PREFIXES_REGEX = re.compile(
        r"^(jessyca|jessica|jessi|jessy|yesica|yesyca|olle\s*jessyca|oye\s*jessica|oye\s*jessyca|oye\s*jessi)[,\s]*",
        re.IGNORECASE,
    )

    @classmethod
    def normalize_wake_prefix(cls, text: str) -> tuple[str, bool]:
        """Elimina de forma segura el prefijo del nombre si está presente."""
        text_clean = text.strip()
        match = cls.WAKE_PREFIXES_REGEX.match(text_clean)
        if match:
            had_prefix = True
            cleaned = text_clean[match.end():].strip()
            # Si el usuario solo dijo el nombre "Jessica" o "Jessyca"
            if not cleaned:
                cleaned = "hola"
            return cleaned, had_prefix
        return text_clean, False

    @classmethod
    def clean_text(cls, text: str) -> str:
        """Limpia espacios repetidos y caracteres de control preservando palabras."""
        if not text:
            return ""
        # Normalizar espacios
        t = re.sub(r"\s+", " ", text.strip())
        return t


class TranscriptQualityAnalyzer:
    """Analiza la calidad y confiabilidad de una transcripción producida por STT."""

    # Palabras o fragmentos defectuosos que no son palabras/artículos válidos en español
    SUSPICIOUS_FRAGMENTS: set[str] = {
        "pre",
        "da",
        "ab",
        "des",
        "in",
        "tra",
        "conx",
    }

    def __init__(self, min_confidence: float = 0.60) -> None:
        self.min_confidence = min_confidence

    def analyze(self, raw_text: str, confidence: float = 1.0) -> QualityAnalysisResult:
        """Evalúa si la transcripción es válida para procesamiento o si debe solicitarse repetición."""
        if not raw_text or not raw_text.strip():
            return QualityAnalysisResult(
                quality=TranscriptQuality.EMPTY,
                normalized_text="",
                raw_text=raw_text,
                confidence=0.0,
                is_acceptable=False,
                reason="Transcripción vacía o sin contenido de audio.",
                suggested_prompt="No escuché ninguna orden. ¿Puedes repetir?",
            )

        cleaned, _had_wake = SafeTextNormalizer.normalize_wake_prefix(raw_text)
        cleaned = SafeTextNormalizer.clean_text(cleaned)
        words = cleaned.split()

        # 1. Comprobación de nivel de confianza bajo
        if confidence < self.min_confidence:
            logger.warning(f"[TRANSCRIPT LOW CONFIDENCE] Confianza {confidence:.2f} < {self.min_confidence:.2f} para '{raw_text}'.")
            return QualityAnalysisResult(
                quality=TranscriptQuality.LOW_CONFIDENCE,
                normalized_text=cleaned,
                raw_text=raw_text,
                confidence=confidence,
                is_acceptable=False,
                reason=f"Nivel de confianza STT ({confidence:.2f}) inferior al umbral.",
                suggested_prompt="No te entendí bien. ¿Puedes repetirlo?",
            )

        # 2. Detección de fragmentos defectuosos como "pre calculadora"
        if len(words) >= 2 and words[0].lower() in self.SUSPICIOUS_FRAGMENTS:
            logger.warning(f"[DEFECTIVE TRANSCRIPT DETECTED] Fragmento sospechoso: '{raw_text}'.")
            return QualityAnalysisResult(
                quality=TranscriptQuality.AMBIGUOUS,
                normalized_text=cleaned,
                raw_text=raw_text,
                confidence=confidence * 0.5,
                is_acceptable=False,
                reason=f"Transcripción defectuosa o prefijo truncado ('{words[0]}').",
                suggested_prompt="No te entendí bien. ¿Puedes repetirlo?",
            )

        # 3. Palabra única que es solo fragmento defectuoso
        if len(words) == 1 and words[0].lower() in self.SUSPICIOUS_FRAGMENTS:
            return QualityAnalysisResult(
                quality=TranscriptQuality.NOISE,
                normalized_text=cleaned,
                raw_text=raw_text,
                confidence=0.1,
                is_acceptable=False,
                reason="Audio contiene únicamente una palabra de enlace o ruido.",
                suggested_prompt="No te entendí bien. ¿Puedes repetirlo?",
            )

        return QualityAnalysisResult(
            quality=TranscriptQuality.VALID,
            normalized_text=cleaned,
            raw_text=raw_text,
            confidence=confidence,
            is_acceptable=True,
            reason="Transcripción válida y de calidad suficiente.",
            suggested_prompt=None,
        )


class IntentCompletenessChecker:
    """Verifica si una orden posee la información suficiente para ejecutarse o requiere continuación."""

    # Terminaciones de preposiciones/artículos que indican corte abrupto
    TRAILING_INCOMPLETE_REGEX = re.compile(
        r"\b(de\s*lo|de\s*la|de\s*los|de\s*las|de|un|una|el|la|los|las|en|sobre|para|con|por)$",
        re.IGNORECASE,
    )

    def check_completeness(self, text: str) -> CompletenessResult:
        """Evalúa si la frase está completa o si le falta el objeto/tema."""
        cleaned = SafeTextNormalizer.clean_text(text)
        lower = cleaned.lower()
        lower_clean = re.sub(r"[\.\,\;\:\?\!\s]+$", "", lower).strip()

        # 1. Caso: "dame un informe de lo" / "investiga sobre" / "busca de" (frase truncada)
        if any(w in lower_clean for w in ("informe", "reporte", "investiga", "investigar", "analiza", "analizar")):
            # Verificar si termina en preposición incompleta
            if self.TRAILING_INCOMPLETE_REGEX.search(lower_clean):
                return CompletenessResult(
                    completeness=IntentCompleteness.INCOMPLETE,
                    intent_category="multistep_research",
                    missing_slot="topic",
                    clarification_question="¿De qué tema quieres el informe?",
                )

        # 2. Caso: "Abre una aplicación" / "Abre una app" (Intención incompleta sin app)
        if lower in (
            "abre una aplicación",
            "abre una aplicacion",
            "abre una app",
            "abre una aplicacion por favor",
            "abrir una aplicacion",
            "abrir una aplicación",
            "abre alguna aplicación",
            "abre alguna aplicacion",
        ):
            return CompletenessResult(
                completeness=IntentCompleteness.INCOMPLETE,
                intent_category="open_application",
                missing_slot="app_name",
                clarification_question="Claro. ¿Cuál aplicación quieres abrir?",
            )

        # 3. Caso: "Pon una alarma" (Tarea multi-parámetro)
        if lower in ("pon una alarma", "crea una alarma", "configura una alarma", "alarma", "pon alarma"):
            return CompletenessResult(
                completeness=IntentCompleteness.INCOMPLETE,
                intent_category="set_alarm",
                missing_slot="alarm_time",
                clarification_question="¿Para qué hora?",
            )

        # 4. Caso: "Abre notas" (Ambigüedad significativa)
        if lower in ("abre notas", "abrir notas", "notas"):
            return CompletenessResult(
                completeness=IntentCompleteness.AMBIGUOUS,
                intent_category="open_application",
                missing_slot="app_name",
                clarification_question="¿Te refieres al Bloc de notas o a otra aplicación de notas?",
            )

        # 5. Caso: "abre el" / "abre la" / "inicia" sin aplicación
        if lower in ("abre", "abrir", "abre el", "abre la", "abre un", "inicia", "ejecuta", "lanza"):
            return CompletenessResult(
                completeness=IntentCompleteness.INCOMPLETE,
                intent_category="open_application",
                missing_slot="app_name",
                clarification_question="¿Qué aplicación deseas que abra?",
            )

        # 6. Caso: "busca" / "busca en" sin parámetro
        if lower in ("busca", "buscar", "busca en", "encuentra", "localiza"):
            return CompletenessResult(
                completeness=IntentCompleteness.INCOMPLETE,
                intent_category="search_file",
                missing_slot="query",
                clarification_question="¿Qué archivo o documento estás buscando?",
            )

        # 7. Caso: "cierra" / "cierra el"
        if lower in ("cierra", "cerrar", "cierra el", "cierra la"):
            return CompletenessResult(
                completeness=IntentCompleteness.INCOMPLETE,
                intent_category="close_application",
                missing_slot="app_name",
                clarification_question="¿Qué aplicación deseas cerrar?",
            )

        # 8. Caso: "elimina" / "borra"
        if lower in ("elimina", "eliminar", "borra", "borrar"):
            return CompletenessResult(
                completeness=IntentCompleteness.INCOMPLETE,
                intent_category="delete_file",
                missing_slot="path",
                clarification_question="¿Qué archivo deseas eliminar?",
            )

        return CompletenessResult(
            completeness=IntentCompleteness.COMPLETE,
            intent_category="general",
        )
