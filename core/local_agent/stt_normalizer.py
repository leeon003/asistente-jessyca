"""Normalizador Contextual de Transcripciones STT (stt_normalizer.py).

Mitiga errores y ruidos de reconocimiento acústico (como 'música cierre bloc de notas'
o muletillas de voz) sin recurrir a sustituciones frágiles ad-hoc.
Utiliza reconocimiento de patrones verbales, canonización de flexiones y alineación
con entidades de acción conocidas (aplicaciones, personas, búsquedas).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.local_agent.stt_normalizer")

# Muletillas y ruidos acústicos frecuentes al inicio de transcripciones de voz
COMMON_ACOUSTIC_NOISE_PREFIXES: tuple[str, ...] = (
    "música ",
    "musica ",
    "oye ",
    "oigan ",
    "eh ",
    "este ",
    "bueno ",
    "a ver ",
    "por favor ",
    "porfa ",
    "jessica, ",
    "jessyca, ",
    "jessica ",
    "jessyca ",
)

# Normalizaciones canónicas de flexiones verbales hacia formas imperativas estándar
VERB_INFLECTIONS_MAP: dict[str, str] = {
    "cierre": "cierra",
    "cierres": "cierra",
    "cierren": "cierra",
    "cerrar": "cierra",
    "abra": "abre",
    "abran": "abre",
    "abras": "abre",
    "abrir": "abre",
    "busque": "busca",
    "busquen": "busca",
    "busques": "busca",
    "buscar": "busca",
    "salude": "saluda",
    "saluden": "saluda",
    "saludes": "saluda",
    "saludar": "saluda",
}

# Entidades conocidas del sistema para detección de intenciones de acción
KNOWN_APP_ENTITIES: tuple[str, ...] = (
    "bloc de notas",
    "el bloc de notas",
    "notepad",
    "calculadora",
    "la calculadora",
    "calc",
    "google",
    "el navegador",
    "navegador",
    "edge",
    "chrome",
    "paint",
    "consola",
    "terminal",
    "cmd",
)


@dataclass(frozen=True)
class STTNormalizationResult:
    """Resultado estructurado de la normalización de transcripción STT."""

    original_text: str
    normalized_text: str
    was_modified: bool
    detected_action: str | None = None
    detected_target: str | None = None
    is_ambiguous: bool = False
    clarification_prompt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class STTTranscriptNormalizer:
    """Normalizador de texto de voz con tolerancia a ruido y concordancia contextual."""

    def __init__(self) -> None:
        pass

    def normalize(self, raw_transcript: str) -> STTNormalizationResult:
        """Normaliza una transcripción de voz tolerando artefactos de audio y flexiones."""
        if not raw_transcript or not raw_transcript.strip():
            return STTNormalizationResult(
                original_text=raw_transcript,
                normalized_text="",
                was_modified=False,
            )

        text = raw_transcript.strip()
        lower = text.lower()
        cleaned_lower = lower

        # 1. Eliminar prefijos repetidos de invocación de wake word o muletillas
        cleaned_lower = re.sub(r"^(?:(?:jessyca|jessica)[,\s]+)+", "", cleaned_lower).strip()

        # 2. Eliminar modales de cortesía iniciales ("puedes cerrar...", "por favor...")
        cleaned_lower = re.sub(r"^(?:puedes|podrías|podrias|por favor|favor de|oye|hey)\s+", "", cleaned_lower).strip()

        # 3. Detección de comandos de acción con ruido acústico inicial (ej: "música cierre bloc de notas")
        for noise in COMMON_ACOUSTIC_NOISE_PREFIXES:
            if cleaned_lower.startswith(noise):
                candidate = cleaned_lower[len(noise):].strip()
                # Verificar si tras remover el ruido hay una orden clara de acción
                tokens = candidate.split()
                if tokens:
                    first_verb = VERB_INFLECTIONS_MAP.get(tokens[0], tokens[0])
                    if first_verb in ("cierra", "cerrar", "abre", "abrir", "busca", "buscar", "saluda"):
                        cleaned_lower = f"{first_verb} {' '.join(tokens[1:])}"
                        break

        # 4. Canonización de flexiones verbales en la primera posición
        tokens = cleaned_lower.split()
        if tokens:
            v_orig = tokens[0]
            if v_orig in VERB_INFLECTIONS_MAP:
                tokens[0] = VERB_INFLECTIONS_MAP[v_orig]
                cleaned_lower = " ".join(tokens)

        # 5. Normalizar artículos directos en comandos de acción ("cierra el bloc" -> "cierra bloc")
        cleaned_lower = re.sub(r"^(cierra|cerrar|abre|abrir)\s+(?:el|la|los|las|un|una)\s+", r"\1 ", cleaned_lower).strip()

        # 4. Reconocimiento de acción y entidad
        detected_action: str | None = None
        detected_target: str | None = None
        is_ambiguous = False
        clarification_prompt: str | None = None

        if any(cleaned_lower.startswith(v) for v in ("cierra ", "cerrar ", "puedes cerrar ")):
            detected_action = "close_application"
            for app in KNOWN_APP_ENTITIES:
                if app in cleaned_lower:
                    detected_target = "notepad" if "bloc" in app or "notepad" in app else ("calc" if "calc" in app else app)
                    break
        elif any(cleaned_lower.startswith(v) for v in ("abre ", "abrir ", "inicia ", "puedes abrir ")):
            if "google" in cleaned_lower:
                detected_action = "open_browser"
                detected_target = "Google"
            else:
                detected_action = "open_application"
                for app in KNOWN_APP_ENTITIES:
                    if app in cleaned_lower:
                        detected_target = "notepad" if "bloc" in app or "notepad" in app else ("calc" if "calc" in app else app)
                        break

        was_mod = (cleaned_lower != lower)
        if was_mod:
            logger.info(f"[STT NORMALIZATION] '{raw_transcript}' -> '{cleaned_lower}' (Acción: {detected_action}, Target: {detected_target})")

        return STTNormalizationResult(
            original_text=raw_transcript,
            normalized_text=cleaned_lower if was_mod else raw_transcript,
            was_modified=was_mod,
            detected_action=detected_action,
            detected_target=detected_target,
            is_ambiguous=is_ambiguous,
            clarification_prompt=clarification_prompt,
        )


_normalizer_instance: STTTranscriptNormalizer | None = None


def get_stt_normalizer() -> STTTranscriptNormalizer:
    """Obtiene la instancia singleton del normalizador STT."""
    global _normalizer_instance
    if _normalizer_instance is None:
        _normalizer_instance = STTTranscriptNormalizer()
    return _normalizer_instance
