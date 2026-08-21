"""Clasificador y Detector de Intención de Preferencias (preference_detector.py - Fase 22: User Profile).

Distingue determinísticamente entre:
- ONE_TIME_INFORMATION: Datos efímeros de sesión que NO deben guardarse en el perfil.
- PREFERENCE_CANDIDATE: Preferencias implícitas que exigen confirmación interactiva.
- EXPLICIT_PREFERENCE: Afirmaciones directas y definitivas del usuario para su perfil.
"""

from __future__ import annotations

import re
from typing import Any

from core.logger import get_logger
from core.profile.profile_models import (
    InformationScopeType,
    ProfileCategory,
)

logger = get_logger("jessyca.profile.detector")

# Patrones explícitos que indican orden directa del usuario para recordar/personalizar
EXPLICIT_REMEMBER_PATTERNS = [
    r"\b(recuerda que|guarda en mi perfil|de ahora en adelante|a partir de ahora|siempre que me hables|mi preferencia es|configura por defecto)\b",
    r"\b(mi proyecto (principal|activo|favorito) es|mi editor (favorito|predeterminado) es|mi aplicacion favorita es)\b",
]

# Patrones transitorios de un solo uso (One-Time)
ONE_TIME_PATTERNS = [
    r"\b(abre|cierra|ejecuta|busca|lee|borra|elimina|crea el archivo|hoy|ahora|en este momento|solo por esta vez|temporalmente)\b",
    r"\b(revisa el estado|cuanta ram|pon el volumen|que hora es|mañana tengo)\b",
]

# Mapeo de palabras clave a categorías de perfil
CATEGORY_KEYWORD_MAP: list[tuple[ProfileCategory, list[str]]] = [
    (ProfileCategory.COMMUNICATION_STYLE, ["conciso", "tecnico", "técnico", "formal", "breve", "detallado", "explicativo", "estilo de respuesta"]),
    (ProfileCategory.PREFERENCES, ["tema oscuro", "tema claro", "modo oscuro", "modo claro", "idioma", "espanol", "español", "ingles", "inglés", "unidades metricas", "métricas"]),
    (ProfileCategory.FREQUENT_APPS, ["vs code", "visual studio", "edge", "terminal", "notepad", "bloc de notas", "chrome", "navegador"]),
    (ProfileCategory.PROJECTS, ["proyecto", "repositorio", "codebase", "sistema jessyca", "directorio de trabajo"]),
    (ProfileCategory.FREQUENT_TASKS, ["inspeccion diaria", "limpieza de logs", "backup", "diagnostico"]),
    (ProfileCategory.CONFIGURATIONS, ["puerto", "url base", "directorio de descargas", "sandbox"]),
    (ProfileCategory.INTERACTION_HABITS, ["atajos", "confirmacion por voz", "notificaciones", "sin confirmacion"]),
]


class PreferenceDetector:
    """Detector y clasificador de preferencias y hábitos a partir de entradas del usuario."""

    @classmethod
    def analyze_statement(
        cls,
        text: str,
    ) -> tuple[InformationScopeType, ProfileCategory | None, str | None, Any | None, str | None]:
        """Clasifica el texto en ONE_TIME_FACT, PREFERENCE_CANDIDATE o EXPLICIT_PREFERENCE."""
        clean = text.strip().lower()
        if not clean:
            return InformationScopeType.ONE_TIME_FACT, None, None, None, None

        # 1. Comprobar si es explícitamente una preferencia permanente declarada
        for pat in EXPLICIT_REMEMBER_PATTERNS:
            if re.search(pat, clean):
                cat, key, val = cls._extract_category_and_value(clean)
                if cat and key:
                    return InformationScopeType.EXPLICIT_PREFERENCE, cat, key, val, None

        # 2. Comprobar si es claramente una orden de un solo uso (One-Time)
        for pat in ONE_TIME_PATTERNS:
            if re.search(pat, clean) and not any(p in clean for p in ("siempre", "por defecto", "recuerda")):
                return InformationScopeType.ONE_TIME_FACT, None, None, None, None

        # 3. Comprobar si coincide con términos de preferencias pero sin instrucción explícita de persistencia
        cat, key, val = cls._extract_category_and_value(clean)
        if cat and key:
            prompt = f"¿Quieres que recuerde que prefieres '{val}' para futuras conversaciones?"
            return InformationScopeType.PREFERENCE_CANDIDATE, cat, key, val, prompt

        return InformationScopeType.ONE_TIME_FACT, None, None, None, None

    @classmethod
    def _extract_category_and_value(cls, text: str) -> tuple[ProfileCategory | None, str | None, Any | None]:
        """Extrae la categoría, clave y valor normalizado a partir del texto."""
        # Comunicación
        if "conciso" in text or "breve" in text:
            return ProfileCategory.COMMUNICATION_STYLE, "style", "concise"
        if "formal" in text:
            return ProfileCategory.COMMUNICATION_STYLE, "style", "formal"
        if "técnico" in text or "tecnico" in text:
            return ProfileCategory.COMMUNICATION_STYLE, "style", "technical"
        if "detallado" in text or "explicativo" in text:
            return ProfileCategory.COMMUNICATION_STYLE, "style", "detailed"

        # Tema
        if "modo oscuro" in text or "tema oscuro" in text:
            return ProfileCategory.PREFERENCES, "theme", "dark"
        if "modo claro" in text or "tema claro" in text:
            return ProfileCategory.PREFERENCES, "theme", "light"

        # Idioma
        if "español" in text or "espanol" in text:
            return ProfileCategory.PREFERENCES, "language", "es"
        if "inglés" in text or "ingles" in text:
            return ProfileCategory.PREFERENCES, "language", "en"

        # Apps frecuentes
        if "vs code" in text or "visual studio code" in text:
            return ProfileCategory.FREQUENT_APPS, "primary_editor", "Visual Studio Code"
        if "edge" in text:
            return ProfileCategory.FREQUENT_APPS, "primary_browser", "Microsoft Edge"

        # Proyectos
        proj_match = re.search(r"proyecto\s+([\w\-\.]+)", text)
        if proj_match:
            return ProfileCategory.PROJECTS, "active_project", proj_match.group(1)

        return None, None, None
