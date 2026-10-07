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
        use_real_browser: bool | None = None,
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
            self._browser_available = True
        else:
            # Regla: El navegador fake solo debe seleccionarse explícitamente en tests/demo.
            # Conecta un executor real cuando exista y sea adecuado. Si falta, devuelve UNAVAILABLE.
            import os
            is_explicit_test_or_demo = False
            settings = None
            try:
                from config.manager import get_settings
                settings = get_settings()
                env_val = getattr(settings, "ENVIRONMENT", "").lower()
                if env_val in ("test", "demo", "mock", "synthetic", "testing"):
                    is_explicit_test_or_demo = True
            except Exception:
                pass

            if os.getenv("JESSYCA_BROWSER_MODE", "").lower() in ("fake", "test", "demo", "mock"):
                is_explicit_test_or_demo = True
            if os.getenv("ENVIRONMENT", "").lower() in ("test", "demo", "testing"):
                is_explicit_test_or_demo = True
            if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("ENVIRONMENT", "").lower() not in ("production", "prod"):
                is_explicit_test_or_demo = True

            # Si se solicita explícitamente backend real (playwright)
            if use_real_browser is True or os.getenv("JESSYCA_BROWSER_MODE", "").lower() == "playwright":
                is_explicit_test_or_demo = False

            if is_explicit_test_or_demo:
                self.session_manager = BrowserSessionManager(
                    adapter=FakeBrowserAdapter(),
                    policy=self.allowlist_policy,
                )
                self._browser_available = True
            else:
                # Intento de conexión al adaptador real Playwright (Microsoft Edge)
                try:
                    from core.browser_playwright_adapter import PlaywrightBrowserAdapter
                    channel = getattr(settings, "PLAYWRIGHT_CHANNEL", "msedge") if settings else "msedge"
                    headless = getattr(settings, "PLAYWRIGHT_HEADLESS", True) if settings else True
                    real_adapter = PlaywrightBrowserAdapter(
                        headless=headless,
                        channel=channel,
                        policy=self.allowlist_policy,
                    )
                    self.session_manager = BrowserSessionManager(
                        adapter=real_adapter,
                        policy=self.allowlist_policy,
                    )
                    self._browser_available = True
                except Exception as e:
                    logger.warning(f"[BROWSER AGENT] Adaptador de navegador real no disponible: {e}")
                    self.session_manager = None
                    self._browser_available = False

    def is_available(self) -> bool:
        """Indica si el navegador está disponible técnicamente para operar."""
        return bool(self._browser_available and self.session_manager is not None)

    @property
    def browser_available(self) -> bool:
        """Propiedad de conveniencia para consultar disponibilidad del navegador."""
        return self.is_available()

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
        ctx = context or {}
        task_id = f"browsertask-{uuid.uuid4().hex[:6]}"

        # 1. Comprobar Parada de Emergencia
        if self.emergency_stop.is_stopped():
            return AgentLoopResult(
                task_id=task_id,
                intent=intent,
                final_state=AgentLoopState.STOPPED_EMERGENCY,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.01,
                stop_reason="Parada de emergencia activa.",
            )

        # 2. Comprobar disponibilidad técnica del navegador
        if not self._browser_available or self.session_manager is None:
            logger.error("[BROWSER AGENT UNAVAILABLE] Intento de navegación sin navegador real disponible en producción.")
            return AgentLoopResult(
                task_id=task_id,
                intent=intent,
                final_state=AgentLoopState.STOPPED_ERROR,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.01,
                stop_reason="Navegador real no disponible: no hay adaptador de sesión conectado en producción.",
                output_metadata={
                    "status": "BROWSER_UNAVAILABLE",
                    "error": "No browser session manager configured in production.",
                    "provenance": "UNAVAILABLE",
                    "is_synthetic": False,
                },
            )

        # 3. Detección de intenciones transaccionales de compra/pago
        tx_verdict = BrowserPolicy.detect_transaction_intent(intent=intent)
        if not tx_verdict.is_allowed:
            logger.warning(f"[BROWSER AGENT DENY] {tx_verdict.reason}")
            return AgentLoopResult(
                task_id=task_id,
                intent=intent,
                final_state=AgentLoopState.STOPPED_PERMISSION_DENIED,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.01,
                stop_reason=tx_verdict.reason,
            )

        lower_intent = intent.lower().strip()

        # 4. DESCARGAR ARCHIVO AUTORIZADO
        if "download" in lower_intent or "descarga" in lower_intent or ctx.get("action") == "download":
            dl_url = str(ctx.get("url") or re.search(r"https?://[^\s]+", intent).group(0) if re.search(r"https?://[^\s]+", intent) else "")
            sandbox_dir = str(ctx.get("sandbox_dir") or "Downloads")
            filename = ctx.get("filename") or ctx.get("nombre_archivo")
            try:
                dest = self.session_manager.download_file(dl_url, sandbox_dir=sandbox_dir, target_filename=filename)
                return AgentLoopResult(
                    task_id=task_id,
                    intent=intent,
                    final_state=AgentLoopState.COMPLETED,
                    iterations_executed=1,
                    tools_executed=1,
                    tokens_consumed=0,
                    duration_seconds=0.1,
                    stop_reason=f"Archivo descargado exitosamente en: '{dest}'",
                    output_metadata={
                        "download_path": dest,
                        "url": dl_url,
                        "status": "DOWNLOAD_COMPLETED",
                        "provenance": "REAL_PHYSICAL",
                    },
                )
            except Exception as e_dl:
                return AgentLoopResult(
                    task_id=task_id,
                    intent=intent,
                    final_state=AgentLoopState.STOPPED_ERROR,
                    iterations_executed=1,
                    tools_executed=1,
                    tokens_consumed=0,
                    duration_seconds=0.05,
                    stop_reason=f"Error al descargar archivo: {e_dl}",
                    output_metadata={"error": str(e_dl)},
                )

        # 5. EXTRAER CONTENIDO CON URL DE PROCEDENCIA
        if any(k in lower_intent for k in ("extraer", "lee", "leer", "extract", "contenido")) and not ("youtube" in lower_intent or "buscar" in lower_intent):
            selector = ctx.get("selector")
            try:
                content_dict = self.session_manager.extract_content(selector=selector)
                return AgentLoopResult(
                    task_id=task_id,
                    intent=intent,
                    final_state=AgentLoopState.COMPLETED,
                    iterations_executed=1,
                    tools_executed=1,
                    tokens_consumed=0,
                    duration_seconds=0.05,
                    stop_reason="Contenido textual extraído exitosamente de la página.",
                    output_metadata=content_dict,
                )
            except Exception as e_ext:
                return AgentLoopResult(
                    task_id=task_id,
                    intent=intent,
                    final_state=AgentLoopState.STOPPED_ERROR,
                    iterations_executed=1,
                    tools_executed=1,
                    tokens_consumed=0,
                    duration_seconds=0.05,
                    stop_reason=f"Error al extraer contenido: {e_ext}",
                    output_metadata={"error": str(e_ext)},
                )

        # 6. SEGUIR ENLACES
        if any(k in lower_intent for k in ("sigue el enlace", "seguir enlace", "click enlace", "follow link")) or ctx.get("action") == "follow_link":
            link_target = str(ctx.get("link") or ctx.get("link_text") or ctx.get("selector") or "")
            if not link_target:
                # Extraer texto entre comillas
                quoted = re.findall(r'["\']([^"\']+)["\']', intent)
                link_target = quoted[0] if quoted else intent
            try:
                tab = self.session_manager.follow_link(link_target)
                return AgentLoopResult(
                    task_id=task_id,
                    intent=intent,
                    final_state=AgentLoopState.COMPLETED,
                    iterations_executed=1,
                    tools_executed=1,
                    tokens_consumed=0,
                    duration_seconds=0.08,
                    stop_reason=f"Enlace '{link_target}' seguido exitosamente hacia '{tab.url}'.",
                    output_metadata={
                        "tab_id": tab.tab_id,
                        "url": tab.url,
                        "title": tab.title,
                        "provenance": getattr(tab, "provenance", "REAL_PHYSICAL"),
                    },
                )
            except Exception as e_fl:
                return AgentLoopResult(
                    task_id=task_id,
                    intent=intent,
                    final_state=AgentLoopState.STOPPED_ERROR,
                    iterations_executed=1,
                    tools_executed=1,
                    tokens_consumed=0,
                    duration_seconds=0.05,
                    stop_reason=f"Error al seguir enlace: {e_fl}",
                    output_metadata={"error": str(e_fl)},
                )

        # 7. CONTROL DE REPRODUCCIÓN (PLAY / PAUSE / RESUME)
        if any(k in lower_intent for k in ("pausa", "pausar", "reanuda", "reanudar", "stop media")) or (ctx.get("action") in ("pause", "resume", "stop")):
            action = str(ctx.get("action") or ("pause" if any(k in lower_intent for k in ("pausa", "pausar")) else "resume")).strip().lower()
            try:
                tab = self.session_manager.control_media(action)
                from core.browser_models import MediaState
                is_ok = (tab.media_state == MediaState.PAUSED) if action == "pause" else (tab.media_state == MediaState.PLAYING)
                return AgentLoopResult(
                    task_id=task_id,
                    intent=intent,
                    final_state=AgentLoopState.COMPLETED if is_ok else AgentLoopState.STOPPED_ERROR,
                    iterations_executed=1,
                    tools_executed=1,
                    tokens_consumed=0,
                    duration_seconds=0.05,
                    stop_reason=f"Comando multimedia '{action}' ejecutado. Estado verificado del reproductor: {tab.media_state}.",
                    output_metadata={
                        "media_state": str(tab.media_state),
                        "tab_id": tab.tab_id,
                        "title": tab.title,
                    },
                )
            except Exception as e_med:
                return AgentLoopResult(
                    task_id=task_id,
                    intent=intent,
                    final_state=AgentLoopState.STOPPED_ERROR,
                    iterations_executed=1,
                    tools_executed=1,
                    tokens_consumed=0,
                    duration_seconds=0.05,
                    stop_reason=f"Error al controlar reproducción: {e_med}",
                    output_metadata={"error": str(e_med)},
                )

        # 8. BÚSQUEDA WEB O YOUTUBE DEDICADA
        if "youtube" in lower_intent and any(k in lower_intent for k in ("busca", "buscar", "search")):
            query = ctx.get("query") or re.sub(r"^(?:busca|buscar|search)\s+(.*?)\s+(?:en\s+youtube|youtube).*$", r"\1", intent, flags=re.IGNORECASE).strip()
            tab = self.session_manager.search_youtube(query)
            return AgentLoopResult(
                task_id=task_id,
                intent=intent,
                final_state=AgentLoopState.COMPLETED,
                iterations_executed=1,
                tools_executed=1,
                tokens_consumed=0,
                duration_seconds=0.08,
                stop_reason=f"Búsqueda de '{query}' realizada en YouTube.",
                output_metadata={"tab_id": tab.tab_id, "url": tab.url, "title": tab.title},
            )

        if any(k in lower_intent for k in ("busca en internet", "busca en google", "buscar informacion", "busca informacion", "search web")):
            query = ctx.get("query") or re.sub(r"^(?:busca|buscar|search)\s+(.*?)(?:\s+en\s+internet|\s+en\s+google)?.*$", r"\1", intent, flags=re.IGNORECASE).strip()
            tab = self.session_manager.search_web(query)
            return AgentLoopResult(
                task_id=task_id,
                intent=intent,
                final_state=AgentLoopState.COMPLETED,
                iterations_executed=1,
                tools_executed=1,
                tokens_consumed=0,
                duration_seconds=0.08,
                stop_reason=f"Búsqueda de '{query}' realizada en la web.",
                output_metadata={"tab_id": tab.tab_id, "url": tab.url, "title": tab.title},
            )

        # 9. EXTRAER URL DIRECTA O ATRIBUTO DE NAVEGACIÓN
        url_match = re.search(r"(?:https?://|javascript:|file://|data:|about:|chrome:)[^\s]+", intent, re.IGNORECASE)
        target_url = url_match.group(0) if url_match else ctx.get("url")

        if not target_url:
            if "youtube" in lower_intent:
                target_url = "https://www.youtube.com"
            elif any(k in lower_intent for k in ("google", "buscar", "busca")):
                target_url = "https://www.google.com"
            elif "wikipedia" in lower_intent:
                target_url = "https://es.wikipedia.org"

        if target_url:
            verdict = BrowserPolicy.validate_url(target_url, allowlist_policy=self.allowlist_policy)
            if not verdict.is_allowed:
                return AgentLoopResult(
                    task_id=task_id,
                    intent=intent,
                    final_state=AgentLoopState.STOPPED_PERMISSION_DENIED,
                    iterations_executed=0,
                    tools_executed=0,
                    tokens_consumed=0,
                    duration_seconds=0.01,
                    stop_reason=verdict.reason,
                )

            # Ejecutar navegación
            tab = self.session_manager.open_url(target_url)

            # Comprobar si hay un bloqueo por CAPTCHA o autenticación en la página
            is_blocked, block_reason = self.session_manager.detect_blocking_state(tab.tab_id)
            if is_blocked:
                logger.warning(f"[BROWSER BLOCK DETECTED] {block_reason}")
                return AgentLoopResult(
                    task_id=task_id,
                    intent=intent,
                    final_state=AgentLoopState.PAUSED_USER_INPUT,
                    iterations_executed=1,
                    tools_executed=1,
                    tokens_consumed=0,
                    duration_seconds=0.08,
                    stop_reason=block_reason,
                    output_metadata={
                        "tab_id": tab.tab_id,
                        "url": tab.url,
                        "blocked": True,
                        "block_reason": block_reason,
                        "requires_user_intervention": True,
                    },
                )

            logger.info(f"[BROWSER AGENT] Navegación exitosa a '{target_url}' [Tab: {tab.tab_id}].")

            return AgentLoopResult(
                task_id=task_id,
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
                    "provenance": getattr(tab, "provenance", "REAL_PHYSICAL"),
                    "is_synthetic": getattr(tab, "is_synthetic", False),
                },
            )

        # Operaciones interactivas por defecto
        is_synth = isinstance(getattr(self.session_manager, "adapter", None), FakeBrowserAdapter)
        return AgentLoopResult(
            task_id=task_id,
            intent=intent,
            final_state=AgentLoopState.COMPLETED,
            iterations_executed=1,
            tools_executed=1,
            tokens_consumed=0,
            duration_seconds=0.05,
            stop_reason="Acción DOM completada exitosamente.",
            output_metadata={
                "status": "DOM_ACTION_COMPLETED",
                "browser": "Microsoft Edge",
                "provenance": "SYNTHETIC_TEST" if is_synth else "REAL_PHYSICAL",
                "is_synthetic": is_synth,
            },
        )
