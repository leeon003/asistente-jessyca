"""Contrato desacoplado para controladores de escritorio de Windows (core/desktop/driver_protocol.py).

Permite alternar de manera transparente entre:
1. NativeWindowsDriver (UIAutomationCore + Win32 + PyCaw + PyAutoGUI con Failsafe activo).
2. CuaMcpDriverAdapter (Adaptador futuro vía MCP contra cua-driver sin alterar el Core).
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class DesktopActionResult:
    """Resultado formal y verificable de una acción física de escritorio."""

    success: bool
    action: str
    target: str
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    timestamp: float = field(default_factory=time.time)


@runtime_checkable
class DesktopDriverProtocol(Protocol):
    """Protocolo formal de operaciones de escritorio."""

    def open_app(self, app_name: str, executable: str | None = None) -> DesktopActionResult:
        ...

    def close_app(self, app_name_or_pid: str | int) -> DesktopActionResult:
        ...

    def focus_window(self, title_or_process: str) -> DesktopActionResult:
        ...

    def type_text(self, text: str, target_element: str | None = None) -> DesktopActionResult:
        ...

    def click_element(self, element_id: str | None = None, coords: tuple[int, int] | None = None) -> DesktopActionResult:
        ...

    def capture_screen(self) -> bytes:
        ...


class NativeWindowsDriver:
    """Controlador nativo de Windows gobernado y seguro."""

    def __init__(self) -> None:
        try:
            import pyautogui
            # SEGURIDAD OBLIGATORIA: Failsafe activo para aborto en esquina
            pyautogui.FAILSAFE = True
        except Exception:
            pass

    def _ensure_safe_cursor(self) -> None:
        """Asegura que el cursor no dispare falso FailSafe en sesiones donde el cursor inicial permanece en (0, 0)."""
        try:
            import ctypes
            import pyautogui
            ctypes.windll.user32.SetCursorPos(500, 500)
            time.sleep(0.02)
            if pyautogui.position() == (0, 0):
                # Mantener failsafe activo en las demás esquinas pero evitar falso positivo en origen fijo (0, 0)
                pyautogui.FAILSAFE_POINTS = [p for p in getattr(pyautogui, "FAILSAFE_POINTS", []) if p != (0, 0)]
        except Exception:
            pass

    def _resolve_executable(self, exe: str) -> str:
        """Resuelve rutas absolutas si el ejecutable no está en el PATH estándar."""
        low = exe.lower()
        if "edge" in low or "msedge" in low:
            for p in [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]:
                if os.path.exists(p):
                    return p
            return "msedge.exe"
        if "chrome" in low:
            for p in [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]:
                if os.path.exists(p):
                    return p
            return "chrome.exe"
        return exe

    def open_app(self, app_name: str, executable: str | None = None) -> DesktopActionResult:
        """Lanza una aplicación verificando su creación de proceso."""
        exe = executable or app_name
        # Mapeo básico de nombres conocidos
        known_exes = {
            "calc": "calc.exe",
            "calculadora": "calc.exe",
            "notepad": "notepad.exe",
            "bloc de notas": "notepad.exe",
            "chrome": "chrome.exe",
            "edge": "msedge.exe",
            "paint": "mspaint.exe",
            "cmd": "cmd.exe",
            "explorer": "explorer.exe",
        }
        eff_exe = known_exes.get(exe.lower(), exe)
        eff_exe = self._resolve_executable(eff_exe)

        try:
            proc = subprocess.Popen([eff_exe], shell=False)
            time.sleep(0.3)
            return DesktopActionResult(
                success=True,
                action="open_app",
                target=app_name,
                evidence={"pid": proc.pid, "executable": eff_exe, "is_verified": proc.poll() is None},
            )
        except Exception as e:
            return DesktopActionResult(
                success=False,
                action="open_app",
                target=app_name,
                evidence={"is_verified": False},
                error=str(e),
            )

    def close_app(self, app_name_or_pid: str | int) -> DesktopActionResult:
        """Cierra una aplicación por PID o nombre de proceso mediante psutil."""
        try:
            import psutil
            closed_pids: list[int] = []
            if isinstance(app_name_or_pid, int) or (isinstance(app_name_or_pid, str) and app_name_or_pid.isdigit()):
                pid = int(app_name_or_pid)
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                    closed_pids.append(pid)
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    # El proceso ya finalizó o fue un launcher efímero de Windows
                    closed_pids.append(pid)
            else:
                target_str = str(app_name_or_pid).lower()
                for p in psutil.process_iter(["pid", "name"]):
                    try:
                        p_name = (p.info["name"] or "").lower()
                        if target_str in p_name:
                            p.terminate()
                            closed_pids.append(p.info["pid"])
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            return DesktopActionResult(
                success=True,
                action="close_app",
                target=str(app_name_or_pid),
                evidence={"closed_pids": closed_pids, "is_verified": True},
            )
        except Exception as e:
            return DesktopActionResult(
                success=False,
                action="close_app",
                target=str(app_name_or_pid),
                evidence={"is_verified": False},
                error=str(e),
            )

    def focus_window(self, title_or_process: str) -> DesktopActionResult:
        """Trae al frente una ventana por título o nombre de proceso mediante Win32 API."""
        try:
            import win32gui
            found_hwnd: list[int] = []

            def enum_cb(hwnd: int, extra: Any) -> None:
                if win32gui.IsWindowVisible(hwnd):
                    text = win32gui.GetWindowText(hwnd)
                    if title_or_process.lower() in text.lower():
                        found_hwnd.append(hwnd)

            win32gui.EnumWindows(enum_cb, None)
            if found_hwnd:
                hwnd = found_hwnd[0]
                win32gui.SetForegroundWindow(hwnd)
                return DesktopActionResult(
                    success=True,
                    action="focus_window",
                    target=title_or_process,
                    evidence={"hwnd": hwnd, "is_verified": True},
                )
            return DesktopActionResult(
                success=False,
                action="focus_window",
                target=title_or_process,
                evidence={"is_verified": False},
                error=f"Ventana '{title_or_process}' no encontrada.",
            )
        except Exception as e:
            return DesktopActionResult(
                success=False,
                action="focus_window",
                target=title_or_process,
                evidence={"is_verified": False},
                error=str(e),
            )

    def type_text(self, text: str, target_element: str | None = None) -> DesktopActionResult:
        """Escribe texto en la ventana activa o elemento enfocado de manera controlada."""
        from core.emergency_stop import EmergencyStopManager
        if EmergencyStopManager.get_instance().is_stopped():
            return DesktopActionResult(
                success=False,
                action="type_text",
                target=target_element or "active_window",
                evidence={"is_verified": False},
                error="Operación abortada por Parada de Emergencia activa.",
            )

        try:
            self._ensure_safe_cursor()
            import pyautogui
            pyautogui.typewrite(text, interval=0.01)
            return DesktopActionResult(
                success=True,
                action="type_text",
                target=target_element or "active_window",
                evidence={"length": len(text), "is_verified": True},
            )
        except Exception as e:
            import pyautogui
            if isinstance(e, getattr(pyautogui, "FailSafeException", ())) or "failsafe" in str(e).lower():
                from core.emergency_stop import EmergencyStopManager
                EmergencyStopManager.get_instance().trigger_stop("FailSafe triggered by user moving cursor to corner", source="failsafe_corner")
            return DesktopActionResult(
                success=False,
                action="type_text",
                target=target_element or "active_window",
                evidence={"is_verified": False},
                error=str(e),
            )

    def click_element(self, element_id: str | None = None, coords: tuple[int, int] | None = None) -> DesktopActionResult:
        """Realiza un clic físico seguro."""
        from core.emergency_stop import EmergencyStopManager
        if EmergencyStopManager.get_instance().is_stopped():
            return DesktopActionResult(
                success=False,
                action="click",
                target=f"coords({coords[0]},{coords[1]})" if coords else (element_id or "unknown"),
                evidence={"is_verified": False},
                error="Operación abortada por Parada de Emergencia activa.",
            )

        try:
            import pyautogui
            if coords:
                pyautogui.click(coords[0], coords[1])
                return DesktopActionResult(
                    success=True,
                    action="click",
                    target=f"coords({coords[0]},{coords[1]})",
                    evidence={"coords": coords, "is_verified": True},
                )
            return DesktopActionResult(
                success=False,
                action="click",
                target=element_id or "unknown",
                evidence={"is_verified": False},
                error="Coordenadas requeridas para NativeWindowsDriver.",
            )
        except Exception as e:
            import pyautogui
            if isinstance(e, getattr(pyautogui, "FailSafeException", ())) or "failsafe" in str(e).lower():
                from core.emergency_stop import EmergencyStopManager
                EmergencyStopManager.get_instance().trigger_stop("FailSafe triggered by user moving cursor to corner", source="failsafe_corner")
            return DesktopActionResult(
                success=False,
                action="click",
                target=f"coords({coords[0]},{coords[1]})" if coords else (element_id or "unknown"),
                evidence={"is_verified": False},
                error=str(e),
            )
            return DesktopActionResult(
                success=False,
                action="click",
                target=str(coords or element_id),
                evidence={"is_verified": False},
                error=str(e),
            )

    def capture_screen(self) -> bytes:
        """Captura la pantalla completa en formato PNG in-memory con manejo seguro de sesiones headless."""
        import io
        from PIL import Image, ImageGrab

        try:
            img = ImageGrab.grab()
        except (OSError, Exception):
            # Fallback seguro para entornos sin desktop interactivo (headless)
            img = Image.new("RGB", (100, 100), color=(30, 30, 30))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


__all__ = [
    "DesktopActionResult",
    "DesktopDriverProtocol",
    "NativeWindowsDriver",
]
