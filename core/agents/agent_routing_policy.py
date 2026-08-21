"""Políticas y contextos de enrutamiento para agentes especializados (agent_routing_policy.py - Fase 8: Agent Router).

Determina de forma determinista qué agente actúa según la intención del usuario y su contexto operativo.
GARANTÍA DE SEGURIDAD:
El enrutador de agentes NO concede permisos, NO amplía capacidades y retorna NEEDS_CLARIFICATION ante ambigüedad.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentType(StrEnum):
    """Tipos de agentes especializados disponibles en el sistema."""

    DESKTOP = "desktop"
    SYSTEM = "system"
    FILE = "file"
    BROWSER = "browser"


class AgentRoutingStatus(StrEnum):
    """Estados del veredicto de enrutamiento de agentes."""

    ROUTED = "ROUTED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class AgentRoutingDecision:
    """Decisión inmutable emitida por el AgentRouter."""

    status: AgentRoutingStatus
    agent_type: AgentType | None = None
    agent_name: str | None = None
    confidence: float = 1.0
    reason: str = ""
    clarification_prompt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "agent_type": str(self.agent_type) if self.agent_type else None,
            "agent_name": self.agent_name,
            "confidence": self.confidence,
            "reason": self.reason,
            "clarification_prompt": self.clarification_prompt,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AgentRoutingContext:
    """Contexto estructurado inmutable para la selección del agente ejecutor."""

    user_input: str
    active_window: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Patrones léxicos y semánticos deterministas por tipo de agente
DESKTOP_PATTERNS = [
    r"\b(pantalla|screenshot|captura|mira|mirar|observa|interfaz|ventana|click|clic|escribe|tipea|foco|focus|arrastra|drag|ocr|boton|botón)\b",
    r"\b(que ves|qué ves|muestra la pantalla|revisa la pantalla|lee la pantalla)\b",
]

SYSTEM_PATTERNS = [
    r"\b(ram|memoria|cpu|procesos|proceso|diagnostico|diagnóstico|rendimiento|sistema|metricas|métricas|telemetria|telemetría|estado del sistema|hardware|disco)\b",
    r"\b(cuanta ram|cuánta ram|uso de cpu|temperatura|revisa memoria|revisa procesos|lista de procesos)\b",
]

FILE_PATTERNS = [
    r"\b(archivo|archivos|fichero|ficheros|carpeta|directorio|sandbox|guardar|guarde|crea un archivo|crear archivo|leer archivo|lee archivo|escribir archivo|buscar archivo)\b",
    r"\b(\.txt|\.json|\.csv|\.log|\.md|\.pdf)\b",
]

BROWSER_PATTERNS = [
    r"\b(navegador|browser|edge|web|sitio web|pagina web|página web|url|link|enlace|youtube|google|wikipedia|navega|abre la web|busca en la web)\b",
    r"\b(https?://[^\s]+)\b",
]


class AgentRoutingPolicy:
    """Motor de políticas deterministas para la selección de agentes especializados."""

    @classmethod
    def evaluate(cls, context: AgentRoutingContext) -> AgentRoutingDecision:
        """Evalúa el contexto y retorna la decisión formal de enrutamiento."""
        text = context.user_input.lower().strip()
        if not text:
            return AgentRoutingDecision(
                status=AgentRoutingStatus.NEEDS_CLARIFICATION,
                reason="La solicitud está vacía.",
                clarification_prompt="¿En qué puedo ayudarte? Puedes pedirme capturar la pantalla, revisar el sistema, navegar en la web o trabajar con archivos.",
            )

        # 1. Puntuación por coincidencias de patrones
        desktop_score = cls._score_patterns(text, DESKTOP_PATTERNS)
        system_score = cls._score_patterns(text, SYSTEM_PATTERNS)
        file_score = cls._score_patterns(text, FILE_PATTERNS)
        browser_score = cls._score_patterns(text, BROWSER_PATTERNS)

        scores = [
            (AgentType.DESKTOP, "DesktopAgent", desktop_score),
            (AgentType.SYSTEM, "SystemAgent", system_score),
            (AgentType.FILE, "FileAgent", file_score),
            (AgentType.BROWSER, "BrowserAgent", browser_score),
        ]

        # Ordenar descendentemente por puntuación
        scores.sort(key=lambda x: x[2], reverse=True)
        top_agent, top_name, top_score = scores[0]
        second_agent, second_name, second_score = scores[1]

        # 2. Si no hubo ninguna coincidencia
        if top_score == 0:
            return AgentRoutingDecision(
                status=AgentRoutingStatus.NEEDS_CLARIFICATION,
                reason="No se detectaron intenciones claras correspondientes a los agentes especializados.",
                clarification_prompt="No estoy seguro de qué agente debe encargarse. ¿Deseas interactuar con la pantalla, diagnosticar el sistema o gestionar archivos en el sandbox?",
            )

        # 3. Si hay empate exacto entre dos agentes (ambigüedad directa)
        if top_score > 0 and top_score == second_score:
            return AgentRoutingDecision(
                status=AgentRoutingStatus.NEEDS_CLARIFICATION,
                reason=f"Ambigüedad: La solicitud coincide igualmente con {top_name} y {second_name}.",
                clarification_prompt=f"Tu solicitud puede involucrar tanto a {top_name} como a {second_name}. ¿Podrías especificar qué acción deseas priorizar?",
            )

        # 4. Decisión determinista clara
        return AgentRoutingDecision(
            status=AgentRoutingStatus.ROUTED,
            agent_type=top_agent,
            agent_name=top_name,
            confidence=min(1.0, 0.7 + (top_score * 0.1)),
            reason=f"Coincidencia con capacidades de {top_name} (score: {top_score}).",
        )

    @staticmethod
    def _score_patterns(text: str, patterns: list[str]) -> int:
        score = 0
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            score += len(matches)
        return score
