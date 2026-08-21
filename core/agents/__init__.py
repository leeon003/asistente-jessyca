"""Paquete de Agentes Especializados para Jessyca Windows MCP (core.agents - Fase 7, 8 & 9).

Exporta las clases base, modelos de identidad, presupuestos, agentes, enrutador y coordinación multi-agente:
- DesktopAgent: UI automation, OCR y visión.
- SystemAgent: Diagnósticos de sistema (estrictamente READ ONLY).
- FileAgent: Operaciones de archivos acotadas estrictamente a sandbox/.
- AgentRouter: Router que selecciona determinísticamente qué agente actúa.
- AgentCoordinator, TaskGraph, AgentMessage, DelegationPolicy: Colaboración controlada multi-agente.
"""

from __future__ import annotations

from core.agents.agent_budget import (
    create_desktop_agent_budget,
    create_file_agent_budget,
    create_system_agent_budget,
)
from core.agents.agent_coordinator import (
    AgentCoordinator,
)
from core.agents.agent_errors import (
    AgentError,
    AgentSecurityError,
    ReadOnlyViolationError,
    RiskCeilingExceededError,
    SandboxViolationError,
    ToolNotAllowedError,
)
from core.agents.agent_message import (
    AgentMessage,
    AgentMessageType,
)
from core.agents.agent_router import (
    AgentRouter,
    get_agent_router,
)
from core.agents.agent_routing_policy import (
    AgentRoutingContext,
    AgentRoutingDecision,
    AgentRoutingPolicy,
    AgentRoutingStatus,
    AgentType,
)
from core.agents.base_agent import (
    AgentIdentity,
    BaseSpecializedAgent,
)
from core.agents.browser_agent import (
    ALLOWED_BROWSER_TOOLS,
    BrowserAgent,
)
from core.agents.browser_capabilities import (
    INTERACTIVE_BROWSER_CAPABILITIES,
    READ_ONLY_BROWSER_CAPABILITIES,
    BrowserCapability,
)
from core.agents.browser_policy import (
    BrowserPolicy,
    BrowserPolicyVerdict,
)
from core.agents.delegation_policy import (
    ALLOWED_DELEGATIONS,
    MAX_DELEGATION_DEPTH,
    DelegationPolicy,
    DelegationVerdict,
)
from core.agents.desktop_agent import (
    DESKTOP_ALLOWED_TOOLS,
    DesktopAgent,
)
from core.agents.file_agent import (
    FILE_ALLOWED_TOOLS,
    FileAgent,
)
from core.agents.system_agent import (
    FORBIDDEN_WRITE_OPERATIONS,
    SYSTEM_ALLOWED_TOOLS,
    SystemAgent,
)
from core.agents.task_graph import (
    TaskGraph,
    TaskNode,
)

__all__ = [
    # Base e Identidad
    "AgentIdentity",
    "BaseSpecializedAgent",
    # Agentes Especializados
    "DesktopAgent",
    "SystemAgent",
    "FileAgent",
    "BrowserAgent",
    # Listas de Herramientas
    "DESKTOP_ALLOWED_TOOLS",
    "SYSTEM_ALLOWED_TOOLS",
    "FORBIDDEN_WRITE_OPERATIONS",
    "FILE_ALLOWED_TOOLS",
    "ALLOWED_BROWSER_TOOLS",
    # Capacidades y Políticas de Navegador
    "BrowserCapability",
    "READ_ONLY_BROWSER_CAPABILITIES",
    "INTERACTIVE_BROWSER_CAPABILITIES",
    "BrowserPolicy",
    "BrowserPolicyVerdict",
    # Presupuestos
    "create_desktop_agent_budget",
    "create_system_agent_budget",
    "create_file_agent_budget",
    # Excepciones
    "AgentError",
    "AgentSecurityError",
    "ToolNotAllowedError",
    "RiskCeilingExceededError",
    "SandboxViolationError",
    "ReadOnlyViolationError",
    # Enrutador de Agentes (Fase 8)
    "AgentType",
    "AgentRoutingStatus",
    "AgentRoutingDecision",
    "AgentRoutingContext",
    "AgentRoutingPolicy",
    "AgentRouter",
    "get_agent_router",
    # Colaboración y Delegación Multi-Agente (Fase 9)
    "AgentCoordinator",
    "TaskGraph",
    "TaskNode",
    "AgentMessage",
    "AgentMessageType",
    "DelegationPolicy",
    "DelegationVerdict",
    "ALLOWED_DELEGATIONS",
    "MAX_DELEGATION_DEPTH",
]
