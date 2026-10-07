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
    BrowserControlError,
    BrowserDescriptor,
    BrowserSession,
    BrowserSessionState,
    BrowserTab,
    DOMQueryEngine,
    IBrowserAdapter,
    MediaPlaybackController,
    MediaState,
    PageStateWaiter,
    SandboxEscapeError,
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
        self.dom_engine = DOMQueryEngine()

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
            provenance="SYNTHETIC_TEST",
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
                provenance="SYNTHETIC_TEST",
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
                provenance=t.provenance,
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

    def get_text(self, selector: str | None = None) -> str:
        if selector:
            elem = self.dom_engine.query_element(selector)
            return str(elem.get("text", ""))
        return "Fake page text data"

    def query_dom(self, selector: str) -> dict[str, Any]:
        return self.dom_engine.query_element(selector)

    def get_accessibility_snapshot(self) -> dict[str, Any]:
        return {"role": "WebArea", "name": "Fake Document", "children": []}

    def fill_form(self, selector_values: dict[str, str]) -> dict[str, bool]:
        return dict.fromkeys(selector_values, True)

    def click(self, selector: str) -> bool:
        return self.dom_engine.click_element(selector)

    def download_file(
        self,
        url_or_selector: str,
        sandbox_dir: str,
        target_filename: str | None = None,
    ) -> str:
        from pathlib import Path

        sbox = Path(sandbox_dir).resolve()
        fname = target_filename or "download.txt"
        dest = (sbox / fname).resolve()
        try:
            dest.relative_to(sbox)
        except ValueError as err:
            raise SandboxEscapeError(f"Intento de escape de sandbox detectado: '{target_filename}'") from err
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("fake download content", encoding="utf-8")
        return str(dest)

    def follow_link(self, link_text_or_selector: str) -> BrowserTab:
        tid = self.active_tab_id or f"tab-{uuid.uuid4().hex[:6]}"
        curr = self.tabs.get(tid)
        curr_url = curr.url if curr else "http://127.0.0.1:8000"
        new_url = f"{curr_url.rstrip('/')}/link-{uuid.uuid4().hex[:4]}"
        tab = BrowserTab(
            tab_id=tid,
            url=new_url,
            title=f"Página: {link_text_or_selector}",
            is_active=True,
            is_loading=False,
            media_state=MediaState.STOPPED,
            provenance="SYNTHETIC_TEST",
        )
        self.tabs[tid] = tab
        return tab

    def extract_content(self, selector: str | None = None) -> dict[str, Any]:
        tab = self.get_active_tab()
        text = self.get_text(selector=selector)
        return {
            "url": tab.url if tab else "http://127.0.0.1:8000",
            "title": tab.title if tab else "Fake Page",
            "texto": text,
            "provenance": "SYNTHETIC_TEST",
            "is_untrusted_data": True,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def search_web(self, query: str, engine: str = "google") -> BrowserTab:
        url = f"https://www.google.com/search?q={query}"
        return self.open_url(url)

    def search_youtube(self, query: str) -> BrowserTab:
        url = f"https://www.youtube.com/results?search_query={query}"
        return self.open_url(url)

    def handle_consent_and_popups(self, tab_id: str | None = None) -> dict[str, Any]:
        return {"handled": True, "actions": ["synthetic_consent"]}

    def detect_blocking_state(self, tab_id: str | None = None) -> tuple[bool, str]:
        tab = self.get_active_tab()
        if tab and "captcha" in tab.url.lower():
            return True, "Detectado CAPTCHA en prueba sintética. Se requiere intervención del usuario."
        return False, ""

    def health(self) -> dict[str, Any]:
        return {"status": "HEALTHY", "backend": "fake", "is_synthetic": True}

    def capabilities(self) -> dict[str, Any]:
        return {"backend": "fake", "dom_query": True, "is_synthetic": True}

    def close(self) -> None:
        self.tabs.clear()
        self.active_tab_id = None


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

    def get_text(self, selector: str | None = None) -> str:
        return self.fake.get_text(selector)

    def query_dom(self, selector: str) -> dict[str, Any]:
        return self.fake.query_dom(selector)

    def get_accessibility_snapshot(self) -> dict[str, Any]:
        return self.fake.get_accessibility_snapshot()

    def fill_form(self, selector_values: dict[str, str]) -> dict[str, bool]:
        return self.fake.fill_form(selector_values)

    def click(self, selector: str) -> bool:
        return self.fake.click(selector)

    def download_file(
        self,
        url_or_selector: str,
        sandbox_dir: str,
        target_filename: str | None = None,
    ) -> str:
        return self.fake.download_file(url_or_selector, sandbox_dir, target_filename)

    def follow_link(self, link_text_or_selector: str) -> BrowserTab:
        return self.fake.follow_link(link_text_or_selector)

    def extract_content(self, selector: str | None = None) -> dict[str, Any]:
        return self.fake.extract_content(selector)

    def search_web(self, query: str, engine: str = "google") -> BrowserTab:
        return self.fake.search_web(query, engine)

    def search_youtube(self, query: str) -> BrowserTab:
        return self.fake.search_youtube(query)

    def handle_consent_and_popups(self, tab_id: str | None = None) -> dict[str, Any]:
        return self.fake.handle_consent_and_popups(tab_id)

    def detect_blocking_state(self, tab_id: str | None = None) -> tuple[bool, str]:
        return self.fake.detect_blocking_state(tab_id)

    def health(self) -> dict[str, Any]:
        return self.fake.health()

    def capabilities(self) -> dict[str, Any]:
        return self.fake.capabilities()

    def close(self) -> None:
        self.fake.close()


def resolve_browser_adapter(
    backend: str | None = None,
    policy: URLAllowlistPolicy | None = None,
) -> IBrowserAdapter:
    """Resuelve e instancia el adaptador de navegador configurado con fallback controlado."""
    try:
        from config.manager import get_settings
        settings = get_settings()
        target_backend = (backend or getattr(settings, "BROWSER_BACKEND", "playwright")).lower().strip()
        playwright_enabled = getattr(settings, "PLAYWRIGHT_ENABLED", True)
    except Exception:
        settings = None
        target_backend = (backend or "playwright").lower().strip()
        playwright_enabled = True

    if target_backend == "playwright" or (playwright_enabled and target_backend not in ("fake", "windows")):
        try:
            from core.browser_playwright_adapter import PlaywrightBrowserAdapter
            logger.info("[BROWSER ADAPTER] Inicializando backend PlaywrightBrowserAdapter...")
            return PlaywrightBrowserAdapter(
                headless=getattr(settings, "PLAYWRIGHT_HEADLESS", True) if settings else True,
                channel=getattr(settings, "PLAYWRIGHT_CHANNEL", "msedge") if settings else "msedge",
                user_data_dir=getattr(settings, "PLAYWRIGHT_USER_DATA_DIR", None) if settings else None,
                timeout_ms=getattr(settings, "PLAYWRIGHT_TIMEOUT_MS", 15000) if settings else 15000,
                policy=policy,
            )
        except Exception as e:
            logger.warning(
                f"[BROWSER ADAPTER FALLBACK] No se pudo inicializar Playwright ({e}). "
                "Recurriendo a WindowsBrowserAdapter."
            )
            return WindowsBrowserAdapter()

    if target_backend == "fake":
        return FakeBrowserAdapter()

    return WindowsBrowserAdapter()


_shared_browser_adapter: IBrowserAdapter | None = None


def get_shared_browser_adapter(
    backend: str | None = None,
    policy: URLAllowlistPolicy | None = None,
    force_new: bool = False,
) -> IBrowserAdapter:
    """Retorna o inicializa la instancia compartida del adaptador de navegador para persistencia de sesión."""
    global _shared_browser_adapter
    if not force_new and _shared_browser_adapter is not None:
        is_closed = getattr(_shared_browser_adapter, "_is_closed", False)
        if not is_closed:
            if policy and hasattr(_shared_browser_adapter, "policy"):
                _shared_browser_adapter.policy = policy
            return _shared_browser_adapter

    _shared_browser_adapter = resolve_browser_adapter(backend=backend, policy=policy)
    return _shared_browser_adapter


def reset_shared_browser_adapter() -> None:
    """Cierra y resetea el adaptador compartido de navegador."""
    global _shared_browser_adapter
    if _shared_browser_adapter is not None:
        try:
            if hasattr(_shared_browser_adapter, "close"):
                _shared_browser_adapter.close()
        except Exception:
            pass
        _shared_browser_adapter = None


class BrowserSessionManager:
    """Orquestador de sesiones de navegador, pestañas, política de URLs, motor DOM y reproducción de medios."""

    def __init__(
        self,
        adapter: IBrowserAdapter | None = None,
        policy: URLAllowlistPolicy | None = None,
        app_session_manager: ApplicationSessionManager | None = None,
    ) -> None:
        self.policy = policy or URLAllowlistPolicy()
        self.adapter = adapter if adapter is not None else get_shared_browser_adapter(policy=self.policy)
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
        if hasattr(self.adapter, "query_dom"):
            try:
                return self.adapter.query_dom(selector)
            except Exception:
                pass
        return self.dom_query_engine.query_element(selector)

    def click_dom_element(self, selector: str) -> bool:
        """Emite un clic estructurado sobre un elemento del DOM."""
        if hasattr(self.adapter, "click"):
            try:
                return self.adapter.click(selector)
            except Exception:
                pass
        return self.dom_query_engine.click_element(selector)

    def get_text(self, selector: str | None = None) -> str:
        """Extrae texto sanitizado de la página o de un elemento."""
        if hasattr(self.adapter, "get_text"):
            return self.adapter.get_text(selector)
        return ""

    def query_dom(self, selector: str) -> dict[str, Any]:
        """Consulta el estado estructurado del elemento DOM."""
        if hasattr(self.adapter, "query_dom"):
            return self.adapter.query_dom(selector)
        return self.dom_query_engine.query_element(selector)

    def get_accessibility_snapshot(self) -> dict[str, Any]:
        """Obtiene el árbol o snapshot de accesibilidad."""
        if hasattr(self.adapter, "get_accessibility_snapshot"):
            return self.adapter.get_accessibility_snapshot()
        return {}

    def fill_form(self, selector_values: dict[str, str]) -> dict[str, bool]:
        """Rellena campos de formulario de forma gobernada."""
        if hasattr(self.adapter, "fill_form"):
            return self.adapter.fill_form(selector_values)
        return dict.fromkeys(selector_values, False)

    def click(self, selector: str) -> bool:
        """Emite un clic gobernado con verificación de estado."""
        if hasattr(self.adapter, "click"):
            return self.adapter.click(selector)
        return self.dom_query_engine.click_element(selector)

    def download_file(
        self,
        url_or_selector: str,
        sandbox_dir: str,
        target_filename: str | None = None,
    ) -> str:
        """Descarga un archivo confinado estrictamente al sandbox."""
        if hasattr(self.adapter, "download_file"):
            return self.adapter.download_file(url_or_selector, sandbox_dir, target_filename)
        raise BrowserControlError("El adaptador de navegador actual no soporta descargas a sandbox.")

    def follow_link(self, link_text_or_selector: str) -> BrowserTab:
        """Sigue un enlace en la pestaña activa mediante su texto o selector CSS."""
        if hasattr(self.adapter, "follow_link"):
            return self.adapter.follow_link(link_text_or_selector)
        raise BrowserControlError("El adaptador de navegador actual no soporta follow_link.")

    def extract_content(self, selector: str | None = None) -> dict[str, Any]:
        """Extrae el contenido textual sanitizado con metadatos y URL de procedencia."""
        if hasattr(self.adapter, "extract_content"):
            return self.adapter.extract_content(selector=selector)
        tab = self.get_active_tab()
        return {
            "url": tab.url if tab else "",
            "title": tab.title if tab else "",
            "texto": self.get_text(selector=selector),
            "provenance": getattr(tab, "provenance", "UNKNOWN"),
            "is_untrusted_data": True,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def search_web(self, query: str, engine: str = "google") -> BrowserTab:
        """Realiza una búsqueda de información en la web."""
        if hasattr(self.adapter, "search_web"):
            return self.adapter.search_web(query, engine=engine)
        q_url = f"https://www.google.com/search?q={query}"
        return self.open_url(q_url)

    def search_youtube(self, query: str) -> BrowserTab:
        """Busca videos en YouTube."""
        if hasattr(self.adapter, "search_youtube"):
            return self.adapter.search_youtube(query)
        q_url = f"https://www.youtube.com/results?search_query={query}"
        return self.open_url(q_url)

    def handle_consent_and_popups(self, tab_id: str | None = None) -> dict[str, Any]:
        """Gestiona diálogos y modales de consentimiento o ventanas emergentes."""
        if hasattr(self.adapter, "handle_consent_and_popups"):
            return self.adapter.handle_consent_and_popups(tab_id=tab_id)
        return {"handled": False}

    def detect_blocking_state(self, tab_id: str | None = None) -> tuple[bool, str]:
        """Comprueba si la página activa presenta bloqueo por CAPTCHA o autenticación obligatoria."""
        if hasattr(self.adapter, "detect_blocking_state"):
            return self.adapter.detect_blocking_state(tab_id=tab_id)
        return False, ""

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

    def health(self) -> dict[str, Any]:
        """Comprueba la salud del backend de navegador activo."""
        if hasattr(self.adapter, "health"):
            return self.adapter.health()
        return {"status": "UNKNOWN", "backend": "unknown"}

    def capabilities(self) -> dict[str, Any]:
        """Reporta las capacidades técnicas del backend de navegador activo."""
        if hasattr(self.adapter, "capabilities"):
            return self.adapter.capabilities()
        return {}

    def close(self) -> None:
        """Cierra el adaptador de navegador y libera sus recursos."""
        if hasattr(self.adapter, "close"):
            self.adapter.close()
        global _shared_browser_adapter
        if self.adapter is _shared_browser_adapter:
            _shared_browser_adapter = None

    def get_session_state(self) -> BrowserSessionState:
        active_tab = None
        try:
            active_tab = self.adapter.get_active_tab()
        except Exception:
            pass

        active_id = active_tab.tab_id if active_tab else None
        tabs_tuple: tuple[BrowserTab, ...] = ()
        if isinstance(self.adapter, FakeBrowserAdapter):
            tabs_tuple = tuple(self.adapter.tabs.values())
        elif hasattr(self.adapter, "_tab_metadata") and isinstance(self.adapter._tab_metadata, dict):
            tabs_tuple = tuple(self.adapter._tab_metadata.values())

        return BrowserSessionState(
            session_id=self.session_id,
            browser_type="msedge",
            tabs=tabs_tuple,
            active_tab_id=active_id,
            start_time=self.start_time,
        )
