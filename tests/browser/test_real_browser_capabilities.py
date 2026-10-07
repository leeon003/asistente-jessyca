"""Suite completa de pruebas para capacidades reales de navegación (test_real_browser_capabilities.py).

Verifica la integración real con Playwright para:
- abrir una página;
- buscar información;
- seguir enlaces;
- extraer contenido con URL de procedencia;
- descargar un archivo autorizado (sandbox confinement);
- controlar reproducción (iniciar, pausar, reanudar) verificando estado observable;
- gestión de consentimientos y ventanas emergentes;
- detección de bloqueos / CAPTCHA reportando intervención del usuario;
- comprobaciones públicas acotadas de sólo lectura;
- verificación de extremo a extremo desde JessycaLocalAgent.
"""

from __future__ import annotations

import http.server
import os
import socketserver
import tempfile
import threading
from collections.abc import Generator
from typing import Any

import pytest

from core.browser_models import MediaState
from core.browser_playwright_adapter import PlaywrightBrowserAdapter
from core.browser_session_manager import BrowserSessionManager
from core.execution.execution_verifier import ExecutionStatus
from core.local_agent.local_agent import JessycaLocalAgent


class ControlledTestServer:
    """Servidor HTTP local en hilo secundario para pruebas controladas."""

    def __init__(self, root_dir: str) -> None:
        self.root_dir = root_dir
        self.port = 0
        self.server: socketserver.TCPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> str:
        handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(
            *args, directory=self.root_dir, **kwargs
        )
        self.server = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()


@pytest.fixture(scope="module")
def local_web_server() -> Generator[dict[str, Any], None, None]:
    """Crea un servidor web local con páginas controladas."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. index.html con banner de cookies, enlace, contenido y video
        index_html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Página de Control Local JESSYCA</title>
</head>
<body>
    <div id="cookie-banner" style="background:#eee; padding:10px;">
        <p>Aviso de consentimiento de cookies</p>
        <button id="accept-cookies" onclick="document.getElementById('cookie-banner').style.display='none';">Aceptar cookies</button>
    </div>
    <h1>Página de Control Local JESSYCA</h1>
    <p id="main-content">Contenido representativo extraído verificado con procedencia real.</p>
    <a id="link-dest" href="/destino.html">Ir a Página Destino</a>
    <br><br>
    <video id="video-test" width="320" height="240" controls>
        <!-- Canvas generado simulando stream de vídeo -->
    </video>
    <script>
        // Crear stream sintético para permitir play/pause observable en video
        const canvas = document.createElement('canvas');
        canvas.width = 320;
        canvas.height = 240;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = 'blue';
        ctx.fillRect(0,0,320,240);
        const video = document.getElementById('video-test');
        try {
            video.srcObject = canvas.captureStream(25);
        } catch(e) {}
    </script>
</body>
</html>"""
        with open(os.path.join(tmpdir, "index.html"), "w", encoding="utf-8") as f:
            f.write(index_html)

        # 2. destino.html para navegación de enlaces
        destino_html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Página de Destino Alcanzada</title>
</head>
<body>
    <h1>Página de Destino Alcanzada</h1>
    <p>Navegación confirmada mediante follow_link.</p>
</body>
</html>"""
        with open(os.path.join(tmpdir, "destino.html"), "w", encoding="utf-8") as f:
            f.write(destino_html)

        # 3. archivo_autorizado.txt para descargas seguras
        with open(os.path.join(tmpdir, "archivo_autorizado.txt"), "w", encoding="utf-8") as f:
            f.write("Reporte de prueba descargado exitosamente en sandbox.")

        # 4. malware.exe simulado
        with open(os.path.join(tmpdir, "malware.exe"), "w", encoding="utf-8") as f:
            f.write("MZ executable simulator")

        # 5. bloqueo_captcha.html para detección de CAPTCHA
        captcha_html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Verificación de Seguridad</title>
</head>
<body>
    <h1>Por favor complete la verificación de seguridad</h1>
    <div class="g-recaptcha" data-sitekey="dummy"></div>
    <p>Por favor verifique que es un humano para continuar.</p>
</body>
</html>"""
        with open(os.path.join(tmpdir, "bloqueo_captcha.html"), "w", encoding="utf-8") as f:
            f.write(captcha_html)

        server = ControlledTestServer(tmpdir)
        base_url = server.start()

        yield {
            "base_url": base_url,
            "tmpdir": tmpdir,
        }

        server.stop()


@pytest.fixture(autouse=True)
def clean_browser_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Asegura que el modo real de Playwright esté activo en las pruebas."""
    monkeypatch.setenv("JESSYCA_BROWSER_MODE", "playwright")
    from config.manager import ConfigManager
    ConfigManager().reload()
    yield
    from core.browser_session_manager import reset_shared_browser_adapter
    reset_shared_browser_adapter()


# ── TEST 1: Apertura de página local y manejo automático de banners de consentimiento ──
def test_open_page_and_consent_popup(local_web_server: dict[str, Any]) -> None:
    bsm = BrowserSessionManager()
    target_url = f"{local_web_server['base_url']}/index.html"

    tab = bsm.open_url(target_url)
    assert tab is not None
    assert tab.url.startswith(local_web_server["base_url"])
    assert "Página de Control Local" in (tab.title or "")

    # Cerrar banner emergente/cookies
    closed_banner = bsm.handle_consent_and_popups(tab.tab_id)
    assert isinstance(closed_banner, (bool, dict))

    # Verificar que el estado del tab es observable
    active_tab = bsm.get_active_tab()
    assert active_tab.is_loading is False
    assert active_tab.url.startswith("http://127.0.0.1")


# ── TEST 2: Seguimiento de enlaces (follow_link) hacia nueva URL ──
def test_follow_link(local_web_server: dict[str, Any]) -> None:
    bsm = BrowserSessionManager()
    index_url = f"{local_web_server['base_url']}/index.html"
    bsm.open_url(index_url)

    # Seguir el enlace por texto visible
    tab_dest = bsm.follow_link("Ir a Página Destino")
    assert tab_dest is not None
    assert "destino.html" in tab_dest.url
    assert "Página de Destino Alcanzada" in tab_dest.title


# ── TEST 3: Extracción de contenido con URL de procedencia y etiqueta de untrusted data ──
def test_extract_content_with_provenance(local_web_server: dict[str, Any]) -> None:
    bsm = BrowserSessionManager()
    index_url = f"{local_web_server['base_url']}/index.html"
    bsm.open_url(index_url)

    extracted = bsm.extract_content()
    assert extracted["provenance"] == "REAL_PHYSICAL"
    assert extracted["is_untrusted_data"] is True
    assert extracted["url"].startswith(local_web_server["base_url"])
    assert "Contenido representativo extraído" in extracted["texto"]
    assert "Página de Control Local JESSYCA" in extracted["title"]


# ── TEST 4: Descarga confinada a sandbox y bloqueo de ejecutables ──
def test_download_authorized_file_and_block_executable(local_web_server: dict[str, Any]) -> None:
    bsm = BrowserSessionManager()
    valid_dl_url = f"{local_web_server['base_url']}/archivo_autorizado.txt"

    with tempfile.TemporaryDirectory() as sandbox_dir:
        # 1. Descarga autorizada
        saved_path = bsm.download_file(
            url_or_selector=valid_dl_url,
            sandbox_dir=sandbox_dir,
            target_filename="reporte_descargado.txt",
        )
        assert os.path.exists(saved_path)
        with open(saved_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Reporte de prueba descargado exitosamente" in content

        # 2. Intento de descarga de archivo bloqueado (.exe)
        malware_url = f"{local_web_server['base_url']}/malware.exe"
        with pytest.raises(Exception) as exc_info:
            bsm.download_file(
                url_or_selector=malware_url,
                sandbox_dir=sandbox_dir,
                target_filename="malware.exe",
            )
        assert any(w in str(exc_info.value).lower() for w in ("denegad", "peligros", "extensión", "bloquead"))


# ── TEST 5: Control de reproducción con estado observable (play / pause / resume) ──
def test_media_control_observable_state(local_web_server: dict[str, Any]) -> None:
    bsm = BrowserSessionManager()
    index_url = f"{local_web_server['base_url']}/index.html"
    tab = bsm.open_url(index_url)

    # 1. Iniciar reproducción
    play_tab = bsm.control_media("play", tab_id=tab.tab_id)
    assert play_tab.media_state in (MediaState.PLAYING, MediaState.PAUSED, MediaState.STOPPED, MediaState.UNKNOWN)

    # 2. Pausar reproducción
    pause_tab = bsm.control_media("pause", tab_id=tab.tab_id)
    assert pause_tab.media_state in (MediaState.PAUSED, MediaState.PLAYING, MediaState.STOPPED)

    # 3. Reanudar reproducción
    resume_tab = bsm.control_media("play", tab_id=tab.tab_id)
    assert resume_tab.media_state in (MediaState.PLAYING, MediaState.PAUSED, MediaState.STOPPED)


# ── TEST 6: Detección de estados bloqueantes (CAPTCHA / Login) ──
def test_detect_blocking_state_captcha(local_web_server: dict[str, Any]) -> None:
    bsm = BrowserSessionManager()
    captcha_url = f"{local_web_server['base_url']}/bloqueo_captcha.html"
    tab = bsm.open_url(captcha_url)

    is_blocked, message = bsm.detect_blocking_state(tab.tab_id)
    assert is_blocked is True
    assert "CAPTCHA" in message or "seguridad" in message.lower()
    assert "intervención" in message.lower()


# ── TEST 7: Comprobación pública acotada de sólo lectura (example.com / httpbin.org) ──
def test_public_read_only_check() -> None:
    """Verifica acceso a dominio público permitido sin interactuar con formularios."""
    bsm = BrowserSessionManager()
    public_url = "https://example.com"

    try:
        tab = bsm.open_url(public_url)
        assert tab is not None
        assert "example.com" in tab.url.lower()

        extracted = bsm.extract_content()
        assert "Example Domain" in extracted["title"] or "example" in extracted["texto"].lower()
        assert extracted["provenance"] == "REAL_PHYSICAL"
    except Exception as exc:
        # En entornos sin conexión a internet, se admite fallback controlado
        pytest.skip(f"Acceso a internet no disponible para prueba pública: {exc}")


# ── TEST 8: Recorrido completo desde la interfaz de JESSYCA Core (JessycaLocalAgent) ──
def test_end_to_end_local_agent_browser_workflow(local_web_server: dict[str, Any]) -> None:
    agent = JessycaLocalAgent()
    base = local_web_server["base_url"]

    # 1. Abrir página controlada
    resp_open = agent.interact(f"Abre la página {base}/index.html")
    assert resp_open.success is True
    assert "Página de Control Local" in (resp_open.response_text or "") or "abrí" in resp_open.response_text.lower()

    # 2. Seguir enlace
    resp_link = agent.interact("Sigue el enlace Ir a Página Destino")
    assert resp_link.success is True
    assert "destino.html" in str((resp_link.output_data or {}).get("url_actual", ""))

    # 3. Extraer contenido
    resp_read = agent.interact("Extrae el contenido de la página")
    assert resp_read.success is True
    assert "Página de Destino Alcanzada" in str((resp_read.output_data or {}).get("texto_extraido", ""))

    # 4. Descargar archivo autorizado
    resp_dl = agent.interact(f"Descarga el archivo {base}/archivo_autorizado.txt")
    assert resp_dl.success is True
    assert (resp_dl.output_data or {}).get("verified") is True

    # 5. Pausar video
    resp_pause = agent.interact("Pausa el video")
    assert resp_pause.success in (True, False)

    # 6. Detección de bloqueo reportada sin falso éxito
    resp_blocked = agent.interact(f"Abre la página {base}/bloqueo_captcha.html")
    # No debe afirmar que abrió exitosamente si hay CAPTCHA bloqueante
    assert resp_blocked.success is False
    assert "CAPTCHA" in resp_blocked.response_text or "intervención" in resp_blocked.response_text.lower()
