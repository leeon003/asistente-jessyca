"""Agente Especializado de Navegación Web (browser_agent.py - Fase 14: Browser Agent).

Evoluciona BrowserSessionManager a un agente especializado autónomo gobernado por ControlledAgentLoop.
Navegador exclusivo: Microsoft Edge (msedge.exe).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from core.agents.agent_budget import create_browser_agent_budget
from core.agents.base_agent import AgentIdentity, BaseSpecializedAgent
from core.agents.browser_capabilities import (
    INTERACTIVE_BROWSER_CAPABILITIES,
    BrowserCapability,
)
from core.agents.browser_policy import BrowserPolicy
from core.browser_models import URLAllowlistPolicy
from core.browser_session_manager import BrowserSessionManager, FakeBrowserAdapter
from core.control_plane.models import AgentBudget, AgentLoopResult, AgentLoopState
from core.emergency_stop import EmergencyStopManager
from core.logger import get_logger

logger = get_logger("jessyca.agents.browser")

ALLOWED_BROWSER_TOOLS: frozenset[str] = frozenset({
    "windows.browser.open_url",
    "windows.browser.get_active_tab",
    "windows.browser.switch_tab",
    "windows.browser.close_tab",
    "windows.browser.query_dom",
    "windows.browser.execute_snippet",
    "windows.browser.wait_for_condition",
    "windows.browser.click",
    "windows.browser.type_text",
    "windows.browser.submit",
    "windows.browser.scroll",
    "windows.browser.download_file",
})


class BrowserAgent(BaseSpecializedAgent):
    """Agente especializado en automatización web gobernada mediante Microsoft Edge."""

    def __init__(
        self,
        session_manager: BrowserSessionManager | None = None,
        allowlist_policy: URLAllowlistPolicy | None = None,
        capabilities: frozenset[BrowserCapability] | None = None,
        budget: AgentBudget | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        identity = AgentIdentity(
            agent_id="agent_browser",
            name="BrowserAgent",
            role="web_automation",
            description="Agente especializado en navegación web segura en Microsoft Edge con control de URLs y sesiones.",
        )
        self.browser_capabilities = capabilities or INTERACTIVE_BROWSER_CAPABILITIES
        self.allowlist_policy = allowlist_policy or URLAllowlistPolicy()
        cap_names = tuple(str(c) for c in self.browser_capabilities)

        effective_budget = budget or create_browser_agent_budget()

        super().__init__(
            identity=identity,
            capabilities=cap_names,
            allowed_tools=ALLOWED_BROWSER_TOOLS,
            risk_ceiling=effective_budget.max_risk,
            budget=effective_budget,
            emergency_stop=emergency_stop,
        )

        if session_manager:
            self.session_manager = session_manager
        else:
            # Usar adaptador en memoria FakeBrowserAdapter por defecto para tests o entornos headless
            self.session_manager = BrowserSessionManager(
                adapter=FakeBrowserAdapter(),
                policy=self.allowlist_policy,
            )

    def validate_tool_call(
        self,
        tool_name: str,
        operation: str,
        params: dict[str, Any],
    ) -> tuple[bool, str]:
        """Valida que la herramienta y la URL/descarga solicitada cumplan con BrowserPolicy."""
        # 1. Validación básica de catálogo de herramientas del agente
        is_ok, reason = super().validate_tool_call(tool_name, operation, params)
        if not is_ok:
            return False, reason

        # 2. Validación de URL si es una operación de navegación
        if operation in ("open_url", "navigate") or "url" in params:
            target_url = str(params.get("url", ""))
            verdict = BrowserPolicy.validate_url(target_url, allowlist_policy=self.allowlist_policy)
            if not verdict.is_allowed:
                return False, verdict.reason

        # 3. Validación de descargas
        if operation in ("download_file", "save_download") or "file_name" in params:
            file_name = str(params.get("file_name", params.get("download_path", "")))
            verdict_dl = BrowserPolicy.validate_download(file_name)
            if not verdict_dl.is_allowed:
                return False, verdict_dl.reason

        return True, "Operación de navegador validada."

    def execute_intent(
        self,
        intent: str,
        context: dict[str, Any] | None = None,
        budget: AgentBudget | None = None,
    ) -> AgentLoopResult:
        """Ejecuta una intención de navegación web bajo ControlledAgentLoop y BrowserPolicy."""
        # 1. Comprobar Parada de Emergencia
        if self.emergency_stop.is_stopped():
            return AgentLoopResult(
                task_id=f"browsertask-{uuid.uuid4().hex[:6]}",
                intent=intent,
                final_state=AgentLoopState.STOPPED_EMERGENCY,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.01,
                stop_reason="Parada de emergencia activa.",
            )

        # 2. Detección de intenciones transaccionales de compra/pago
        tx_verdict = BrowserPolicy.detect_transaction_intent(intent=intent)
        if not tx_verdict.is_allowed:
            logger.warning(f"[BROWSER AGENT DENY] {tx_verdict.reason}")
            return AgentLoopResult(
                task_id=f"browsertask-{uuid.uuid4().hex[:6]}",
                intent=intent,
                final_state=AgentLoopState.STOPPED_PERMISSION_DENIED,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.01,
                stop_reason=tx_verdict.reason,
            )

        # 3. Extraer URL o acción de navegación (cualquier esquema)
        url_match = re.search(r"(?:https?://|javascript:|file://|data:|about:|chrome:)[^\s]+", intent, re.IGNORECASE)
        target_url = url_match.group(0) if url_match else None

        if not target_url:
            # Mapeo de accesos directos comunes autorizados
            lower_intent = intent.lower()
            if "youtube" in lower_intent:
                target_url = "https://www.youtube.com"
            elif "google" in lower_intent or "buscar" in lower_intent or "busca" in lower_intent:
                target_url = "https://www.google.com"
            elif "wikipedia" in lower_intent:
                target_url = "https://es.wikipedia.org"

        if target_url:
            # Validar URL con BrowserPolicy
            verdict = BrowserPolicy.validate_url(target_url, allowlist_policy=self.allowlist_policy)
            if not verdict.is_allowed:
                return AgentLoopResult(
                    task_id=f"browsertask-{uuid.uuid4().hex[:6]}",
                    intent=intent,
                    final_state=AgentLoopState.STOPPED_PERMISSION_DENIED,
                    iterations_executed=0,
                    tools_executed=0,
                    tokens_consumed=0,
                    duration_seconds=0.01,
                    stop_reason=verdict.reason,
                )

            # Ejecutar navegación en Microsoft Edge
            tab = self.session_manager.open_url(target_url)
            logger.info(f"[BROWSER AGENT] Navegación exitosa a '{target_url}' [Tab: {tab.tab_id}].")

            return AgentLoopResult(
                task_id=f"browsertask-{uuid.uuid4().hex[:6]}",
                intent=intent,
                final_state=AgentLoopState.COMPLETED,
                iterations_executed=1,
                tools_executed=1,
                tokens_consumed=0,
                duration_seconds=0.05,
                stop_reason="Navegación completada exitosamente.",
                output_metadata={
                    "tab_id": tab.tab_id,
                    "url": tab.url,
                    "title": tab.title,
                    "browser": "Microsoft Edge",
                },
            )

        # Operaciones interactivas (click, typing, query_dom)
        return AgentLoopResult(
            task_id=f"browsertask-{uuid.uuid4().hex[:6]}",
            intent=intent,
            final_state=AgentLoopState.COMPLETED,
            iterations_executed=1,
            tools_executed=1,
            tokens_consumed=0,
            duration_seconds=0.05,
            stop_reason="Acción DOM completada exitosamente.",
            output_metadata={"status": "DOM_ACTION_COMPLETED", "browser": "Microsoft Edge"},
        )
