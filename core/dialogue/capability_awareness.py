"""Motor de Conciencia de Capacidades de JESSYCA (capability_awareness.py - Fase 52.1).

Permite consultar y evaluar si JESSYCA puede realizar una solicitud, determinando:
- Nivel de cobertura (FULL, PARTIAL, NONE)
- Aspectos soportados y no soportados
- Explicaciones conversacionales transparentes y veraces sin inventar capacidades
"""

from __future__ import annotations

import threading
from typing import Any

from core.dialogue.dialogue_models import (
    CapabilityAssessment,
    CapabilityLevel,
)
from core.logger import get_logger
from skills.skill_registry import SkillRegistry

logger = get_logger("jessyca.dialogue.capability_awareness")


class CapabilityAwarenessEngine:
    """Motor de evaluación y explicación de capacidades reales del sistema."""

    _instance: CapabilityAwarenessEngine | None = None
    _lock = threading.RLock()

    def __init__(self, skill_registry: SkillRegistry | None = None) -> None:
        self.skill_registry = skill_registry or SkillRegistry.get_instance()

    @classmethod
    def get_instance(cls) -> CapabilityAwarenessEngine:
        with cls._lock:
            if cls._instance is None:
                cls._instance = CapabilityAwarenessEngine()
            return cls._instance

    # ── 1. EVALUACIÓN DE PETICIONES ──

    def assess_request(
        self,
        user_input: str,
        intent: str,
        params: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> CapabilityAssessment:
        """Evalúa si una petición del usuario está totalmente, parcialmente o no soportada."""
        lower = user_input.strip().lower()
        params_dict = params or {}

        # 1.1 Consultas de capacidades explícitas ("¿Puedes...?", "¿Sabes...?")
        if self._is_capability_query(lower):
            explanation = self.explain_capability(lower)
            return CapabilityAssessment(
                intent="explain_capability",
                level=CapabilityLevel.FULL,
                supported=True,
                supported_aspects=["explicar_capacidades"],
                explanation=explanation,
            )

        # 1.2 Peticiones con capacidades no soportadas conocidas
        unsupported_patterns = [
            ("edita profesionalmente", "edición profesional de vídeo"),
            ("editar profesionalmente", "edición profesional de vídeo"),
            ("hazlo viral", "optimización de viralidad"),
            ("hazlo famoso", "optimización de viralidad"),
            ("edítalo para tiktok", "edición para TikTok"),
            ("editalo para tiktok", "edición para TikTok"),
            ("edita este vídeo", "edición de vídeo"),
            ("edita este video", "edición de vídeo"),
            ("prende las luces", "control domótico de luces"),
            ("enciende las luces", "control domótico de luces"),
            ("apaga las luces", "control domótico de luces"),
            ("cocina", "preparación física de alimentos"),
            ("hackea", "ciberataques no autorizados"),
        ]

        detected_unsupported: list[str] = []
        for pattern, desc in unsupported_patterns:
            if pattern in lower:
                detected_unsupported.append(desc)

        # 1.3 Evaluar si hay capacidades parciales combinadas
        detected_supported: list[str] = []
        if any(w in lower for w in ("busca", "buscar", "pon", "reproduce", "ver", "encuentra")):
            if any(k in lower for k in ("baile", "bailame", "báilame", "video", "vídeo")):
                detected_supported.append("buscar y reproducir vídeos de baile")
            elif any(k in lower for k in ("musica", "música", "cancion", "canción", "youtube", "morodo")):
                detected_supported.append("buscar y reproducir contenido en YouTube o la web")
            else:
                detected_supported.append("búsqueda de archivos o contenido")

        if any(w in lower for w in ("abre", "abrir", "inicia", "iniciar")):
            detected_supported.append("apertura de aplicaciones o sitios web")

        # Caso: Soporte Parcial
        if detected_supported and detected_unsupported:
            supp_str = " y ".join(detected_supported)
            unsupp_str = " y ".join(detected_unsupported)
            explanation = (
                f"Puedo ayudarte a {supp_str}, pero todavía no puedo realizar {unsupp_str}."
            )
            return CapabilityAssessment(
                intent=intent,
                level=CapabilityLevel.PARTIAL,
                supported=True,
                supported_aspects=detected_supported,
                unsupported_aspects=detected_unsupported,
                explanation=explanation,
            )

        # Caso: No Soportado
        if detected_unsupported:
            return CapabilityAssessment(
                intent="unsupported",
                level=CapabilityLevel.NONE,
                supported=False,
                unsupported_aspects=detected_unsupported,
                explanation="Eso todavía no puedo hacerlo directamente.",
            )

        # 1.4 Capacidades nativas registradas
        if intent == "play_random_video":
            return CapabilityAssessment(
                intent=intent,
                level=CapabilityLevel.FULL,
                supported=True,
                supported_aspects=["reproducción de vídeos de baile"],
                skill_id="windows.media@1.0.0",
                tool_name="windows.media.play",
            )

        if intent in ("open_application", "close_application"):
            app_target = params_dict.get("app_name") or params_dict.get("target") or "aplicación"
            return CapabilityAssessment(
                intent=intent,
                level=CapabilityLevel.FULL,
                supported=True,
                supported_aspects=[f"control de aplicación ({app_target})"],
                skill_id="windows.apps@1.0.0",
                tool_name="windows.launch_app" if intent == "open_application" else "windows.close_app",
            )

        if intent in ("browser_search", "search_file", "math_calculation", "multistep_research", "general_query"):
            return CapabilityAssessment(
                intent=intent,
                level=CapabilityLevel.FULL,
                supported=True,
                supported_aspects=[intent],
            )

        # Por defecto, si se reconoce la skill
        return CapabilityAssessment(
            intent=intent,
            level=CapabilityLevel.FULL,
            supported=True,
            supported_aspects=[intent],
        )

    # ── 2. EXPLICACIÓN DE CAPACIDADES ──

    def _is_capability_query(self, lower: str) -> bool:
        """Determina si el usuario está preguntando por las capacidades del sistema."""
        capability_triggers = (
            "puedes abrir",
            "sabes abrir",
            "puedes reproducir",
            "puedes bailar",
            "puedes hacerme un baile",
            "puedes hacer un baile",
            "puedes poner",
            "puedes buscar",
            "puedes editar",
            "qué puedes hacer",
            "que puedes hacer",
            "qué sabes hacer",
            "que sabes hacer",
            "cuáles son tus capacidades",
            "cuales son tus capacidades",
        )
        return any(t in lower for t in capability_triggers)

    def explain_capability(self, query: str) -> str:
        """Genera una explicación conversacional honesta de las capacidades del sistema."""
        lower = query.lower()

        # YouTube / Navegación
        if "youtube" in lower:
            return "Sí. Puedo abrir YouTube, buscar vídeos o música y reproducir lo que me indiques."

        # Baile / Media
        if any(w in lower for w in ("baile", "bailar", "bailame", "báilame")):
            return "Sí. Puedo elegir uno de tus vídeos de baile y reproducirlo."

        # Edición de vídeo (No soportada)
        if any(w in lower for w in ("editar", "edita", "edición", "edicion")):
            return "Eso todavía no puedo hacerlo directamente."

        # Aplicaciones de escritorio
        if any(w in lower for w in ("aplicacion", "aplicación", "bloc de notas", "calculadora", "programas")):
            return "Sí. Puedo abrir y cerrar aplicaciones como el Bloc de notas, la Calculadora o el navegador."

        # Búsquedas o archivos
        if any(w in lower for w in ("archivo", "archivos", "buscar", "documentos")):
            return "Sí. Puedo buscar archivos en tu sistema, leer documentos y resumir información."

        # General
        return (
            "Soy Jessyca. Puedo abrir y cerrar aplicaciones, reproducir vídeos de baile, "
            "buscar y reproducir contenido en YouTube o la web, gestionar archivos y realizar cálculos."
        )
