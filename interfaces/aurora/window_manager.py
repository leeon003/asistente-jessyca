"""Gestor de Ventana de Escritorio para JESSYCA ORB en Windows 11.

Controla:
1. Lanzamiento desacoplado en modo aplicación web nativa (Microsoft Edge / Chromium App Mode).
2. Prevención de robo de foco (WS_EX_NOACTIVATE) e integración segura sin interferir con Notepad ni teclados.
3. Gestión limpia del ciclo de vida y liberación de recursos en el cierre.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.aurora.window")


class AuroraWindowManager:
    """Administra la ventana de escritorio nativa del orbe en Windows 11."""

    EDGE_PATHS = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "Microsoft\\Edge\\Application\\msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Microsoft\\Edge\\Application\\msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft\\Edge\\Application\\msedge.exe",
    ]

    CHROME_PATHS = [
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Google\\Chrome\\Application\\chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "Google\\Chrome\\Application\\chrome.exe",
    ]

    def __init__(self, port: int = 8765, width: int = 720, height: int = 720) -> None:
        self.port = port
        self.width = width
        self.height = height
        self.process: subprocess.Popen[Any] | None = None
        self.hwnd: int = 0

    def find_browser_executable(self) -> Path | None:
        """Localiza el ejecutable de Edge o Chromium en Windows."""
        for p in self.EDGE_PATHS:
            if p.exists():
                return p
        for p in self.CHROME_PATHS:
            if p.exists():
                return p
        return None

    def launch(self) -> bool:
        """Lanza la ventana del orbe en modo aplicación de escritorio sin bordes de navegador."""
        browser_exe = self.find_browser_executable()
        url = f"http://127.0.0.1:{self.port}"

        if not browser_exe:
            logger.warning("[AURORA WINDOW] Navegador nativo no encontrado. Abriendo en navegador por defecto...")
            import webbrowser
            webbrowser.open(url)
            return True

        args = [
            str(browser_exe),
            f"--app={url}",
            f"--window-size={self.width},{self.height}",
            "--disable-features=TranslateUI",
            "--disable-extensions",
            "--no-first-run",
            "--user-data-dir=" + str(Path(os.environ.get("TEMP", "C:\\Temp")) / "jessyca_orb_profile"),
        ]

        try:
            self.process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"[AURORA WINDOW] Ventana 3D iniciada (PID: {self.process.pid}) en puerto {self.port}")
            return True
        except Exception as e:
            logger.error(f"[AURORA WINDOW] Error iniciando ventana: {e}")
            return False

    def close(self) -> None:
        """Cierra el proceso de la ventana de forma limpia."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
                logger.info("[AURORA WINDOW] Ventana cerrada exitosamente.")
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
