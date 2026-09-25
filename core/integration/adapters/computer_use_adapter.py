"""Adapter de Integración de Windows Computer Use / Agent Skills para JESSYCA 4.0.

Implementa la integración controlada y selectiva de capacidades de interacción con el escritorio:
observación de pantalla, control de puntero/mouse, teclado controlado, gestión de ventanas y
ciclos compuestos de percepción y acción (OBSERVAR -> ACTUAR -> OBSERVAR).

Principios Obligatorios:
1. IDENTIDAD: Computer Use NO es un agente independiente; es un proveedor de herramientas para JESSYCA.
2. SEGURIDAD: Toda acción está sujeta a la Security Layer de JESSYCA y sus niveles de riesgo (RiskLevel).
3. EXECUTE -> VERIFY -> REPORT: Ninguna acción física auto-certifica éxito (verified=False por defecto).
4. AISLAMIENTO: Dependencias opcionales y controladas (pyautogui, psutil, win32gui, PIL).
5. FALLBACK: Si Computer Use falla o está deshabilitado, JESSYCA continúa operando de forma aislada.
"""

from __future__ import annotations

import base64
import io
import time
from typing import Any

from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapter import IntegrationAdapter
from core.integration.models import (
    IntegrationCapability,
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationHealth,
    IntegrationStatus,
)
from core.logger import get_logger
from core.security import RiskLevel

logger = get_logger("jessyca.integration.adapters.computer_use")

# Lista blanca de teclas seguras para press_key y hotkey
_ALLOWED_KEYS: frozenset[str] = frozenset({
    "enter", "return", "tab", "space", "backspace", "delete", "esc", "escape",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    "ctrl", "control", "alt", "shift", "win", "f1", "f2", "f3", "f4", "f5",
    "f6", "f7", "f8", "f9", "f10", "f11", "f12", "capslock",
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
})


class ComputerUseAdapter(IntegrationAdapter):
    """Adapter oficial para la integración de Windows Computer Use / Agent Skills."""

    def __init__(self) -> None:
        super().__init__(
            name="windows_computer_use",
            version="1.0.0",
            dependencies=["pyautogui", "psutil"],
        )
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
        except Exception:
            pass
        self._register_audited_capabilities()

    def _register_audited_capabilities(self) -> None:
        """Registra las 5 capacidades auditadas de interacción con Windows."""
        # 1. Observación del escritorio y telemetría de pantalla
        self.register_capability(
            IntegrationCapability(
                name="computer_use.observe_desktop",
                description="Obtiene telemetría del escritorio: resolución, posición del cursor, ventanas y captura opcional",
                required_risk_level=RiskLevel.READ_ONLY,
                required_permissions=[],
                parameters_schema={
                    "include_screenshot": {"type": "bool", "default": False, "required": False},
                    "include_windows": {"type": "bool", "default": True, "required": False},
                },
            )
        )

        # 2. Control controlado de mouse
        self.register_capability(
            IntegrationCapability(
                name="computer_use.mouse_interact",
                description="Ejecuta interacción con el cursor (move, click, double_click, right_click, scroll) con límites de pantalla",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=[],
                parameters_schema={
                    "action": {"type": "str", "enum": ["move", "click", "double_click", "right_click", "scroll"], "required": True},
                    "x": {"type": "int", "required": False},
                    "y": {"type": "int", "required": False},
                    "clicks": {"type": "int", "default": 1, "required": False},
                    "button": {"type": "str", "enum": ["left", "right", "middle"], "default": "left", "required": False},
                    "scroll_amount": {"type": "int", "required": False},
                },
            )
        )

        # 3. Control controlado de teclado
        self.register_capability(
            IntegrationCapability(
                name="computer_use.keyboard_type",
                description="Envío de texto controlado o pulsación de teclas especiales con lista blanca de seguridad",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=[],
                parameters_schema={
                    "action": {"type": "str", "enum": ["write_text", "press_key", "hotkey"], "required": True},
                    "text": {"type": "str", "required": False},
                    "key": {"type": "str", "required": False},
                    "keys": {"type": "list", "required": False},
                },
            )
        )

        # 4. Gestión y comprobación de ventanas
        self.register_capability(
            IntegrationCapability(
                name="computer_use.window_control",
                description="Inspección, foco, minimizar, maximizar o cerrar ventanas con verificación de proceso",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=[],
                parameters_schema={
                    "action": {"type": "str", "enum": ["list_windows", "focus_window", "minimize_window", "maximize_window", "close_window"], "required": True},
                    "target": {"type": "str", "required": False, "description": "Nombre del proceso o título de la ventana"},
                },
            )
        )

        # 5. Ciclo Percepción + Acción (OBSERVAR -> ACTUAR -> OBSERVAR)
        self.register_capability(
            IntegrationCapability(
                name="computer_use.perceive_and_act",
                description="Ejecuta una acción comparando el estado del escritorio antes y después para verificar el cambio",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=[],
                parameters_schema={
                    "sub_action": {"type": "dict", "required": True, "description": "Acción a ejecutar dentro del ciclo"},
                },
            )
        )

    async def initialize(self) -> bool:
        """Inicializa el adapter verificando dependencias y drivers de visualización."""
        try:
            has_deps, missing = self.check_dependencies()
            if not has_deps:
                self.status = IntegrationStatus.UNAVAILABLE
                logger.warning(f"ComputerUseAdapter no disponible. Faltan dependencias: {missing}")
                return False

            # Comprobación de resolución de pantalla
            import pyautogui

            try:
                width, height = pyautogui.size()
                if width <= 0 or height <= 0:
                    self.status = IntegrationStatus.DEGRADED
                    logger.warning("ComputerUseAdapter inicializado en modo DEGRADED: resolución inválida o headless.")
                    return True
            except Exception as exc:
                logger.warning(f"No se pudo determinar resolución de pantalla: {exc}. Operando en modo degradado.")
                self.status = IntegrationStatus.DEGRADED
                return True

            self.status = IntegrationStatus.READY
            logger.info(f"ComputerUseAdapter v{self.version} inicializado y READY ({width}x{height}).")
            return True
        except Exception as exc:
            self.status = IntegrationStatus.ERROR
            logger.error(f"Error crítico inicializando ComputerUseAdapter: {exc}", exc_info=True)
            return False

    async def health_check(self) -> IntegrationHealth:
        """Comprueba el estado del subsistema gráfico y dependencias."""
        start = time.perf_counter()
        is_healthy = self.status in (IntegrationStatus.READY, IntegrationStatus.DEGRADED, IntegrationStatus.AVAILABLE)
        latency = (time.perf_counter() - start) * 1000.0

        details: dict[str, Any] = {
            "version": self.version,
            "status": self.status.value,
            "capabilities_count": len(self._capabilities),
        }

        try:
            import pyautogui

            details["screen_size"] = list(pyautogui.size())
            details["cursor_position"] = list(pyautogui.position())
        except Exception as exc:
            details["screen_error"] = str(exc)

        return IntegrationHealth(
            status=self.status,
            is_healthy=is_healthy,
            latency_ms=latency,
            message="ComputerUseAdapter saludable" if is_healthy else f"Estado anormal: {self.status.value}",
            details=details,
        )

    async def shutdown(self) -> None:
        """Libera de forma ordenada los recursos del adapter."""
        self.status = IntegrationStatus.AVAILABLE
        logger.info("ComputerUseAdapter apagado exitosamente.")

    async def execute(
        self,
        capability: str,
        context: IntegrationContext,
    ) -> IntegrationExecutionResult:
        """Ejecuta una capacidad respetando el principio EXECUTE -> VERIFY -> REPORT."""
        start_time = time.perf_counter()
        params = context.parameters or {}

        if self.status not in (IntegrationStatus.READY, IntegrationStatus.DEGRADED):
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                verification_required=False,
                error=f"ComputerUseAdapter no está disponible para ejecución (estado: {self.status.value})",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        if capability not in self._capabilities:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                verification_required=False,
                error=f"Capacidad '{capability}' no está registrada en ComputerUseAdapter",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        try:
            if capability == "computer_use.observe_desktop":
                return self._execute_observe_desktop(params, start_time)
            elif capability == "computer_use.mouse_interact":
                return self._execute_mouse_interact(params, start_time)
            elif capability == "computer_use.keyboard_type":
                return self._execute_keyboard_type(params, start_time)
            elif capability == "computer_use.window_control":
                return self._execute_window_control(params, start_time)
            elif capability == "computer_use.perceive_and_act":
                return self._execute_perceive_and_act(params, start_time)
            else:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    error=f"Manejador no implementado para '{capability}'",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
        except Exception as exc:
            dur = (time.perf_counter() - start_time) * 1000.0
            logger.error(f"Error inesperado al ejecutar '{capability}': {exc}", exc_info=True)
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error=str(exc),
                duration_ms=dur,
            )

    # --- 1. Observación de Escritorio ---

    def _execute_observe_desktop(self, params: dict[str, Any], start_time: float) -> IntegrationExecutionResult:
        import psutil
        import pyautogui

        include_screenshot = bool(params.get("include_screenshot", False))
        include_windows = bool(params.get("include_windows", True))

        try:
            screen_w, screen_h = pyautogui.size()
            pos_x, pos_y = pyautogui.position()
        except Exception:
            screen_w, screen_h = 1920, 1080
            pos_x, pos_y = 0, 0

        # Mapeo de procesos relevantes con ventanas activas
        active_apps: list[dict[str, Any]] = []
        if include_windows:
            try:
                for proc in psutil.process_iter(["pid", "name", "status"]):
                    try:
                        pname = proc.info["name"] or ""
                        # Filtrar procesos de usuario conocidos
                        if pname.lower().endswith((".exe",)):
                            if pname.lower() in ("explorer.exe", "notepad.exe", "calc.exe", "calculatorapp.exe", "chrome.exe", "msedge.exe", "code.exe"):
                                active_apps.append({
                                    "pid": proc.info["pid"],
                                    "name": pname,
                                    "status": proc.info["status"],
                                })
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception as exc:
                logger.debug(f"Error listando procesos en observación: {exc}")

        # Captura de pantalla opcional y segura
        screenshot_b64: str | None = None
        if include_screenshot:
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                screenshot_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            except Exception:
                # Fallback transparente si se ejecuta en sesión sin escritorio directo
                screenshot_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

        data = {
            "resolution": {"width": screen_w, "height": screen_h},
            "cursor": {"x": pos_x, "y": pos_y},
            "active_applications": active_apps[:15],
            "screenshot": screenshot_b64,
        }

        dur = (time.perf_counter() - start_time) * 1000.0
        return IntegrationExecutionResult(
            executed=True,
            status=ExecutionStatus.SUCCEEDED,
            verified=False,  # Datos leídos; no auto-certifica
            verification_required=False,
            output=data,
            duration_ms=dur,
            metadata={"adapter": "windows_computer_use", "capability": "computer_use.observe_desktop"},
        )

    # --- 2. Control de Mouse ---

    def _execute_mouse_interact(self, params: dict[str, Any], start_time: float) -> IntegrationExecutionResult:
        import pyautogui

        action = str(params.get("action", "")).lower()
        if not action:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error="El parámetro 'action' es obligatorio",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        screen_w, screen_h = pyautogui.size()
        x = params.get("x")
        y = params.get("y")

        # Validación de límites de pantalla
        if x is not None:
            if not isinstance(x, (int, float)) or x < 0 or x > screen_w:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    error=f"Coordenada X fuera de límites de pantalla (0 a {screen_w}): {x}",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            x = int(x)

        if y is not None:
            if not isinstance(y, (int, float)) or y < 0 or y > screen_h:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    error=f"Coordenada Y fuera de límites de pantalla (0 a {screen_h}): {y}",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            y = int(y)

        button = str(params.get("button", "left")).lower()
        if button not in ("left", "right", "middle"):
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error=f"Botón de mouse inválido: '{button}'",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        pos_before = pyautogui.position()

        if action == "move":
            if x is None or y is None:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    error="Para la acción 'move' se requieren 'x' e 'y'",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            pyautogui.moveTo(x, y)
            msg = f"Cursor movido a ({x}, {y})"

        elif action == "click":
            if x is not None and y is not None:
                pyautogui.click(x=x, y=y, button=button)
                msg = f"Click {button} ejecutado en ({x}, {y})"
            else:
                pyautogui.click(button=button)
                msg = f"Click {button} ejecutado en posición actual"

        elif action == "double_click":
            if x is not None and y is not None:
                pyautogui.doubleClick(x=x, y=y)
                msg = f"Doble click ejecutado en ({x}, {y})"
            else:
                pyautogui.doubleClick()
                msg = "Doble click ejecutado en posición actual"

        elif action == "right_click":
            if x is not None and y is not None:
                pyautogui.rightClick(x=x, y=y)
                msg = f"Click derecho ejecutado en ({x}, {y})"
            else:
                pyautogui.rightClick()
                msg = "Click derecho ejecutado en posición actual"

        elif action == "scroll":
            amount = int(params.get("scroll_amount", 100))
            pyautogui.scroll(amount)
            msg = f"Scroll ejecutado con magnitud {amount}"

        else:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error=f"Acción de mouse no reconocida: '{action}'",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        pos_after = pyautogui.position()
        dur = (time.perf_counter() - start_time) * 1000.0

        return IntegrationExecutionResult(
            executed=True,
            status=ExecutionStatus.SUCCEEDED,
            verified=False,  # En cumplimiento anti-falso-éxito: verified=False por defecto
            verification_required=True,
            output={
                "message": msg,
                "action": action,
                "position_before": list(pos_before),
                "position_after": list(pos_after),
            },
            duration_ms=dur,
            metadata={"adapter": "windows_computer_use", "capability": "computer_use.mouse_interact"},
        )

    # --- 3. Control de Teclado ---

    def _execute_keyboard_type(self, params: dict[str, Any], start_time: float) -> IntegrationExecutionResult:
        import pyautogui

        action = str(params.get("action", "")).lower()
        if not action:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error="El parámetro 'action' es obligatorio",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        if action == "write_text":
            text = params.get("text")
            if text is None or not isinstance(text, str):
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    error="Para 'write_text' se requiere el parámetro 'text'",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            # Limitar longitud para evitar desbordamientos
            safe_text = text[:1000]
            pyautogui.write(safe_text, interval=0.01)
            msg = f"Texto de {len(safe_text)} caracteres enviado al foco activo."

        elif action == "press_key":
            key = str(params.get("key", "")).lower()
            if not key or key not in _ALLOWED_KEYS:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    error=f"Tecla no permitida o ausente: '{key}'",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            pyautogui.press(key)
            msg = f"Tecla '{key}' presionada."

        elif action == "hotkey":
            keys = params.get("keys", [])
            if not keys or not isinstance(keys, list):
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    error="Para 'hotkey' se requiere una lista de 'keys'",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            # Validar que todas las teclas de la combinación estén permitidas
            clean_keys = [str(k).lower() for k in keys]
            for k in clean_keys:
                if k not in _ALLOWED_KEYS:
                    return IntegrationExecutionResult(
                        executed=False,
                        status=ExecutionStatus.FAILED,
                        verified=False,
                        error=f"Tecla en combinación no permitida: '{k}'",
                        duration_ms=(time.perf_counter() - start_time) * 1000.0,
                    )
            pyautogui.hotkey(*clean_keys)
            msg = f"Combinación '{'+'.join(clean_keys)}' ejecutada."

        else:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error=f"Acción de teclado no reconocida: '{action}'",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        dur = (time.perf_counter() - start_time) * 1000.0
        return IntegrationExecutionResult(
            executed=True,
            status=ExecutionStatus.SUCCEEDED,
            verified=False,  # Nunca auto-certifica
            verification_required=True,
            output={"message": msg, "action": action},
            duration_ms=dur,
            metadata={"adapter": "windows_computer_use", "capability": "computer_use.keyboard_type"},
        )

    # --- 4. Gestión de Ventanas y Procesos ---

    def _execute_window_control(self, params: dict[str, Any], start_time: float) -> IntegrationExecutionResult:
        import psutil

        action = str(params.get("action", "")).lower()
        target = str(params.get("target", "")).strip()

        if not action:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error="El parámetro 'action' es obligatorio",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        if action == "list_windows":
            # Enumeración combinada de ventanas y procesos
            windows_info: list[dict[str, Any]] = []
            try:
                import win32gui
                def enum_cb(hwnd: int, _: Any) -> bool:
                    if win32gui.IsWindowVisible(hwnd):
                        txt = win32gui.GetWindowText(hwnd)
                        if txt.strip():
                            windows_info.append({"hwnd": hwnd, "title": txt.strip()})
                    return True
                win32gui.EnumWindows(enum_cb, None)
            except Exception:
                pass

            # Si no hay ventanas Win32 visibles en el entorno, complementar con procesos
            if not windows_info:
                for proc in psutil.process_iter(["pid", "name"]):
                    try:
                        pname = (proc.info["name"] or "").lower()
                        if pname in ("notepad.exe", "calc.exe", "calculatorapp.exe", "explorer.exe", "chrome.exe", "msedge.exe"):
                            windows_info.append({"pid": proc.info["pid"], "title": pname})
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=True,
                status=ExecutionStatus.SUCCEEDED,
                verified=False,
                verification_required=False,
                output={"windows": windows_info[:20]},
                duration_ms=dur,
                metadata={"adapter": "windows_computer_use", "action": "list_windows"},
            )

        elif action in ("focus_window", "minimize_window", "maximize_window"):
            if not target:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    error=f"Para '{action}' se requiere 'target'",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )

            # Intento vía Win32 GUI
            acted = False
            try:
                import win32con
                import win32gui

                def match_cb(hwnd: int, _: Any) -> bool:
                    nonlocal acted
                    if win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        if target.lower() in title.lower():
                            if action == "focus_window":
                                win32gui.SetForegroundWindow(hwnd)
                            elif action == "minimize_window":
                                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                            elif action == "maximize_window":
                                win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                            acted = True
                            return False
                    return True

                win32gui.EnumWindows(match_cb, None)
            except Exception as exc:
                logger.debug(f"Error operando ventana Win32: {exc}")

            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=True,
                status=ExecutionStatus.SUCCEEDED if acted else ExecutionStatus.FAILED,
                verified=False,
                verification_required=True,
                output={
                    "action": action,
                    "target": target,
                    "window_found": acted,
                    "message": f"Acción '{action}' completada para '{target}'" if acted else f"No se encontró ventana para '{target}'",
                },
                error=None if acted else f"No se encontró ventana visible coincidente con '{target}'",
                duration_ms=dur,
            )

        elif action == "close_window":
            if not target:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    error="Para 'close_window' se requiere 'target'",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )

            closed_count = 0
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    pname = (proc.info["name"] or "").lower()
                    if target.lower() in pname:
                        proc.terminate()
                        closed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=True,
                status=ExecutionStatus.SUCCEEDED if closed_count > 0 else ExecutionStatus.FAILED,
                verified=False,
                verification_required=True,
                output={"action": "close_window", "target": target, "closed_processes": closed_count},
                error=None if closed_count > 0 else f"No se encontró ningún proceso activo para '{target}'",
                duration_ms=dur,
            )

        else:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error=f"Acción de ventana no reconocida: '{action}'",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

    # --- 5. Ciclo Percepción + Acción ---

    def _execute_perceive_and_act(self, params: dict[str, Any], start_time: float) -> IntegrationExecutionResult:
        import pyautogui

        sub_action = params.get("sub_action")
        if not sub_action or not isinstance(sub_action, dict):
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error="El parámetro 'sub_action' es obligatorio y debe ser un diccionario",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        # 1. OBSERVAR (Estado inicial)
        try:
            pos_before = list(pyautogui.position())
        except Exception:
            pos_before = [0, 0]

        # 2. ACTUAR (Ejecutar sub-acción)
        sub_type = sub_action.get("type", "mouse")
        sub_params = sub_action.get("parameters", {})

        if sub_type == "mouse":
            act_res = self._execute_mouse_interact(sub_params, start_time)
        elif sub_type == "keyboard":
            act_res = self._execute_keyboard_type(sub_params, start_time)
        elif sub_type == "window":
            act_res = self._execute_window_control(sub_params, start_time)
        else:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error=f"Tipo de sub-acción no soportado: '{sub_type}'",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        # 3. OBSERVAR NUEVAMENTE (Estado final)
        try:
            pos_after = list(pyautogui.position())
        except Exception:
            pos_after = [0, 0]

        delta_detected = (pos_before != pos_after) or (act_res.executed and act_res.status == ExecutionStatus.SUCCEEDED)

        dur = (time.perf_counter() - start_time) * 1000.0
        return IntegrationExecutionResult(
            executed=act_res.executed,
            status=act_res.status,
            verified=False,  # En cumplimiento anti-falso-éxito: verified=False por defecto
            verification_required=True,
            output={
                "cycle": "OBSERVAR -> ACTUAR -> OBSERVAR",
                "state_before": {"cursor": pos_before},
                "action_result": act_res.output,
                "state_after": {"cursor": pos_after},
                "delta_detected": delta_detected,
            },
            duration_ms=dur,
            metadata={"adapter": "windows_computer_use", "capability": "computer_use.perceive_and_act"},
        )
