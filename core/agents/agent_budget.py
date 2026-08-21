"""Presupuestos específicos para agentes especializados (agent_budget.py - Fase 7).

Define configuraciones de presupuesto delimitadas por rol y riesgo.
"""

from __future__ import annotations

from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk
from core.control_plane.models import AgentBudget


def create_desktop_agent_budget(
    max_steps: int = 15,
    max_time: float = 60.0,
    max_actions: int = 20,
    max_risk: TaskActionRisk = TaskActionRisk.DANGEROUS,
    max_retries: int = 3,
) -> AgentBudget:
    """Presupuesto por defecto para DesktopAgent (automatización de interfaz y visión)."""
    return AgentBudget.create(
        max_steps=max_steps,
        max_time=max_time,
        max_actions=max_actions,
        max_risk=max_risk,
        max_retries=max_retries,
        required_autonomy_level=AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
    )


def create_system_agent_budget(
    max_steps: int = 5,
    max_time: float = 15.0,
    max_actions: int = 5,
    max_risk: TaskActionRisk = TaskActionRisk.READ_ONLY,
    max_retries: int = 2,
) -> AgentBudget:
    """Presupuesto por defecto para SystemAgent (estrictamente READ ONLY para diagnósticos)."""
    return AgentBudget.create(
        max_steps=max_steps,
        max_time=max_time,
        max_actions=max_actions,
        max_risk=max_risk,
        max_retries=max_retries,
        required_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
    )


def create_file_agent_budget(
    max_steps: int = 10,
    max_time: float = 30.0,
    max_actions: int = 10,
    max_risk: TaskActionRisk = TaskActionRisk.MEDIUM_RISK,
    max_retries: int = 3,
) -> AgentBudget:
    """Presupuesto por defecto para FileAgent (acotado al sandbox de archivos)."""
    return AgentBudget.create(
        max_steps=max_steps,
        max_time=max_time,
        max_actions=max_actions,
        max_risk=max_risk,
        max_retries=max_retries,
        required_autonomy_level=AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
    )


def create_browser_agent_budget(
    max_steps: int = 8,
    max_time: float = 30.0,
    max_actions: int = 10,
    max_risk: TaskActionRisk = TaskActionRisk.MEDIUM_RISK,
    max_retries: int = 2,
) -> AgentBudget:
    """Presupuesto por defecto para BrowserAgent (navegación web acotada en Microsoft Edge)."""
    return AgentBudget.create(
        max_steps=max_steps,
        max_time=max_time,
        max_actions=max_actions,
        max_risk=max_risk,
        max_retries=max_retries,
        required_autonomy_level=AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
    )
