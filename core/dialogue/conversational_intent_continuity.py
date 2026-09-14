"""Continuidad de Intención Conversacional (conversational_intent_continuity.py - Fase 64.3.2).

Permite que JESSYCA interprete con precisión órdenes de seguimiento deícticas y anafóricas
que dependen estrictamente del contexto conversacional inmediato:
- Pronombres y clíticos: "ciérralo", "ábrela", "páusala", "eso", "esa aplicación", "ese programa"
- Repetición y elipsis: "de nuevo", "otra vez", "repítelo"
- Detección rigurosa de ambigüedad (dos o más entidades candidatas -> CLARIFY)
- Caducidad temporal explícita (TTL) evitando usar contexto histórico arbitrario
- Anti-False Context: una acción fallida NUNCA se registra como contexto exitoso
- Invariante de NO-EJECUCIÓN: la resolución de contexto es puramente analítica, nunca
  llama al Dispatcher ni modifica el sistema operativo.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.dialogue.conversational_intent_continuity")


# ── MODELO DE CONTEXTO DE ACCIÓN INMEDIATA ───────────────────────────────────


@dataclass(frozen=True)
class ActionContext:
    """Representa el contexto mínimo indispensable de la última acción completada.

    Mantiene:
    - action_id: Identificador único de la acción ejecutada
    - action: Intención semántica ejecutada (ej. "open_application")
    - skill: Identificador de la skill responsable (ej. "windows.apps")
    - operation: Operación física despachada (ej. "launch_app")
    - target: Objetivo canónico o nombre de la aplicación (ej. "notepad")
    - result: Salida física o resultado verificado
    - status: Estado final de la acción (ej. "COMPLETED")
    - timestamp: Marca de tiempo de registro (segundos Unix)
    - entities: Entidades involucradas o mencionadas en el turno
    - ttl_seconds: Tiempo de vida máximo de vigencia contextual
    """

    action_id: str
    action: str
    skill: str
    operation: str
    target: str
    result: Any = None
    status: str = "COMPLETED"
    timestamp: float = field(default_factory=time.time)
    entities: tuple[str, ...] = ()
    ttl_seconds: float = 180.0

    def is_expired(self, current_time: float | None = None) -> bool:
        """Determina si la validez temporal del contexto de acción ha vencido."""
        now = current_time if current_time is not None else time.time()
        return (now - self.timestamp) > self.ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        """Serializa el contexto a un diccionario plano."""
        return {
            "action_id": self.action_id,
            "action": self.action,
            "skill": self.skill,
            "operation": self.operation,
            "target": self.target,
            "result": self.result,
            "status": self.status,
            "timestamp": self.timestamp,
            "entities": list(self.entities),
            "ttl_seconds": self.ttl_seconds,
            "is_expired": self.is_expired(),
        }


# ── RESULTADO FORMAL DE RESOLUCIÓN DE CONTINUIDAD ─────────────────────────────


@dataclass(frozen=True)
class ContinuityResolutionResult:
    """Resultado formal del análisis de continuidad contextual y referencias."""

    is_reference: bool
    resolved_intent: str | None = None
    resolved_parameters: dict[str, Any] = field(default_factory=dict)
    resolved_target: str | None = None
    resolved_targets: tuple[str, ...] = ()
    is_plural: bool = False
    resolved_skill: str | None = None
    resolved_operation: str | None = None
    is_ambiguous: bool = False
    is_expired: bool = False
    clarification_question: str | None = None
    confidence: float = 1.0
    reason: str | None = None


# ── MAPEOS DETERMINISTAS Y NORMALIZACIÓN DE ENTIDADES ──────────────────────────

_CANONICAL_APP_NAMES: dict[str, str] = {
    "notepad": "notepad",
    "bloc de notas": "notepad",
    "el bloc de notas": "notepad",
    "bloc notas": "notepad",
    "bloc": "notepad",
    "notas": "notepad",
    "calculadora": "calc",
    "la calculadora": "calc",
    "calc": "calc",
    "chrome": "chrome",
    "google chrome": "chrome",
    "el navegador": "chrome",
    "navegador": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "paint": "paint",
    "el paint": "paint",
    "cmd": "cmd",
    "terminal": "cmd",
    "consola": "cmd",
    "spotify": "spotify",
}

_DISPLAY_APP_NAMES: dict[str, str] = {
    "notepad": "Bloc de notas",
    "calc": "Calculadora",
    "chrome": "Chrome",
    "edge": "Edge",
    "paint": "Paint",
    "cmd": "CMD",
    "spotify": "Spotify",
    "browser": "Navegador",
}


def format_display_entity(target: str) -> str:
    """Formatea el nombre de la entidad para formulación natural de preguntas."""
    canon = _CANONICAL_APP_NAMES.get(target.strip().lower(), target.strip())
    return _DISPLAY_APP_NAMES.get(canon, target.capitalize())


# ── RESOLVEDOR DETERMINISTA DE CONTINUIDAD CONTEXTUAL ─────────────────────────


class ConversationalIntentContinuityResolver:
    """Analizador determinista para resolución de pronombres, elipsis y referencias deícticas."""

    _instance: ConversationalIntentContinuityResolver | None = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> ConversationalIntentContinuityResolver:
        with cls._lock:
            if cls._instance is None:
                cls._instance = ConversationalIntentContinuityResolver()
            return cls._instance

    # ── 1. EXTRACCIÓN DETERMINISTA DE ENTIDADES MENCIONADAS ──

    def extract_entities(self, text: str) -> list[str]:
        """Extrae de forma determinista entidades reconocibles mencionadas en el texto."""
        lower = text.lower().strip()
        entities: list[str] = []

        # Buscar por patrones de aplicaciones conocidas
        # Priorizar expresiones compuestas más largas primero
        sorted_patterns = sorted(_CANONICAL_APP_NAMES.keys(), key=len, reverse=True)
        already_matched_canonical: set[str] = set()

        for pat in sorted_patterns:
            pattern_regex = rf"\b{re.escape(pat)}\b"
            if re.search(pattern_regex, lower):
                canon = _CANONICAL_APP_NAMES[pat]
                if canon not in already_matched_canonical:
                    already_matched_canonical.add(canon)
                    entities.append(canon)

        return entities

    # ── 2. DETECCIÓN DE REFERENCIAS ANAFÓRICAS / DEÍCTICAS ──

    def detect_reference(self, user_input: str) -> tuple[bool, str | None, str | None]:
        """Determina si una entrada de usuario hace referencia anafórica a una acción o entidad previa.

        Retorna:
            (is_reference, verb_action_type, pronoun_or_phrase)
            verb_action_type puede ser: "close", "open", "pause", "repeat", "navigate"
        """
        lower = user_input.strip().lower()
        cleaned = re.sub(r"^(?:por\s+favor\s*,?|jessyca\s*,?|jessica\s*,?|oye\s*,?)\s*", "", lower).strip()
        cleaned = re.sub(r"\s*(?:por\s+favor|porfa|gracias)\s*$", "", cleaned).strip()

        # Si menciona explícitamente una entidad o aplicación concreta, NO es una referencia pura
        entities = self.extract_entities(cleaned)
        # Excepción: si el texto dice "cierra esa aplicación" o "abre ese programa", no son nombres propios
        if entities and not any(phrase in cleaned for phrase in ("esa aplicación", "ese programa", "esa app", "esa ventana")):
            return False, None, None

        # 2.1 Pronombre enclítico de Cierre:
        # Plurales: "ciérralos", "cierralos", "ciérralas", "cierralas", "cierra ambos", "cierra los dos"
        if re.match(
            r"^(?:ciérralos|cierralos|ciérralas|cierralas|cierra\s+ambos|cierra\s+ambas|cierra\s+los\s+dos|cierra\s+las\s+dos)$",
            cleaned,
        ):
            return True, "close", "los"

        # Singulares: "ciérralo", "ciérrala", "cierralo", "cierrala"
        if re.match(r"^(?:ciérralo|cierralo|ciérrala|cierrala)$", cleaned):
            return True, "close", "lo"

        # 2.2 Frases de Cierre con demostrativo: "cierra eso", "cierra esa aplicación", "cierra esa ventana"
        if re.match(
            r"^(?:cierra|apaga|termina|kill|detén|deten)\s+(?:eso|esto|aquello|esa\s+aplicaci[oó]n|ese\s+programa|esa\s+ventana|esa\s+app)$",
            cleaned,
        ):
            return True, "close", "eso"

        # 2.3 Pronombre enclítico de Apertura:
        # Plurales: "ábrelos", "abrelos", "ábrelas", "abrelas", "abre ambos", "abre los dos"
        if re.match(
            r"^(?:ábrelos|abrelos|ábrelas|abrelas|abre\s+ambos|abre\s+ambas|abre\s+los\s+dos|abre\s+las\s+dos)$",
            cleaned,
        ):
            return True, "open", "los"

        # Singulares: "ábrelo", "abrelo", "ábrela", "abrela"
        if re.match(r"^(?:ábrelo|abrelo|ábrela|abrela)$", cleaned):
            return True, "open", "lo"

        # 2.4 Frases de Apertura con demostrativo: "abre eso", "abre esa aplicación", "inicia eso"
        if re.match(
            r"^(?:abre|inicia|ejecuta|lanza)\s+(?:eso|esto|aquello|esa\s+aplicaci[oó]n|ese\s+programa|esa\s+ventana|esa\s+app)$",
            cleaned,
        ):
            return True, "open", "eso"

        # 2.5 Pausa / Detención Multimedia: "páusala", "pausala", "páusalo", "pausalo", "deténlo", "detenlo"
        if re.match(r"^(?:páusala|pausala|páusalo|pausalo|deténlo|detenlo|deténla|detenla|pára|para)$", cleaned):
            return True, "pause", "la"

        if re.match(r"^(?:pausa|det[eé]n|para)\s+(?:eso|la\s+m[uú]sica|el\s+v[ií]deo|la\s+canci[oó]n)$", cleaned):
            return True, "pause", "eso"

        # 2.6 Repetición / Elipsis de Acción: "de nuevo", "otra vez", "repítelo", "hazlo de nuevo"
        if cleaned in ("de nuevo", "otra vez", "repítelo", "repitelo", "hazlo de nuevo", "hazlo otra vez", "haz lo mismo", "repite"):
            return True, "repeat", "de_nuevo"

        # 2.7 Referencia locativa / espacial: "busca allí", "entra allí", "abre allí"
        if re.match(r"^(?:busca|entra|abre|mira)\s+(?:all[ií]|ah[ií])$", cleaned):
            return True, "navigate", "allí"

        return False, None, None

    # ── 3. RESOLUCIÓN CONTEXTUAL DE REFERENCIAS ──

    def resolve(
        self,
        user_input: str,
        action_context: ActionContext | None,
        ttl_seconds: float | None = None,
        current_time: float | None = None,
        active_session_apps: list[str] | None = None,
    ) -> ContinuityResolutionResult:
        """Resuelve deterministamente el significado y la intención de una orden contextual.

        Reglas estrictas:
        - Si no es referencia: devuelve is_reference=False.
        - Si no hay contexto previo: CLARIFY ("¿Qué aplicación deseas cerrar?").
        - Si el contexto expiró por TTL: CLARIFY ("El contexto anterior ya expiró...").
        - Si hay múltiples candidatos en contexto:
            * Pronombre plural ('ciérralos', 'ambos'): resuelve inequívocamente todas las entidades.
            * Pronombre singular ('ciérralo'): AMBIGUITY -> CLARIFY ("¿Cuál quieres que cierre, X o Y?").
        - Si el referente es inequívoco: produce la intención y parámetros resueltos sin ejecutar.
        """
        is_ref, action_type, pronoun = self.detect_reference(user_input)
        if not is_ref or action_type is None:
            return ContinuityResolutionResult(is_reference=False)

        logger.info(
            f"[CONTINUITY DETECTED] input='{user_input}' action_type='{action_type}' "
            f"pronoun='{pronoun}'"
        )

        is_plural_ref = pronoun in ("los", "las", "ambos", "ambas")

        # 3.1 Ausencia de contexto previo ("No inventar contexto")
        if action_context is None and not active_session_apps:
            logger.info("[CONTINUITY NO CONTEXT] Referencia recibida sin acción previa en memoria.")
            q = (
                "¿Qué aplicación deseas que cierre?"
                if action_type == "close"
                else "¿Qué deseas que abra?"
                if action_type == "open"
                else "¿Qué acción deseas realizar?"
            )
            return ContinuityResolutionResult(
                is_reference=True,
                is_ambiguous=True,
                clarification_question=q,
                reason="No prior action context available in this session.",
            )

        # 3.2 Contexto expirado por tiempo (TTL)
        effective_ttl = ttl_seconds if ttl_seconds is not None else (action_context.ttl_seconds if action_context else 180.0)
        now = current_time if current_time is not None else time.time()
        if action_context and (now - action_context.timestamp) > effective_ttl:
            logger.info(
                f"[CONTINUITY CONTEXT EXPIRED] Contexto expirado (edad={now - action_context.timestamp:.1f}s > TTL={effective_ttl}s)."
            )
            q = (
                "¿Qué aplicación deseas que cierre?"
                if action_type == "close"
                else "¿Qué aplicación deseas que abra?"
                if action_type == "open"
                else "¿Qué deseas hacer?"
            )
            return ContinuityResolutionResult(
                is_reference=True,
                is_expired=True,
                is_ambiguous=True,
                clarification_question=q,
                reason=f"Action context expired (age > {effective_ttl}s).",
            )

        # 3.3 Extracción de Candidatos y Detección de Ambigüedad / Pluralidad
        candidate_entities: list[str] = []

        if is_plural_ref:
            # Para orden plural ("ciérralos"), recopilar de entidades de turno o de apps abiertas en sesión
            raw_entities: list[str] = []
            if action_context and action_context.entities:
                raw_entities.extend(action_context.entities)
            elif action_context and action_context.target:
                raw_entities.append(action_context.target)

            if active_session_apps:
                for app in active_session_apps:
                    if app not in raw_entities:
                        raw_entities.append(app)

            for ent in raw_entities:
                canon = _CANONICAL_APP_NAMES.get(ent.lower(), ent.lower())
                if canon not in candidate_entities:
                    candidate_entities.append(canon)
        else:
            # Para orden singular ("ciérralo"):
            # Si el turno anterior contenía múltiples entidades explícitas ("Abre Chrome y Bloc de notas"),
            # entonces un "ciérralo" singular es intrínsecamente ambiguo entre ellas.
            if action_context and action_context.entities and len(action_context.entities) > 1:
                for ent in action_context.entities:
                    canon = _CANONICAL_APP_NAMES.get(ent.lower(), ent.lower())
                    if canon not in candidate_entities:
                        candidate_entities.append(canon)
            elif action_context and action_context.target:
                candidate_entities.append(_CANONICAL_APP_NAMES.get(action_context.target.lower(), action_context.target.lower()))

        # 3.3.1 Caso: Múltiples Candidatos con Pronombre Plural -> Éxito Multi-Target
        if len(candidate_entities) > 1 and is_plural_ref:
            logger.info(
                f"[CONTINUITY PLURAL RESOLVED] Múltiples referentes resueltos por orden plural: {candidate_entities}"
            )
            first_target = candidate_entities[0]
            target_list = list(candidate_entities)
            if action_type == "close":
                return ContinuityResolutionResult(
                    is_reference=True,
                    resolved_intent="close_application",
                    resolved_parameters={"app_name": first_target, "nombre_app": first_target, "targets": target_list},
                    resolved_target=first_target,
                    resolved_targets=tuple(candidate_entities),
                    is_plural=True,
                    resolved_skill="windows.apps",
                    resolved_operation="close_application",
                    confidence=1.0,
                    reason=f"Plural reference resolved to: {candidate_entities}",
                )
            if action_type == "open":
                return ContinuityResolutionResult(
                    is_reference=True,
                    resolved_intent="open_application",
                    resolved_parameters={"app_name": first_target, "nombre_app": first_target, "targets": target_list},
                    resolved_target=first_target,
                    resolved_targets=tuple(candidate_entities),
                    is_plural=True,
                    resolved_skill="windows.apps",
                    resolved_operation="launch_app",
                    confidence=1.0,
                    reason=f"Plural reference resolved to: {candidate_entities}",
                )

        # 3.3.2 Caso: Múltiples Candidatos con Pronombre Singular -> AMBIGÜEDAD (CLARIFY)
        if len(candidate_entities) > 1 and not is_plural_ref:
            logger.info(
                f"[CONTINUITY AMBIGUITY] Múltiples referentes activos ({candidate_entities}) con pronombre singular. "
                f"Solicitando aclaración sin ejecutar."
            )
            display_names = [format_display_entity(c) for c in candidate_entities]
            joined_options = f"{display_names[0]} o {display_names[1]}" if len(display_names) == 2 else ", ".join(display_names)
            verb_str = "cierre" if action_type == "close" else "abra"
            clarification = f"¿Cuál quieres que {verb_str}, {joined_options}?"
            return ContinuityResolutionResult(
                is_reference=True,
                is_ambiguous=True,
                clarification_question=clarification,
                reason=f"Multiple candidates detected with singular pronoun: {candidate_entities}",
            )

        # 3.4 Referente unívoco e inequívoco
        target = candidate_entities[0] if candidate_entities else (action_context.target if action_context else "app")

        # 3.4.1 Acción: Cierre ("ciérralo", "cierra eso", etc.)
        if action_type == "close":
            return ContinuityResolutionResult(
                is_reference=True,
                resolved_intent="close_application",
                resolved_parameters={"app_name": target, "nombre_app": target},
                resolved_target=target,
                resolved_skill="windows.apps",
                resolved_operation="close_application",
                confidence=1.0,
            )

        # 3.4.2 Acción: Apertura ("ábrelo", "abre eso", etc.)
        if action_type == "open":
            return ContinuityResolutionResult(
                is_reference=True,
                resolved_intent="open_application",
                resolved_parameters={"app_name": target, "nombre_app": target},
                resolved_target=target,
                resolved_skill="windows.apps",
                resolved_operation="launch_app",
                confidence=1.0,
            )

        # 3.4.3 Acción: Pausa Multimedia ("páusala", "pausalo", etc.)
        if action_type == "pause":
            media_target = target or "música"
            return ContinuityResolutionResult(
                is_reference=True,
                resolved_intent="pause_media",
                resolved_parameters={"target": media_target},
                resolved_target=media_target,
                resolved_skill="windows.media",
                resolved_operation="pause",
                confidence=1.0,
            )

        # 3.4.4 Acción: Repetición ("de nuevo", "otra vez", "repítelo")
        if action_type == "repeat":
            if action_context is None:
                return ContinuityResolutionResult(
                    is_reference=True,
                    is_ambiguous=True,
                    clarification_question="¿Qué acción deseas que repita?",
                    reason="No prior action context to repeat.",
                )
            return ContinuityResolutionResult(
                is_reference=True,
                resolved_intent=action_context.action,
                resolved_parameters={"app_name": target, "nombre_app": target},
                resolved_target=target,
                resolved_skill=action_context.skill,
                resolved_operation=action_context.operation,
                confidence=1.0,
            )

        # 3.4.5 Acción: Locativa ("busca allí")
        if action_type == "navigate":
            return ContinuityResolutionResult(
                is_reference=True,
                resolved_intent="browser_search",
                resolved_parameters={"query": target},
                resolved_target=target,
                resolved_skill="browser.search",
                resolved_operation="search",
                confidence=1.0,
            )

        return ContinuityResolutionResult(is_reference=False)


def get_continuity_resolver() -> ConversationalIntentContinuityResolver:
    """Helper factory para obtener la instancia singleton del ContinuityResolver."""
    return ConversationalIntentContinuityResolver.get_instance()


__all__ = [
    "ActionContext",
    "ContinuityResolutionResult",
    "ConversationalIntentContinuityResolver",
    "format_display_entity",
    "get_continuity_resolver",
]
