"""Enrutador de agentes especializados (agent_router.py - Fase 8: Agent Router).

Responde a la pregunta: ¿QUÉ AGENTE ACTÚA? (a diferencia de ModelRouter que responde ¿qué modelo piensa?).
Selecciona determinísticamente entre DesktopAgent, SystemAgent y FileAgent.

GARANTÍA DE SEGURIDAD:
- AgentRouter NO concede permisos por sí mismo.
- NO amplía las capacidades de los agentes.
- Respeta estrictamente el AgentBudget y retorna NEEDS_CLARIFICATION ante ambigüedad.
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar

from core.agents.agent_routing_policy import (
    AgentRoutingContext,
    AgentRoutingDecision,
    AgentRoutingPolicy,
    AgentRoutingStatus,
    AgentType,
)
from core.agents.base_agent import BaseSpecializedAgent
from core.agents.browser_agent import BrowserAgent
from core.agents.desktop_agent import DesktopAgent
from core.agents.file_agent import FileAgent
from core.agents.system_agent import SystemAgent
from core.logger import get_logger

logger = get_logger("jessyca.agents.router")


class AgentRouter:
    """Enrutador determinista que asigna solicitudes al agente especializado correspondiente."""

    _instance: ClassVar[AgentRouter | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        desktop_agent: DesktopAgent | None = None,
        system_agent: SystemAgent | None = None,
        file_agent: FileAgent | None = None,
        browser_agent: BrowserAgent | None = None,
    ) -> None:
        self.desktop_agent = desktop_agent or DesktopAgent()
        self.system_agent = system_agent or SystemAgent()
        self.file_agent = file_agent or FileAgent()
        self.browser_agent = browser_agent or BrowserAgent()

        self._agents_map: dict[AgentType, BaseSpecializedAgent] = {
            AgentType.DESKTOP: self.desktop_agent,
            AgentType.SYSTEM: self.system_agent,
            AgentType.FILE: self.file_agent,
            AgentType.BROWSER: self.browser_agent,
        }

    @classmethod
    def get_instance(cls) -> AgentRouter:
        """Obtiene la instancia singleton global del AgentRouter."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = AgentRouter()
            return cls._instance

    def route(
        self,
        context_or_text: AgentRoutingContext | str,
    ) -> AgentRoutingDecision:
        """Determina qué agente especializado debe actuar ante la solicitud dada."""
        if isinstance(context_or_text, str):
            ctx = AgentRoutingContext(user_input=context_or_text)
        else:
            ctx = context_or_text

        decision = AgentRoutingPolicy.evaluate(ctx)

        logger.debug(
            f"[AGENT ROUTER] '{ctx.user_input}' -> {decision.status} "
            f"(Agente: {decision.agent_name}, Confianza: {decision.confidence:.2f})"
        )
        return decision

    def get_agent_for_intent(
        self,
        intent: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[BaseSpecializedAgent | None, AgentRoutingDecision]:
        """Retorna la instancia del agente especializado y la decisión de enrutamiento formal."""
        ctx = AgentRoutingContext(user_input=intent, metadata=context or {})
        decision = self.route(ctx)

        if decision.status == AgentRoutingStatus.ROUTED and decision.agent_type:
            agent = self._agents_map.get(decision.agent_type)
            return agent, decision

        return None, decision


def get_agent_router() -> AgentRouter:
    """Acceso helper a la instancia global de AgentRouter."""
    return AgentRouter.get_instance()
