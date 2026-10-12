"""Adaptador de navegador basado en Playwright (core/browser_playwright_adapter.py - Fase I2).

GARANTÍAS Y REGLAS DE SEGURIDAD ABSOLUTAS:
1. Dependencia opcional fijada: Import perezoso de `playwright.sync_api`.
2. Aislamiento técnico: Hilo dedicado (_PlaywrightWorkerThread) que asegura 100% compatibilidad
   con entornos síncronos y asíncronos (evita el error 'Sync API inside asyncio loop').
3. Perfil de automatización separado: No comparte estado autenticado, cookies ni credenciales
   entre usuarios ni con perfiles personales de Microsoft Edge.
4. Soporte de canal: Detección y respeto del canal 'msedge' instalado en Windows.
5. Política Deny-by-Default: Validación estricta de URL inicial y de redirecciones post-navegación.
6. Datos no confiables: El contenido de páginas web es estrictamente DATA no confiable;
   no modifica permisos ni se interpreta como comandos de sistema. Sanitización de secretos.
7. Sandbox confinement: Descargas confinadas estrictamente a la raíz de sandbox sin escape (anti-traversal).
8. Cero ejecución de código arbitrario: Solo permite snippets cerrados de `AllowedJSSnippet`.
9. Cierre ordenado y deterministic health/capabilities reales.
"""

from __future__ import annotations

import os
import queue
import threading
import urllib.parse
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from core.browser_models import (
    AllowedJSSnippet,
    ArbitraryJSExecutionError,
    BrowserControlError,
    BrowserTab,
    DOMElementNotFoundError,
    IBrowserAdapter,
    MediaPlaybackController,
    MediaState,
    NavigationSecurityError,
    PlaywrightUnavailableError,
    SandboxEscapeError,
    TabNotFoundError,
    URLAllowlistPolicy,
)
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger("jessyca.core.browser_playwright_adapter")


class _PlaywrightWorkerThread:
    """Hilo de trabajo dedicado para aislar las llamadas síncronas de Playwright.

    Garantiza compatibilidad absoluta con loops de asyncio existentes y garantiza
    que todas las operaciones de Playwright ocurran en el hilo que inicializó el runtime.
    """

    def __init__(
        self,
        headless: bool = True,
        channel: str = "msedge",
        user_data_dir: Path | None = None,
        timeout_ms: int = 15000,
        policy: URLAllowlistPolicy | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.headless = headless
        self.channel = channel
        self.user_data_dir = user_data_dir
        self.timeout_ms = timeout_ms
        self.policy = policy
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()

        self._task_queue: queue.Queue[tuple[Callable[[], Any] | None, queue.Queue[tuple[bool, Any]]]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._is_running = False
        self._playwright_instance: Any = None
        self._browser_instance: Any = None
        self._context_instance: Any = None
        self._init_error: Exception | None = None
        self._browser_version: str = "UNKNOWN"

    def start(self) -> None:
        """Inicia el hilo de trabajo e inicializa Playwright y el navegador."""
        if self._is_running:
            return

        init_barrier = queue.Queue(maxsize=1)
        self._thread = threading.Thread(
            target=self._worker_loop,
            args=(init_barrier,),
            name="PlaywrightBrowserWorker",
            daemon=True,
        )
        self._thread.start()

        ok, result = init_barrier.get(timeout=30)
        if not ok:
            self._is_running = False
            raise result

        self._is_running = True

    def _worker_loop(self, init_barrier: queue.Queue[tuple[bool, Any]]) -> None:
        """Bucle principal de ejecución del hilo dedicado."""
        try:
            # Lazy import dentro del hilo dedicado
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as err:
                raise PlaywrightUnavailableError(
                    "La librería 'playwright' no está instalada en el entorno Python activo."
                ) from err

            self._playwright_instance = sync_playwright().start()

            # Intentar canal configurado (ej: msedge), con fallback controlado si no existe
            launch_channel = self.channel
            try:
                self._browser_instance = self._playwright_instance.chromium.launch(
                    channel=launch_channel,
                    headless=self.headless,
                )
            except Exception as e_channel:
                logger.warning(
                    f"[PLAYWRIGHT LAUNCH] No se pudo iniciar con canal '{launch_channel}': {e_channel}. "
                    "Intentando fallback a chromium empaquetado."
                )
                try:
                    self._browser_instance = self._playwright_instance.chromium.launch(
                        headless=self.headless,
                    )
                    launch_channel = "chromium"
                except Exception as e_chromium:
                    raise PlaywrightUnavailableError(
                        f"Fallo crítico al iniciar navegador con Playwright: {e_chromium}"
                    ) from e_chromium

            self.channel = launch_channel
            self._browser_version = self._browser_instance.version

            # Crear contexto aislado por sesión (sin compartir credenciales ni estado entre usuarios)
            self._context_instance = self._browser_instance.new_context(
                accept_downloads=True,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0 JESSYCA/3.0",
            )
            self._context_instance.set_default_timeout(self.timeout_ms)

            # Interceptar y abortar peticiones de red hacia URLs o dominios no autorizados (anti-leak)
            if self.policy:
                def _route_interceptor(route: Any) -> None:
                    req_url = route.request.url
                    if req_url.startswith(("about:blank", "about:srcdoc")):
                        route.continue_()
                        return
                    if not self.policy.is_url_allowed(req_url):
                        logger.warning(f"[SECURITY ROUTE ABORT] Abortando petición hacia URL no autorizada: '{req_url}'")
                        route.abort("accessdenied")
                        return
                    route.continue_()

                self._context_instance.route("**/*", _route_interceptor)

            init_barrier.put((True, "INITIALIZED"))
        except Exception as exc:
            self._init_error = exc
            init_barrier.put((False, exc))
            return

        # Procesar tareas síncronas despachadas al hilo
        while True:
            item = self._task_queue.get()
            fn, reply_queue = item
            if fn is None:
                # Señal de apagado
                break

            try:
                res = fn()
                reply_queue.put((True, res))
            except Exception as e_task:
                reply_queue.put((False, e_task))

        # Cierre ordenado de recursos en el mismo hilo
        try:
            if self._context_instance:
                try:
                    self._context_instance.close()
                except (BrokenPipeError, OSError, Exception) as e_ctx:
                    logger.debug(f"[PLAYWRIGHT CLEANUP] Context close: {e_ctx}")
                self._context_instance = None
            if self._browser_instance:
                try:
                    self._browser_instance.close()
                except (BrokenPipeError, OSError, Exception) as e_br:
                    logger.debug(f"[PLAYWRIGHT CLEANUP] Browser close: {e_br}")
                self._browser_instance = None
            if self._playwright_instance:
                try:
                    self._playwright_instance.stop()
                except (BrokenPipeError, OSError, Exception) as e_pw:
                    logger.debug(f"[PLAYWRIGHT CLEANUP] Playwright stop: {e_pw}")
                self._playwright_instance = None
        except Exception as e_close:
            logger.debug(f"[PLAYWRIGHT WORKER CLEANUP] Error al cerrar recursos: {e_close}")

    def execute(self, fn: Callable[[], Any], timeout_seconds: float = 30.0) -> Any:
        """Envía una función al hilo de trabajo y espera el resultado."""
        if not self._is_running or not self._thread or not self._thread.is_alive():
            raise PlaywrightUnavailableError("El hilo de trabajo de Playwright no está en ejecución.")

        self.emergency_stop.check_cancellation("playwright_worker_dispatch")

        reply_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
        self._task_queue.put((fn, reply_queue))

        try:
            ok, result = reply_queue.get(timeout=timeout_seconds)
        except queue.Empty as err:
            raise BrowserControlError(f"Timeout esperando respuesta del hilo de Playwright ({timeout_seconds}s)") from err

        self.emergency_stop.check_cancellation("playwright_worker_result")

        if not ok:
            raise result
        return result

    def stop(self) -> None:
        """Detiene el hilo de trabajo y libera recursos."""
        if not self._is_running:
            return

        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._task_queue.put((None, queue.Queue()))
            self._thread.join(timeout=10)


class PlaywrightBrowserAdapter(IBrowserAdapter):
    """Adaptador de navegación web de grado producción sobre Playwright (Microsoft Edge).

    Implementa IBrowserAdapter con perfiles de automatización aislados,
    inspección DOM estructurada, accesibilidad, clicks gobernados y descargas sandbox.
    """

    def __init__(
        self,
        headless: bool = True,
        channel: str = "msedge",
        user_data_dir: Path | None = None,
        timeout_ms: int = 15000,
        policy: URLAllowlistPolicy | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.policy = policy or URLAllowlistPolicy()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.timeout_ms = timeout_ms
        self.media_controller = MediaPlaybackController()

        self._worker = _PlaywrightWorkerThread(
            headless=headless,
            channel=channel,
            user_data_dir=user_data_dir,
            timeout_ms=timeout_ms,
            policy=self.policy,
            emergency_stop=self.emergency_stop,
        )
        self._tabs: dict[str, Any] = {}  # tab_id -> Page
        self._tab_metadata: dict[str, BrowserTab] = {}
        self._active_tab_id: str | None = None
        self._is_closed = False

        # Iniciar worker
        self._worker.start()

    def _validate_current_url_policy(self, current_url: str, original_url: str = "") -> None:
        """Valida que la URL actual post-navegación o post-redirección cumpla estrictamente la política."""
        if not self.policy.is_url_allowed(current_url):
            msg = (
                f"Redirección o navegación denegada: La URL de destino '{current_url}' "
                f"viola la política de seguridad Deny-by-Default (URL inicial: '{original_url}')."
            )
            logger.warning(f"[SECURITY REDIRECT DENIED] {msg}")
            raise NavigationSecurityError(msg)

    def open_url(self, url: str, new_tab: bool = False) -> BrowserTab:
        """Valida la URL y abre la página en el contexto de Playwright.

        Garantiza que la URL inicial y cualquier redirección cumplan con URLAllowlistPolicy.
        """
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")

        clean_url = self.policy.validate_url(url)
        self.emergency_stop.check_cancellation("playwright_open_url")

        def _do_open() -> tuple[str, str, str]:
            context = self._worker._context_instance
            if not new_tab and self._active_tab_id and self._active_tab_id in self._tabs:
                page = self._tabs[self._active_tab_id]
                tid = self._active_tab_id
            else:
                page = context.new_page()
                tid = f"tab-{uuid.uuid4().hex[:6]}"
                self._tabs[tid] = page
                self._active_tab_id = tid

            # Navegación gobernada con timeout
            try:
                page.goto(clean_url, timeout=self.timeout_ms, wait_until="domcontentloaded")
            except Exception as e_goto:
                err_str = str(e_goto).lower()
                if "accessdenied" in err_str or "err_access_denied" in err_str or "err_name_not_resolved" in err_str:
                    raise NavigationSecurityError(
                        f"Redirección o navegación denegada hacia URL no autorizada durante apertura de '{clean_url}': {e_goto}"
                    ) from e_goto
                curr_url = getattr(page, "url", "")
                if curr_url and not self.policy.is_url_allowed(curr_url):
                    raise NavigationSecurityError(
                        f"Redirección denegada: '{curr_url}' viola la política Deny-by-Default (URL inicial: '{clean_url}')"
                    ) from e_goto
                raise BrowserControlError(f"Error al navegar a '{clean_url}': {e_goto}") from e_goto

            post_nav_url = page.url
            title = page.title() or "Página Web"
            return tid, post_nav_url, title

        tid, post_nav_url, title = self._worker.execute(_do_open)

        # Validación estricta post-navegación (anti-redirección maliciosa)
        try:
            self._validate_current_url_policy(post_nav_url, original_url=clean_url)
        except NavigationSecurityError:
            # Si redirigió a un dominio malicioso, cerramos la pestaña inmediatamente
            self.close_tab(tid)
            raise

        tab = BrowserTab(
            tab_id=tid,
            url=post_nav_url,
            title=title,
            is_active=True,
            is_loading=False,
            media_state=MediaState.STOPPED,
            provenance="REAL_PHYSICAL",
        )
        self._tab_metadata[tid] = tab
        return tab

    def get_active_tab(self) -> BrowserTab | None:
        """Retorna la pestaña activa actual con su estado verificado."""
        if self._is_closed or not self._active_tab_id or self._active_tab_id not in self._tabs:
            return None

        tid = self._active_tab_id

        def _get_info() -> tuple[str, str]:
            page = self._tabs[tid]
            return page.url, page.title()

        try:
            url, title = self._worker.execute(_get_info)
            prev = self._tab_metadata.get(tid)
            media_st = prev.media_state if prev else MediaState.UNKNOWN
            tab = BrowserTab(
                tab_id=tid,
                url=url,
                title=title,
                is_active=True,
                is_loading=False,
                media_state=media_st,
                provenance="REAL_PHYSICAL",
            )
            self._tab_metadata[tid] = tab
            return tab
        except Exception:
            return self._tab_metadata.get(tid)

    def switch_tab(self, tab_id: str) -> BrowserTab:
        """Asigna el foco a una pestaña específica."""
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")
        if tab_id not in self._tabs:
            raise TabNotFoundError(f"Pestaña no encontrada: '{tab_id}'")

        def _bring_to_front() -> None:
            page = self._tabs[tab_id]
            page.bring_to_front()

        self._worker.execute(_bring_to_front)
        self._active_tab_id = tab_id

        # Actualizar banderas de actividad
        for tid in list(self._tab_metadata.keys()):
            old = self._tab_metadata[tid]
            self._tab_metadata[tid] = BrowserTab(
                tab_id=old.tab_id,
                url=old.url,
                title=old.title,
                is_active=(tid == tab_id),
                is_loading=old.is_loading,
                media_state=old.media_state,
                provenance="REAL_PHYSICAL",
            )

        active = self.get_active_tab()
        if not active:
            raise TabNotFoundError(f"No se pudo activar pestaña '{tab_id}'")
        return active

    def close_tab(self, tab_id: str) -> bool:
        """Cierra una pestaña específica y actualiza el foco."""
        if self._is_closed or tab_id not in self._tabs:
            return False

        def _do_close() -> None:
            page = self._tabs[tab_id]
            page.close()

        try:
            self._worker.execute(_do_close)
        except Exception as e:
            logger.debug(f"[PLAYWRIGHT CLOSE TAB] Error cerrando página: {e}")

        del self._tabs[tab_id]
        if tab_id in self._tab_metadata:
            del self._tab_metadata[tab_id]

        if self._active_tab_id == tab_id:
            self._active_tab_id = next(iter(self._tabs.keys())) if self._tabs else None

        return True

    def get_text(self, selector: str | None = None) -> str:
        """Extrae el contenido textual sanitizado de un elemento o de la página entera.

        GARANTÍA DE DATOS NO CONFIABLES:
        El texto obtenido se trata estrictamente como DATA no confiable.
        Se eliminan secretos mediante BrowserPolicy.sanitize_dom_for_llm.
        """
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")
        if not self._active_tab_id or self._active_tab_id not in self._tabs:
            raise TabNotFoundError("No hay pestaña activa para extraer texto.")

        from core.agents.browser_policy import BrowserPolicy

        tid = self._active_tab_id

        def _extract() -> str:
            page = self._tabs[tid]
            if selector:
                loc = page.locator(selector)
                if loc.count() == 0:
                    raise DOMElementNotFoundError(f"Elemento no encontrado para selector: '{selector}'")
                raw = loc.inner_text()
            else:
                raw = page.locator("body").inner_text()
            return raw

        raw_text = self._worker.execute(_extract)
        # Sanitizar secretos antes de devolver la data
        return BrowserPolicy.sanitize_dom_for_llm(raw_text)

    def get_html(self, selector: str | None = None) -> str:
        """Extrae el contenido HTML del elemento o de la página entera."""
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")
        if not self._active_tab_id or self._active_tab_id not in self._tabs:
            raise TabNotFoundError("No hay pestaña activa para extraer HTML.")

        tid = self._active_tab_id

        def _get_html() -> str:
            page = self._tabs[tid]
            if selector:
                loc = page.locator(selector)
                if loc.count() == 0:
                    raise DOMElementNotFoundError(f"Elemento no encontrado para selector: '{selector}'")
                return loc.inner_html()
            return page.content()

        return self._worker.execute(_get_html)

    def extract_search_results(self, max_results: int = 5) -> list[dict[str, str]]:
        """Extrae estructuradamente (título, href real, snippet) de cada contenedor de resultado en el DOM."""
        if self._is_closed or not self._active_tab_id or self._active_tab_id not in self._tabs:
            return []

        tid = self._active_tab_id

        def _do_extract() -> list[dict[str, str]]:
            from skills.browser_search_skill import parse_search_results_from_html
            page = self._tabs[tid]
            html = page.content()
            return parse_search_results_from_html(
                html=html,
                base_url=page.url,
                policy=self.policy,
                max_results=max_results,
            )

        return self._worker.execute(_do_extract)

    def query_dom(self, selector: str) -> dict[str, Any]:
        """Consulta el estado estructurado de un elemento en el DOM sin coordenadas mágicas."""
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")
        if not self._active_tab_id or self._active_tab_id not in self._tabs:
            raise TabNotFoundError("No hay pestaña activa para consultar DOM.")
        if not selector or not isinstance(selector, str):
            raise DOMElementNotFoundError("Selector de elemento DOM inválido.")

        tid = self._active_tab_id

        def _query() -> dict[str, Any]:
            page = self._tabs[tid]
            loc = page.locator(selector)
            if loc.count() == 0:
                raise DOMElementNotFoundError(f"Elemento no encontrado para selector: '{selector}'")

            first = loc.first
            visible = first.is_visible()

            # En Playwright is_enabled() aplica a controles interactivos; para elementos estructurales se evalúa disabled
            is_dis = False
            try:
                is_dis = first.is_disabled()
            except Exception:
                try:
                    is_dis = bool(first.get_attribute("disabled"))
                except Exception:
                    is_dis = False
            enabled = not is_dis

            text = first.inner_text() if visible else ""

            # Atributos útiles de accesibilidad y etiquetado
            tag_name = first.evaluate("el => el.tagName.toLowerCase()")
            role = first.get_attribute("role") or ""
            input_type = first.get_attribute("type") or ""
            elem_id = first.get_attribute("id") or ""
            name = first.get_attribute("name") or ""

            return {
                "selector": selector,
                "tag": tag_name,
                "visible": visible,
                "enabled": enabled,
                "text": text,
                "role": role,
                "type": input_type,
                "id": elem_id,
                "name": name,
                "is_untrusted_data": True,
            }

        return self._worker.execute(_query)

    def get_accessibility_snapshot(self) -> dict[str, Any]:
        """Obtiene el snapshot estructurado del árbol de accesibilidad de la página activa."""
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")
        if not self._active_tab_id or self._active_tab_id not in self._tabs:
            raise TabNotFoundError("No hay pestaña activa para accesibilidad.")

        tid = self._active_tab_id

        def _snap() -> dict[str, Any]:
            page = self._tabs[tid]
            snapshot = page.accessibility.snapshot()
            return snapshot or {}

        res = self._worker.execute(_snap)
        return res if isinstance(res, dict) else {"snapshot": res}

    def fill_form(self, selector_values: dict[str, str]) -> dict[str, bool]:
        """Rellena campos de formulario de forma estructurada y gobernada."""
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")
        if not self._active_tab_id or self._active_tab_id not in self._tabs:
            raise TabNotFoundError("No hay pestaña activa para rellenar formulario.")

        self.emergency_stop.check_cancellation("playwright_fill_form")
        tid = self._active_tab_id

        def _fill() -> dict[str, bool]:
            page = self._tabs[tid]
            results: dict[str, bool] = {}
            for sel, val in selector_values.items():
                loc = page.locator(sel)
                if loc.count() == 0:
                    raise DOMElementNotFoundError(f"Campo de formulario no encontrado: '{sel}'")
                first = loc.first
                if not first.is_visible() or not first.is_enabled():
                    raise DOMElementNotFoundError(f"Campo '{sel}' no está disponible o visible para edición.")

                first.fill(str(val))
                results[sel] = True
            return results

        return self._worker.execute(_fill)

    def click(self, selector: str) -> bool:
        """Emite un clic gobernado verificando visibilidad, estado del elemento y URLs resultantes."""
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")
        if not self._active_tab_id or self._active_tab_id not in self._tabs:
            raise TabNotFoundError("No hay pestaña activa para realizar clic.")

        self.emergency_stop.check_cancellation("playwright_click")
        tid = self._active_tab_id

        def _do_click() -> str:
            page = self._tabs[tid]
            loc = page.locator(selector)
            if loc.count() == 0:
                raise DOMElementNotFoundError(f"Elemento no encontrado para clic: '{selector}'")
            first = loc.first
            if not first.is_visible():
                raise DOMElementNotFoundError(f"Elemento '{selector}' no es visible para clic.")

            is_dis = False
            try:
                is_dis = first.is_disabled()
            except Exception:
                try:
                    is_dis = bool(first.get_attribute("disabled"))
                except Exception:
                    is_dis = False

            if is_dis:
                raise DOMElementNotFoundError(f"Elemento '{selector}' está deshabilitado para clic.")

            first.click(timeout=self.timeout_ms)
            # Retorna URL resultante tras el clic
            return page.url

        new_url = self._worker.execute(_do_click)

        # Si el clic provocó una navegación, validamos que la nueva URL esté autorizada
        self._validate_current_url_policy(new_url)
        return True

    def download_file(
        self,
        url_or_selector: str,
        sandbox_dir: str | Path,
        target_filename: str | None = None,
    ) -> str:
        """Descarga un archivo confinado estrictamente al directorio sandbox.

        SEGURIDAD ANTI-SANDBOX-ESCAPE:
        - Verifica que la ruta de destino resuelva estrictamente DENTRO de sandbox_dir.
        - Rechaza path traversal ('..', '/etc/', 'C:\\Windows').
        - Rechaza extensiones de archivos auto-ejecutables (.exe, .bat, etc.) según BrowserPolicy.
        - Verifica físicamente la existencia del archivo en disco.
        """
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")

        from core.agents.browser_policy import BrowserPolicy

        sandbox_root = Path(sandbox_dir).resolve()
        sandbox_root.mkdir(parents=True, exist_ok=True)

        # 1. Validación de nombre de archivo o extensión si fue proporcionado
        if target_filename:
            # Detección de escape de sandbox
            dest_candidate = (sandbox_root / target_filename).resolve()
            try:
                dest_candidate.relative_to(sandbox_root)
            except ValueError as err:
                msg = f"Intento de escape de sandbox detectado: '{target_filename}' escapa de '{sandbox_root}'"
                logger.warning(f"[SECURITY ESCAPE DENIED] {msg}")
                raise SandboxEscapeError(msg) from err

            # Validación de extensión peligrosa
            verdict = BrowserPolicy.validate_download(dest_candidate.name)
            if not verdict.is_allowed:
                raise BrowserControlError(verdict.reason)

        is_direct_url = url_or_selector.startswith(("http://", "https://"))
        tid = self._active_tab_id
        if not is_direct_url and (not tid or tid not in self._tabs):
            raise TabNotFoundError("No hay pestaña activa para gestionar descarga.")

        def _do_download() -> str:
            # Caso A: Descarga disparada por clic en elemento de la página
            if not is_direct_url:
                page = self._tabs[tid]
                loc = page.locator(url_or_selector)
                if loc.count() == 0:
                    raise DOMElementNotFoundError(f"Elemento de descarga no encontrado: '{url_or_selector}'")

                with page.expect_download(timeout=self.timeout_ms) as download_info:
                    loc.click()

                download = download_info.value
                fname = target_filename or download.suggested_filename
                final_dest = (sandbox_root / fname).resolve()

                # Re-verificar confinamiento de sandbox sobre nombre sugerido
                try:
                    final_dest.relative_to(sandbox_root)
                except ValueError as err:
                    raise SandboxEscapeError(f"El archivo sugerido '{fname}' intenta escapar del sandbox.") from err

                verdict_suggested = BrowserPolicy.validate_download(final_dest.name)
                if not verdict_suggested.is_allowed:
                    raise BrowserControlError(verdict_suggested.reason)

                download.save_as(str(final_dest))
                return str(final_dest)

            # Caso B: Descarga directa por URL http/https
            clean_url = self.policy.validate_url(url_or_selector)
            context = self._worker._context_instance
            response = context.request.get(clean_url, timeout=self.timeout_ms)
            if not response.ok:
                raise BrowserControlError(f"Fallo al descargar archivo desde URL: {response.status} {response.status_text}")

            fname = target_filename or os.path.basename(urlparse(clean_url).path) or "downloaded_file.bin"
            final_dest = (sandbox_root / fname).resolve()

            try:
                final_dest.relative_to(sandbox_root)
            except ValueError as err:
                raise SandboxEscapeError(f"Ruta de archivo '{fname}' intenta escapar del sandbox.") from err

            verdict_direct = BrowserPolicy.validate_download(final_dest.name)
            if not verdict_direct.is_allowed:
                raise BrowserControlError(verdict_direct.reason)

            final_dest.write_bytes(response.body())
            return str(final_dest)

        saved_path_str = self._worker.execute(_do_download)
        saved_path = Path(saved_path_str)

        # Verificación física en disco
        if not saved_path.exists() or not saved_path.is_file():
            raise BrowserControlError(f"Error de verificación: El archivo descargado no existe en disco: '{saved_path}'")

        logger.info(f"[SANDBOX DOWNLOAD VERIFIED] Archivo descargado exitosamente en: '{saved_path}' ({saved_path.stat().st_size} bytes)")
        return str(saved_path)

    def execute_js_snippet(self, snippet: AllowedJSSnippet, params: dict[str, str] | None = None) -> Any:
        """Ejecuta estrictamente snippets cerrados predefinidos en AllowedJSSnippet.

        PROHIBICIÓN ABSOLUTA DE JAVASCRIPT LIBRE/ARBITRARIO.
        """
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")
        if not isinstance(snippet, AllowedJSSnippet):
            raise ArbitraryJSExecutionError("Ejecución denegada: Solo se permiten snippets autorizados en AllowedJSSnippet.")
        if not self._active_tab_id or self._active_tab_id not in self._tabs:
            raise TabNotFoundError("No hay pestaña activa para ejecutar snippet JS.")

        tid = self._active_tab_id
        template = str(snippet.value)
        p = params or {}
        code = template.format(**p) if p else template

        def _eval() -> Any:
            page = self._tabs[tid]
            return page.evaluate(code)

        return self._worker.execute(_eval)

    def control_media(self, tab_id: str, action: str) -> BrowserTab:
        """Controla la reproducción de medios (play/pause/resume/mute) en una pestaña y verifica el estado resultante real del reproductor."""
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")
        if tab_id not in self._tabs:
            raise TabNotFoundError(f"Pestaña no encontrada para control de medios: '{tab_id}'")

        act_clean = action.strip().lower()

        def _media() -> dict[str, Any]:
            page = self._tabs[tab_id]
            if act_clean in ("play", "reproducir", "start", "resume", "reanudar"):
                page.evaluate("""() => {
                    document.querySelectorAll('video, audio').forEach(el => {
                        try { el.play(); } catch(e) {}
                    });
                }""")
            elif act_clean in ("pause", "pausar", "stop"):
                page.evaluate("""() => {
                    document.querySelectorAll('video, audio').forEach(el => {
                        try { el.pause(); } catch(e) {}
                    });
                }""")
            elif act_clean in ("mute", "silenciar"):
                page.evaluate("""() => {
                    document.querySelectorAll('video, audio').forEach(el => el.muted = true);
                }""")
            elif act_clean in ("unmute", "desilenciar"):
                page.evaluate("""() => {
                    document.querySelectorAll('video, audio').forEach(el => el.muted = false);
                }""")

            # Verificación del estado observable en el DOM (anti-false-success)
            state = page.evaluate("""() => {
                const media = Array.from(document.querySelectorAll('video, audio'));
                if (media.length === 0) {
                    return { has_media: false, is_playing: false, is_paused: true, current_time: 0, count: 0 };
                }
                let playing = false;
                let paused = true;
                for (const el of media) {
                    if (!el.paused && !el.ended && el.readyState >= 2) {
                        playing = true;
                        paused = false;
                        break;
                    }
                }
                return {
                    has_media: true,
                    is_playing: playing,
                    is_paused: paused,
                    current_time: media[0].currentTime,
                    duration: media[0].duration || 0,
                    muted: media[0].muted,
                    count: media.length,
                };
            }""")
            return state

        real_state: dict[str, Any] = {"has_media": False, "is_playing": False, "is_paused": True}
        try:
            real_state = self._worker.execute(_media)
        except Exception as e:
            logger.debug(f"[PLAYWRIGHT MEDIA CONTROL] Intento de comando multimedia: {e}")

        tab = self._tab_metadata.get(tab_id)
        if not tab:
            tab = BrowserTab(tab_id=tab_id, url="", title="Media Tab", is_active=True)

        # Distinción de estado real basada en la evidencia del DOM
        if not real_state.get("has_media"):
            new_media_state = MediaState.STOPPED
        elif real_state.get("is_playing"):
            new_media_state = MediaState.PLAYING
        elif real_state.get("is_paused"):
            new_media_state = MediaState.PAUSED
        elif act_clean in ("mute", "silenciar"):
            new_media_state = MediaState.MUTED
        else:
            new_media_state = MediaState.UNKNOWN

        updated = BrowserTab(
            tab_id=tab.tab_id,
            url=tab.url,
            title=tab.title,
            is_active=tab.is_active,
            is_loading=tab.is_loading,
            media_state=new_media_state,
            provenance="REAL_PHYSICAL",
        )
        self._tab_metadata[tab_id] = updated
        return updated

    def follow_link(self, link_text_or_selector: str) -> BrowserTab:
        """Sigue un enlace en la pestaña activa mediante su texto o selector CSS."""
        if self._is_closed:
            raise PlaywrightUnavailableError("El adaptador de Playwright ha sido cerrado.")
        if not self._active_tab_id or self._active_tab_id not in self._tabs:
            raise TabNotFoundError("No hay pestaña activa para seguir enlaces.")

        tid = self._active_tab_id

        def _follow() -> tuple[str, str, str]:
            page = self._tabs[tid]
            # Intentar búsqueda por texto en etiqueta 'a'
            link_loc = page.locator(f"a:has-text('{link_text_or_selector}')")
            if link_loc.count() == 0:
                try:
                    link_loc = page.locator(link_text_or_selector)
                except Exception:
                    pass
            if link_loc.count() == 0:
                # Fallback: búsqueda de texto normalizada insensible a acentos y mayúsculas
                import unicodedata
                def _strip_acc(t: str) -> str:
                    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower().strip()

                target_norm = _strip_acc(link_text_or_selector)
                all_links = page.locator("a")
                for i in range(all_links.count()):
                    cand = all_links.nth(i)
                    cand_text = _strip_acc(cand.inner_text() or "")
                    if target_norm and (target_norm in cand_text or cand_text in target_norm):
                        link_loc = cand
                        break

            if link_loc.count() == 0:
                raise DOMElementNotFoundError(f"Enlace no encontrado en la página activa: '{link_text_or_selector}'")

            first = link_loc.first
            if not first.is_visible():
                raise DOMElementNotFoundError(f"Enlace '{link_text_or_selector}' no es visible.")

            first.click(timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
            except Exception:
                pass
            return tid, page.url, page.title() or "Página Web"

        _, post_nav_url, title = self._worker.execute(_follow)
        self._validate_current_url_policy(post_nav_url)

        tab = BrowserTab(
            tab_id=tid,
            url=post_nav_url,
            title=title,
            is_active=True,
            is_loading=False,
            media_state=MediaState.STOPPED,
            provenance="REAL_PHYSICAL",
        )
        self._tab_metadata[tid] = tab
        return tab

    def extract_content(self, selector: str | None = None) -> dict[str, Any]:
        """Extrae el contenido textual sanitizado con metadatos y URL de procedencia."""
        tab = self.get_active_tab()
        if not tab:
            raise TabNotFoundError("No hay pestaña activa para extraer contenido.")
        text = self.get_text(selector=selector)
        return {
            "url": tab.url,
            "title": tab.title,
            "texto": text,
            "tab_id": tab.tab_id,
            "provenance": "REAL_PHYSICAL",
            "is_untrusted_data": True,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def search_web(self, query: str, engine: str = "google") -> BrowserTab:
        """Realiza una búsqueda web en motor autorizado (Google, DuckDuckGo, Wikipedia)."""
        q_clean = urllib.parse.quote_plus(query.strip())
        eng_lower = engine.strip().lower()
        if "duck" in eng_lower:
            url = f"https://duckduckgo.com/?q={q_clean}"
        elif "wiki" in eng_lower:
            url = f"https://es.wikipedia.org/wiki/Special:Search?search={q_clean}"
        else:
            url = f"https://www.google.com/search?q={q_clean}"

        tab = self.open_url(url)
        self.handle_consent_and_popups(tab.tab_id)
        return tab

    def search_youtube(self, query: str) -> BrowserTab:
        """Busca videos en YouTube en Microsoft Edge."""
        q_clean = urllib.parse.quote_plus(query.strip())
        url = f"https://www.youtube.com/results?search_query={q_clean}"
        tab = self.open_url(url)
        self.handle_consent_and_popups(tab.tab_id)
        return tab

    def handle_consent_and_popups(self, tab_id: str | None = None) -> dict[str, Any]:
        """Gestiona automáticamente diálogos y banners de consentimiento de cookies y ventanas emergentes."""
        if self._is_closed:
            return {"handled": False}
        target_tid = tab_id or self._active_tab_id
        if not target_tid or target_tid not in self._tabs:
            return {"handled": False}

        def _handle() -> dict[str, Any]:
            page = self._tabs[target_tid]
            handled_actions: list[str] = []

            consent_selectors = [
                "button:has-text('Aceptar todo')",
                "button:has-text('Acepto')",
                "button:has-text('Accept all')",
                "button:has-text('I agree')",
                "button:has-text('Aceptar cookies')",
                "button:has-text('Aceptar')",
                "#accept-cookies",
                ".accept-cookies",
                "button[aria-label*='Aceptar todo']",
                "button[aria-label*='Accept all']",
                "#introAgreeButton",
                ".cookie-accept",
                "#cookie-accept",
            ]
            for sel in consent_selectors:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.click(timeout=1500)
                        handled_actions.append(f"Consent dismissed: {sel}")
                        break
                except Exception:
                    pass

            return {"handled": len(handled_actions) > 0, "actions": handled_actions}

        try:
            return self._worker.execute(_handle)
        except Exception:
            return {"handled": False}

    def detect_blocking_state(self, tab_id: str | None = None) -> tuple[bool, str]:
        """Detecta si la página activa presenta bloqueo por CAPTCHA, Cloudflare o login obligatorio."""
        if self._is_closed:
            return False, ""
        target_tid = tab_id or self._active_tab_id
        if not target_tid or target_tid not in self._tabs:
            return False, ""

        def _detect() -> tuple[bool, str]:
            page = self._tabs[target_tid]
            captcha_selectors = [
                "iframe[src*='recaptcha']",
                "iframe[src*='hcaptcha']",
                ".g-recaptcha",
                ".h-captcha",
                ".cf-turnstile",
                "#challenge-running",
                "#challenge-stage",
                "div[id*='captcha']",
                "[class*='captcha']",
            ]
            for sel in captcha_selectors:
                try:
                    if page.locator(sel).count() > 0:
                        return True, f"Detectado CAPTCHA o desafío anti-bot ({sel}). Se requiere intervención del usuario."
                except Exception:
                    pass

            try:
                content_lower = page.content().lower()
                if any(phrase in content_lower for phrase in ("verifique que es un humano", "verificación de seguridad", "complete el captcha", "challenge-running", "turnstile")):
                    return True, "Detectada verificación de seguridad (CAPTCHA). Se requiere intervención del usuario."
            except Exception:
                pass

            title_lower = (page.title() or "").lower()
            if any(term in title_lower for term in ("inicia sesión", "sign in", "login required", "acceso denegado")):
                return True, f"Acceso restringido por autenticación requerida ('{page.title()}'). Se requiere intervención del usuario."

            return False, ""

        return self._worker.execute(_detect)

    def health(self) -> dict[str, Any]:
        """Comprueba el estado de salud técnico real del navegador y del proceso."""
        if self._is_closed:
            return {
                "status": "CLOSED",
                "backend": "playwright",
                "channel": self._worker.channel,
                "is_running": False,
                "tabs_count": 0,
            }

        worker_alive = bool(self._worker._is_running and self._worker._thread and self._worker._thread.is_alive())
        if not worker_alive:
            return {
                "status": "UNAVAILABLE",
                "backend": "playwright",
                "channel": self._worker.channel,
                "is_running": False,
                "error": "Worker thread is not alive",
            }

        try:
            browser_ver = self._worker._browser_version
            return {
                "status": "HEALTHY",
                "backend": "playwright",
                "channel": self._worker.channel,
                "browser_version": browser_ver,
                "headless": self._worker.headless,
                "is_running": True,
                "tabs_count": len(self._tabs),
            }
        except Exception as e:
            return {
                "status": "DEGRADED",
                "backend": "playwright",
                "channel": self._worker.channel,
                "is_running": True,
                "error": str(e),
            }

    def capabilities(self) -> dict[str, Any]:
        """Reporta las capacidades técnicas del backend Playwright."""
        return {
            "backend": "playwright",
            "channel": self._worker.channel,
            "browser_version": self._worker._browser_version,
            "headless": self._worker.headless,
            "dom_query": True,
            "accessibility_snapshot": True,
            "text_extraction": True,
            "form_filling": True,
            "governed_click": True,
            "sandbox_download": True,
            "media_control": True,
            "closed_js_snippets": True,
            "arbitrary_evaluate": False,  # Prohibición explícita de seguridad
            "isolated_profiles": True,
            "anti_sandbox_escape": True,
        }

    def close(self) -> None:
        """Cierra ordenadamente todas las páginas, contextos, navegador y detiene el worker."""
        if self._is_closed:
            return

        self._is_closed = True
        self._tabs.clear()
        self._tab_metadata.clear()
        self._active_tab_id = None
        self._worker.stop()
        logger.info("[PLAYWRIGHT ADAPTER CLOSED] Todos los recursos de Playwright han sido liberados.")
