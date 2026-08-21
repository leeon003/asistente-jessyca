"""Enrutador inteligente de intenciones a Skills (skill_router.py - Fase 28.5).

Determina deterministamente la Skill óptima para satisfacer una intención del usuario
considerando:
1. Intención semántica, verbos de acción y entidades.
2. Capacidades y herramientas declaradas.
3. Contexto de ejecución y compatibilidad.
4. Nivel de riesgo y disponibilidad (ENABLED / READY).
5. Detección y manejo formal de ambigüedad (solicitud de aclaración).
6. Blindaje contra manipulación por Prompt Injection.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. SKILL ROUTER != AUTHORIZATION (El enrutador solo selecciona; SecurityPipeline autoriza).
2. ANTE AMBIGÜEDAD MATERIAL, NO SE EJECUTAN ACCIONES ARBITRARIAS; SE SOLICITA ACLARACIÓN.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, ClassVar

from core.logger import get_logger
from skills.skill_models import (
    SkillDefinition,
    SkillStatus,
)
from skills.skill_registry import SkillRegistry, get_skill_registry

logger = get_logger("jessyca.skills.router")

PROMPT_INJECTION_REMOVAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(DAN|unrestricted|in\s+godmode)", re.IGNORECASE),
    re.compile(r"\[INST\].*?\[/INST\]", re.DOTALL | re.IGNORECASE),
    re.compile(r"<system>.*?</system>", re.DOTALL | re.IGNORECASE),
]

DOMAIN_KEYWORDS: dict[str, set[str]] = {
    "browser": {"busca", "buscar", "informacion", "nvidia", "google", "web", "internet", "youtube", "video", "pagina", "navegar"},
    "files": {"organiza", "organizar", "archivo", "archivos", "carpeta", "carpetas", "mover", "fichero", "ficheros", "disco"},
    "system": {"diagnostico", "sistema", "salud", "cpu", "ram", "memoria", "rendimiento", "estado"},
    "apps": {"abre", "abrir", "cerrar", "ejecuta", "ejecutar", "inicia", "iniciar", "aplicacion", "programa", "app"},
}


@dataclass(frozen=True)
class SkillRouteDecision:
    """Decisión detallada y estructurada del enrutamiento de intenciones."""

    skill: SkillDefinition | None
    confidence: float
    reason: str
    is_ambiguous: bool = False
    candidate_skills: tuple[tuple[SkillDefinition, float], ...] = ()
    requires_clarification: bool = False
    clarification_prompt: str = ""
    sanitized_intent: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillRouter:
    """Enrutador determinista y semántico de intenciones hacia Skills registradas."""

    _instance: ClassVar[SkillRouter | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self._lock = threading.RLock()
        self.registry = registry or get_skill_registry()

    @classmethod
    def get_instance(cls) -> SkillRouter:
        """Obtiene la instancia singleton global del enrutador de skills."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = SkillRouter()
            return cls._instance

    def _sanitize_intent(self, raw_intent: str) -> str:
        """Sanitiza el prompt del usuario eliminando patrones de inyección de instrucciones."""
        cleaned = raw_intent
        for pat in PROMPT_INJECTION_REMOVAL_PATTERNS:
            cleaned = pat.sub(" ", cleaned)
        return " ".join(cleaned.split()).strip()

    def resolve_routing(
        self,
        intent: str,
        context: dict[str, Any] | None = None,
        required_capability: str | None = None,
    ) -> SkillRouteDecision:
        """Resuelve la mejor Skill candidata o detecta ambigüedad para solicitar aclaración."""
        sanitized = self._sanitize_intent(intent)
        intent_clean = sanitized.lower()

        if not intent_clean:
            return SkillRouteDecision(
                skill=None,
                confidence=0.0,
                reason="Intención vacía o neutralizada por filtros de seguridad.",
                sanitized_intent=sanitized,
            )

        with self._lock:
            all_skills = self.registry.list_skills()
            # Filtrar solo skills habilitadas y activas
            available_skills = [
                s for s in all_skills
                if self.registry.get_status(s.skill_id) not in (
                    SkillStatus.DISABLED,
                    SkillStatus.INVALID,
                    SkillStatus.FAILED,
                    SkillStatus.UNVALIDATED,
                )
            ]

            # Filtrar por capability requerida si fue especificada
            if required_capability:
                req_cap_clean = required_capability.strip().lower()
                available_skills = [
                    s for s in available_skills
                    if any(c.lower() == req_cap_clean or req_cap_clean in c.lower() for c in s.capabilities)
                ]

            if not available_skills:
                return SkillRouteDecision(
                    skill=None,
                    confidence=0.0,
                    reason="No hay skills habilitadas o compatibles en el catálogo para esta solicitud.",
                    sanitized_intent=sanitized,
                )

            # 1. Coincidencia exacta por ID o nombre
            for sk in available_skills:
                if intent_clean == sk.skill_id.lower() or intent_clean == sk.name.lower():
                    return SkillRouteDecision(
                        skill=sk,
                        confidence=1.0,
                        reason=f"Coincidencia exacta con skill '{sk.skill_id}'.",
                        sanitized_intent=sanitized,
                    )

            # 2. Puntuación multi-factor
            intent_tokens = set(intent_clean.replace(".", " ").replace("_", " ").replace("-", " ").split())
            scored_candidates: list[tuple[SkillDefinition, float]] = []

            for sk in available_skills:
                score = self._compute_skill_score(sk, intent_clean, intent_tokens, context)
                if score >= 0.20:
                    scored_candidates.append((sk, score))

            if not scored_candidates:
                return SkillRouteDecision(
                    skill=None,
                    confidence=0.0,
                    reason="Ninguna skill disponible alcanzó el umbral mínimo de afinidad para esta intención.",
                    sanitized_intent=sanitized,
                )

            # Ordenar candidatos de mayor a menor puntuación
            scored_candidates.sort(key=lambda x: x[1], reverse=True)
            top_skill, top_score = scored_candidates[0]

            # 3. Detección de Ambigüedad Material
            if len(scored_candidates) > 1:
                second_skill, second_score = scored_candidates[1]
                # Si ambos tienen confianza alta y la diferencia es pequeña (< 0.15)
                if top_score >= 0.50 and second_score >= 0.50 and (top_score - second_score) < 0.15:
                    logger.info(
                        f"[SKILL ROUTER AMBIGUITY] Ambigüedad entre '{top_skill.skill_id}' ({top_score:.2f}) y '{second_skill.skill_id}' ({second_score:.2f})."
                    )
                    prompt = (
                        f"He encontrado varias opciones para '{sanitized}': "
                        f"1. {top_skill.name} ({top_skill.description}) "
                        f"2. {second_skill.name} ({second_skill.description}). "
                        "¿Cuál prefieres que utilice?"
                    )
                    return SkillRouteDecision(
                        skill=None,
                        confidence=top_score,
                        reason=f"Ambigüedad detectada entre '{top_skill.skill_id}' y '{second_skill.skill_id}'. Se requiere aclaración.",
                        is_ambiguous=True,
                        candidate_skills=tuple(scored_candidates[:3]),
                        requires_clarification=True,
                        clarification_prompt=prompt,
                        sanitized_intent=sanitized,
                    )

            confidence = min(0.98, max(0.50, top_score))
            return SkillRouteDecision(
                skill=top_skill,
                confidence=confidence,
                reason=f"Afinidad semántica con '{top_skill.skill_id}' (Score: {top_score:.2f}).",
                candidate_skills=tuple(scored_candidates[:3]),
                sanitized_intent=sanitized,
            )

    def _compute_skill_score(
        self,
        skill: SkillDefinition,
        intent_clean: str,
        intent_tokens: set[str],
        context: dict[str, Any] | None,
    ) -> float:
        """Calcula el score de afinidad semántica y contextual para una Skill."""
        score = 0.0
        sk_text = f"{skill.skill_id} {skill.name} {skill.description} {' '.join(skill.tags)} {' '.join(skill.capabilities)} {' '.join(skill.required_tools)}".lower()
        sk_tokens = set(sk_text.replace(".", " ").replace("_", " ").replace("-", " ").split())

        # Coincidencia de tokens
        common_tokens = intent_tokens.intersection(sk_tokens)
        if common_tokens:
            token_ratio = len(common_tokens) / max(len(intent_tokens), 1)
            score += token_ratio * 0.60

        # Coincidencia por dominios clave
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if any(kw in intent_clean for kw in keywords):
                if domain in skill.skill_id.lower() or any(domain in cap.lower() for cap in skill.capabilities):
                    score += 0.30

        # Subcadena en ID o nombre
        if skill.skill_id.lower() in intent_clean or skill.name.lower() in intent_clean:
            score += 0.25

        # Afinidad contextual
        if context:
            current_app = str(context.get("active_app", "")).lower()
            if current_app and current_app in sk_text:
                score += 0.15

        return min(1.0, score)

    def route_intent(
        self,
        intent: str,
        context: dict[str, Any] | None = None,
        required_capability: str | None = None,
    ) -> tuple[SkillDefinition | None, float, str]:
        """Interfaz determinista retrocompatible que retorna (SkillDefinition, confianza, razón)."""
        decision = self.resolve_routing(intent, context=context, required_capability=required_capability)
        return decision.skill, decision.confidence, decision.reason


def get_skill_router() -> SkillRouter:
    """Acceso helper al singleton global de SkillRouter."""
    return SkillRouter.get_instance()
