"""Agente especializado en automatización de escritorio y visión (desktop_agent.py - Fase 7: Specialized Agents).

Restringido exclusivamente a herramientas de visión e interacción con la interfaz de usuario de Windows.
No tiene acceso a herramientas de sistema ni del sistema de archivos.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.agents.agent_budget import create_desktop_agent_budget
from core.agents.base_agent import AgentIdentity, BaseSpecializedAgent
from core.control_plane.models import AgentBudget
from core.emergency_stop import EmergencyStopManager
from core.tool_planner import ControlledToolPlanner

DESKTOP_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "windows.desktop.take_screenshot",
    "desktop.screenshot",
    "screenshot",
    "take_screenshot",
    "windows.desktop.ocr_screen",
    "desktop.ocr",
    "ocr",
    "ocr_screen",
    "windows.desktop.inspect_ui",
    "desktop.ui_inspect",
    "ui_inspection",
    "inspect_ui",
    "windows.desktop.set_focus",
    "desktop.focus",
    "focus",
    "set_focus",
    "windows.desktop.click",
    "desktop.click",
    "click",
    "windows.desktop.type_text",
    "desktop.type",
    "type",
    "type_text",
    "windows.desktop.drag",
    "desktop.drag",
    "drag",
})


class DesktopAgent(BaseSpecializedAgent):
    """Agente especializado exclusivamente en visión e interacción con el escritorio de Windows."""

    def __init__(
        self,
        budget: AgentBudget | None = None,
        planner: ControlledToolPlanner | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        action_executor: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
        action_verifier: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        identity = AgentIdentity(
            agent_id="agent_desktop",
            name="DesktopAgent",
            description="Agente especializado en visión, OCR e interacción de interfaz gráfica en Windows.",
            role="desktop_automation",
        )
        capabilities = (
            "screenshot",
            "ocr",
            "ui_inspection",
            "focus",
            "click",
            "type",
            "drag",
        )
        effective_budget = budget or create_desktop_agent_budget()

        super().__init__(
            identity=identity,
            capabilities=capabilities,
            allowed_tools=DESKTOP_ALLOWED_TOOLS,
            risk_ceiling=effective_budget.max_risk,
            budget=effective_budget,
            planner=planner,
            emergency_stop=emergency_stop,
            action_executor=action_executor,
            action_verifier=action_verifier,
        )
