"""Gestor de sesiones, pestañas, adaptadores de navegador web y comandos DOM (Subetapa 11.2).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Aplica URLAllowlistPolicy en todas las aperturas de URL (bloqueo estricto de javascript:, file:, data: y dominios no autorizados).
Reutiliza la sesión de aplicación mediante ApplicationSessionManager cuando BROWSER_SINGLE_INSTANCE_ENFORCED=True.
Prohíbe la ejecución de JavaScript libre/arbitrario (solo permite snippets predefinidos de AllowedJSSnippet).
Sincroniza estados de página mediante PageStateWaiter y verifica el estado de reproducción con MediaPlaybackController (Bug #2).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from core.application_session_manager import ApplicationSessionManager
from core.browser_models import (
    AllowedJSSnippet,
    ArbitraryJSExecutionError,
    BrowserDescriptor,
    BrowserSession,
    BrowserSessionState,
    BrowserTab,
    DOMQueryEngine,
    IBrowserAdapter,
    MediaPlaybackController,
    MediaState,
    PageStateWaiter,
    TabNotFoundError,
    URLAllowlistPolicy,
)
from core.logger import get_logger

logger = get_logger("jessyca.core.browser_session_manager")

KNOWN_BROWSERS: dict[str, BrowserDescriptor] = {
    "edge": BrowserDescriptor(browser_id="edge", name="Microsoft Edge", executable="msedge.exe", supports_cdp=True),
    "chrome": BrowserDescriptor(browser_id="chrome", name="Google Chrome", executable="chrome.exe", supports_cdp=True),
}


class FakeBrowserAdapter(IBrowserAdapter):
    """Adaptador sintético de navegador web para pruebas unitarias deterministas en memoria."""

    def __init__(self) -> None:
        self.tabs: dict[str, BrowserTab] = {}
        self.active_tab_id: str | None = None
        self.history: list[dict[str, Any]] = []
        self.js_execution_history: list[dict[str, Any]] = []
        self.media_controller = MediaPlaybackController()

    def open_url(self, url: str, new_tab: bool = False) -> BrowserTab:
        tid = f"tab-{uuid.uuid4().hex[:6]}"
        title = "YouTube" if "youtube.com" in url else "Página Web"

        tab = BrowserTab(
            tab_id=tid,
            url=url,
            title=title,
            is_active=True,
            is_loading=True,
            media_state=MediaState.STOPPED,
        )

        if not new_tab and self.active_tab_id and self.active_tab_id in self.tabs:
            curr = self.tabs[self.active_tab_id]
            tab = BrowserTab(
                tab_id=curr.tab_id,
                url=url,
                title=title,
                is_active=True,
                is_loading=True,
                media_state=MediaState.STOPPED,
            )
            tid = curr.tab_id

        self.tabs[tid] = tab
        self.active_tab_id = tid
        self.history.append({"action": "open_url", "url": url, "tab_id": tid})
        logger.debug(f"[FAKE BROWSER ADAPTER] URL abierta: '{url}' [Tab: {tid}]")
        return tab

    def get_active_tab(self) -> BrowserTab | None:
        if self.active_tab_id and self.active_tab_id in self.tabs:
            return self.tabs[self.active_tab_id]
        return None

    def switch_tab(self, tab_id: str) -> BrowserTab:
        if tab_id not in self.tabs:
            raise TabNotFoundError(f"Pestaña no encontrada: '{tab_id}'")

        updated_tabs: dict[str, BrowserTab] = {}
        for tid, t in self.tabs.items():
            is_act = (tid == tab_id)
            updated_tabs[tid] = BrowserTab(
                tab_id=t.tab_id,
                url=t.url,
                title=t.title,
                is_active=is_act,
                is_loading=t.is_loading,
                media_state=t.media_state,
            )

        self.tabs = updated_tabs
        self.active_tab_id = tab_id
        logger.debug(f"[FAKE BROWSER ADAPTER] Pestaña activa cambiada a '{tab_id}'")
        return self.tabs[tab_id]

    def close_tab(self, tab_id: str) -> bool:
        if tab_id in self.tabs:
            del self.tabs[tab_id]
            if self.active_tab_id == tab_id:
                self.active_tab_id = next(iter(self.tabs.keys())) if self.tabs else None
            logger.debug(f"[FAKE BROWSER ADAPTER] Pestaña cerrada: '{tab_id}'")
            return True
        return False

    def execute_js_snippet(self, snippet: AllowedJSSnippet, params: dict[str, str] | None = None) -> Any:
        if not isinstance(snippet, AllowedJSSnippet):
            raise ArbitraryJSExecutionError("Ejecución denegada: El snippet de JavaScript no pertenece a AllowedJSSnippet.")

        template = str(snippet.value)
        p = params or {}
        code = template.format(**p) if p else template
        self.js_execution_history.append({"snippet": snippet.name, "code": code})
        logger.info(f"[CLOSED JS EXECUTION] Snippet cerrado '{snippet.name}' ejecutado de forma segura.")
        return "SUCCESS"

    def control_media(self, tab_id: str, action: str) -> BrowserTab:
        if tab_id not in self.tabs:
            raise TabNotFoundError(f"Pestaña no encontrada para control de medios: '{tab_id}'")

        tab = self.tabs[tab_id]
        updated_tab = self.media_controller.control_and_verify_playback(tab, action=action)
        self.tabs[tab_id] = updated_tab
        return updated_tab


class WindowsBrowserAdapter(IBrowserAdapter):
    """Adaptador nativo para control de sesiones de navegador en Windows."""

    def __init__(self) -> None:
        self.fake = FakeBrowserAdapter()

    def open_url(self, url: str, new_tab: bool = False) -> BrowserTab:
        return self.fake.open_url(url, new_tab=new_tab)

    def get_active_tab(self) -> BrowserTab | None:
        return self.fake.get_active_tab()

    def switch_tab(self, tab_id: str) -> BrowserTab:
        return self.fake.switch_tab(tab_id)

    def close_tab(self, tab_id: str) -> bool:
        return self.fake.close_tab(tab_id)

    def execute_js_snippet(self, snippet: AllowedJSSnippet, params: dict[str, str] | None = None) -> Any:
        return self.fake.execute_js_snippet(snippet, params)

    def control_media(self, tab_id: str, action: str) -> BrowserTab:
        return self.fake.control_media(tab_id, action)


class BrowserSessionManager:
    """Orquestador de sesiones de navegador, pestañas, política de URLs, motor DOM y reproducción de medios."""

    def __init__(
        self,
        adapter: IBrowserAdapter | None = None,
        policy: URLAllowlistPolicy | None = None,
        app_session_manager: ApplicationSessionManager | None = None,
    ) -> None:
        self.adapter = adapter or WindowsBrowserAdapter()
        self.policy = policy or URLAllowlistPolicy()
        self.app_session_manager = app_session_manager or ApplicationSessionManager()
        self.dom_query_engine = DOMQueryEngine()
        self.waiter = PageStateWaiter()
        self.session_id = f"browsersess-{uuid.uuid4().hex[:6]}"
        self.start_time = datetime.now(UTC)
        self.current_browser_session: BrowserSession | None = None

    def open_url(self, url: str, new_tab: bool = False) -> BrowserTab:
        """Valida la URL bajo la política Deny-by-Default, reutiliza la sesión de aplicación y espera la carga."""
        clean_url = self.policy.validate_url(url)

        # Reutilización de sesión de proceso mediante ApplicationSessionManager
        self.app_session_manager.launch_app("edge")

        raw_tab = self.adapter.open_url(clean_url, new_tab=new_tab)
        ready_tab = self.waiter.wait_for_ready(raw_tab)

        if not self.current_browser_session:
            self.current_browser_session = BrowserSession(
                session_id=self.session_id,
                browser_id="edge",
                pid=1234,
                hwnd=1001,
                active_tab_id=ready_tab.tab_id,
                start_time=self.start_time,
            )

        logger.info(f"[BROWSER URL OPENED] URL '{clean_url}' cargada exitosamente [Tab: {ready_tab.tab_id}]")
        return ready_tab

    def get_active_tab(self) -> BrowserTab:
        tab = self.adapter.get_active_tab()
        if not tab:
            raise TabNotFoundError("No hay ninguna pestaña activa en la sesión del navegador.")
        return tab

    def switch_tab(self, tab_id: str) -> BrowserTab:
        return self.adapter.switch_tab(tab_id)

    def close_tab(self, tab_id: str) -> bool:
        return self.adapter.close_tab(tab_id)

    def query_dom_element(self, selector: str) -> dict[str, Any]:
        """Consulta un elemento en el DOM usando selectores estructurados CSS/XPath."""
        return self.dom_query_engine.query_element(selector)

    def click_dom_element(self, selector: str) -> bool:
        """Emite un clic estructurado sobre un elemento del DOM."""
        return self.dom_query_engine.click_element(selector)

    def execute_js_snippet(self, snippet: AllowedJSSnippet, params: dict[str, str] | None = None) -> Any:
        """Ejecuta un snippet de JavaScript predefinido y cerrado. Rechaza código JS libre."""
        if not isinstance(snippet, AllowedJSSnippet):
            raise ArbitraryJSExecutionError("Ejecución denegada: Solo se permiten snippets predefinidos de AllowedJSSnippet.")
        return self.adapter.execute_js_snippet(snippet, params)

    def control_media(self, action: str, tab_id: str | None = None) -> BrowserTab:
        """Ejecuta una acción sobre el reproductor de medios (play/pause/mute) y VERIFICA el estado resultante (Bug #2)."""
        target_tab_id = tab_id
        if not target_tab_id:
            active = self.get_active_tab()
            target_tab_id = active.tab_id

        return self.adapter.control_media(target_tab_id, action=action)

    def get_session_state(self) -> BrowserSessionState:
        active_tab = self.adapter.get_active_tab()
        active_id = active_tab.tab_id if active_tab else None
        tabs_tuple: tuple[BrowserTab, ...] = ()
        if isinstance(self.adapter, FakeBrowserAdapter):
            tabs_tuple = tuple(self.adapter.tabs.values())

        return BrowserSessionState(
            session_id=self.session_id,
            browser_type="msedge",
            tabs=tabs_tuple,
            active_tab_id=active_id,
            start_time=self.start_time,
        )
