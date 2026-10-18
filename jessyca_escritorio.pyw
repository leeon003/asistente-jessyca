"""Double-click desktop entry. Reuses the installed environment and local backend."""
from pathlib import Path
import ctypes
import os
import shutil
import subprocess
import sys
import time
import webbrowser

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def launch():
    import requests
    from config.manager import get_settings
    from interfaces.webui_bridge.studio_auth import make_launch_ticket
    from interfaces.aurora.window_manager import AuroraWindowManager

    settings = get_settings()
    secret = settings.WEBUI_BRIDGE_AUTH_TOKEN
    if not secret:
        raise RuntimeError('Falta la clave de conexión de Jessyca en la configuración local.')
    base = 'http://127.0.0.1:8088'
    http = requests.Session()
    http.trust_env = False
    try:
        http.get('http://127.0.0.1:11434/api/tags', timeout=1).raise_for_status()
    except requests.RequestException:
        ollama = shutil.which('ollama')
        if ollama:
            subprocess.Popen([ollama, 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)

    def ready():
        try:
            response = http.get(base + '/health', timeout=1)
            return response.ok and response.json().get('service') == 'jessyca-webui-bridge'
        except (requests.RequestException, ValueError):
            return False

    if not ready():
        (ROOT / 'logs').mkdir(exist_ok=True)
        with (ROOT / 'logs' / 'studio_backend.log').open('a', encoding='utf-8') as log:
            subprocess.Popen([str(ROOT / 'venv' / 'Scripts' / 'python.exe'), str(ROOT / 'main.py'),
                              'serve', '--host', '127.0.0.1', '--port', '8088'],
                             cwd=ROOT, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 35
        while not ready():
            if time.monotonic() > deadline:
                raise RuntimeError('Jessyca no pudo iniciar. Revisa logs/studio_backend.log en su carpeta de instalación.')
            time.sleep(.3)
    response = http.get(base + '/studio/api/status', headers={'Authorization': 'Bearer ' + secret}, timeout=5)
    if not response.ok:
        raise RuntimeError('El servicio abierto no corresponde a esta instalación de Jessyca. No se cerró ningún programa.')
    ticket = make_launch_ticket(secret)
    url = base + '/studio#pair=' + ticket
    browser = AuroraWindowManager().find_browser_executable()
    if browser:
        profile = Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'data'))) / 'Jessyca' / 'AuroraProfile'
        subprocess.Popen([str(browser), '--app=' + url, '--window-size=1500,960', '--no-first-run',
                          '--user-data-dir=' + str(profile)], cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        webbrowser.open(url)


if __name__ == '__main__':
    try:
        launch()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, str(exc), 'JESSYCA · Inicio', 0x10)
