"""Motor de Relevancia para Asistencia Proactiva (relevance_engine.py - Fase 44).

Evalúa matemáticamente y contextualmente:
1. Relevancia (0.0 a 1.0)
2. Urgencia (0.0 a 1.0)
3. Confianza (0.0 a 1.0)
4. Preferencias del usuario (umbrales mínimos y fuentes autorizadas)
5. Contexto actual (foco, aplicación activa, documentos abiertos, proyectos)

OBJETIVO: Evitar ruido cognitivo y notificaciones innecesarias.
"""

from __future__ import annotations

import re
from typing import Any

from core.logger import get_logger
from core.proactive.proactive_models import (
    ProactiveEvent,
    ProactiveEventType,
    RelevanceAssessment,
    UserControlSettings,
)

logger = get_logger("jessyca.proactive.relevance")


class RelevanceEngine:
    """Motor heurístico y contextual de evaluación de relevancia proactiva."""

    # Ponderaciones base por tipo de evento
    BASE_SCORES: dict[ProactiveEventType, tuple[float, float, float]] = {
        # (Relevancia base, Urgencia base, Confianza base)
        ProactiveEventType.CALENDAR_UPCOMING: (0.85, 0.80, 0.90),
        ProactiveEventType.TASK_FAILED: (0.90, 0.85, 0.95),
        ProactiveEventType.HEALTH_ALERT: (0.85, 0.75, 0.85),
        ProactiveEventType.SYSTEM_ERROR: (0.90, 0.85, 0.90),
        ProactiveEventType.TASK_COMPLETED: (0.70, 0.40, 0.95),
        ProactiveEventType.SYSTEM_EVENT: (0.50, 0.40, 0.75),
        ProactiveEventType.FILE_MODIFIED: (0.60, 0.45, 0.80),
        ProactiveEventType.BROWSER_ACTIVITY: (0.50, 0.35, 0.70),
        ProactiveEventType.USER_CONTEXT_CHANGE: (0.55, 0.30, 0.75),
        ProactiveEventType.NOTIFICATION: (0.45, 0.30, 0.70),
    }

    def evaluate(
        self,
        event: ProactiveEvent,
        current_context: dict[str, Any] | None = None,
        settings: UserControlSettings | None = None,
    ) -> RelevanceAssessment:
        """Evalúa integralmente la relevancia, urgencia y confianza de un ProactiveEvent."""
        ctx = current_context or {}
        cfg = settings or UserControlSettings()

        # 1. Comprobar si la fuente está explícitamente deshabilitada en preferencias
        if event.source_type not in cfg.allowed_sources:
            return RelevanceAssessment(
                relevance=0.0,
                urgency=0.0,
                confidence=0.0,
                is_relevant=False,
                reason=f"La fuente '{event.source_type}' no está permitida en las preferencias del usuario.",
                context_match={"source_disabled": True},
            )

        # 2. Puntuación base
        base_rel, base_urg, base_conf = self.BASE_SCORES.get(
            event.event_type, (0.50, 0.40, 0.70)
        )

        relevance = base_rel
        urgency = base_urg
        confidence = base_conf
        context_match: dict[str, Any] = {}
        keywords: list[str] = []

        # 3. Ajustes específicos por contenido y temporización
        # Caso Calendario: urgencia aumenta si falta poco tiempo
        if event.event_type == ProactiveEventType.CALENDAR_UPCOMING:
            starts_in = event.payload.get("starts_in_minutes")
            if starts_in is not None and isinstance(starts_in, (int, float)):
                if starts_in <= 5:
                    urgency = 0.95
                    relevance = max(relevance, 0.90)
                elif starts_in <= 15:
                    urgency = 0.80
                    relevance = max(relevance, 0.85)
                elif starts_in > 60:
                    urgency = 0.30
                    relevance = 0.50

            if event.payload.get("related_document"):
                relevance = min(1.0, relevance + 0.1)
                context_match["has_related_document"] = True

        # 4. Evaluación de coincidencia contextual (Active App, Active File, Recent Topics)
        active_app = str(ctx.get("active_application", "")).lower()
        active_file = str(ctx.get("active_file", "")).lower()
        event_summary_lower = event.summary.lower()

        if active_app and active_app in event_summary_lower:
            relevance = min(1.0, relevance + 0.15)
            context_match["active_app_matched"] = active_app

        if active_file and (active_file in event_summary_lower or any(active_file in str(v).lower() for v in event.tool_parameters.values())):
            relevance = min(1.0, relevance + 0.20)
            context_match["active_file_matched"] = active_file

        # Si el usuario está en modo "Do Not Disturb" o "Enfoque Profundo"
        if ctx.get("deep_focus_mode", False) and urgency < 0.85:
            relevance = max(0.0, relevance - 0.35)
            context_match["deep_focus_suppressed"] = True

        # Extraer palabras clave
        raw_words = re.findall(r"\b[a-zA-ZáéíóúÁÉÍÓÚñÑ_]{4,}\b", event.summary)
        keywords = list({w.lower() for w in raw_words})[:8]

        # 5. Determinar si califica como relevante superando los umbrales configurados
        is_relevant = (
            relevance >= cfg.min_relevance_threshold
            and confidence >= cfg.min_confidence_threshold
        )

        reason = (
            f"Evaluación proactiva: Relevancia={relevance:.2f}, Urgencia={urgency:.2f}, Confianza={confidence:.2f}. "
            f"Umbral mínimo de relevancia={cfg.min_relevance_threshold:.2f}."
        )
        if not is_relevant:
            reason += " Evento descartado por baja relevancia o confianza."

        return RelevanceAssessment(
            relevance=relevance,
            urgency=urgency,
            confidence=confidence,
            is_relevant=is_relevant,
            reason=reason,
            context_match=context_match,
            topic_keywords=keywords,
        )
