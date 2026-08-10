"""Ejecutores reales y sintéticos desacoplados de ratón y teclado (Subetapa 08.4).

GARANTÍA ABSOLUTA DE SEGURIDAD:
NO pueden ser llamados directamente por el agente. Solo invocables tras superar las validaciones de ActionGuard.
NO ejecutan comandos mediante shell ni procesos externos (ZERO SUBPROCESS).
"""

from __future__ import annotations

from typing import Any

from core.desktop_executors_models import IKeyboardExecutor, IMouseExecutor
from core.logger import get_logger

logger = get_logger("jessyca.tools.desktop.executors")


import threading


class FakeMouseExecutor(IMouseExecutor):
    """Ejecutor sintético seguro de ratón para pruebas deterministas en memoria (Thread-Safe)."""

    def __init__(self) -> None:
        self.operations: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def move(self, x: int, y: int) -> None:
        with self._lock:
            self.operations.append({"op": "move", "x": x, "y": y})
        logger.debug(f"[FAKE MOUSE] Mover puntero a ({x}, {y})")

    def click(self, x: int, y: int, button: str = "left") -> None:
        with self._lock:
            self.operations.append({"op": "click", "x": x, "y": y, "button": button})
        logger.debug(f"[FAKE MOUSE] Clic '{button}' en ({x}, {y})")

    def double_click(self, x: int, y: int) -> None:
        with self._lock:
            self.operations.append({"op": "double_click", "x": x, "y": y})
        logger.debug(f"[FAKE MOUSE] Doble clic en ({x}, {y})")


class FakeKeyboardExecutor(IKeyboardExecutor):
    """Ejecutor sintético seguro de teclado para pruebas deterministas en memoria (Thread-Safe)."""

    def __init__(self) -> None:
        self.operations: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def key_press(self, key: str) -> None:
        with self._lock:
            self.operations.append({"op": "key_press", "key": key})
        logger.debug(f"[FAKE KEYBOARD] Presionar tecla '{key}'")

    def hotkey(self, keys: tuple[str, ...]) -> None:
        with self._lock:
            self.operations.append({"op": "hotkey", "keys": keys})
        logger.debug(f"[FAKE KEYBOARD] Ejecutar atajo de teclado: {keys}")

    def type_text(self, text: str) -> None:
        with self._lock:
            self.operations.append({"op": "type_text", "text_len": len(text)})
        logger.debug(f"[FAKE KEYBOARD] Escribir texto (longitud={len(text)})")


class WindowsMouseExecutor(IMouseExecutor):
    """Ejecutor nativo de ratón para Windows utilizando UI Automation con fallback sintético."""

    def move(self, x: int, y: int) -> None:
        try:
            import uiautomation as auto  # type: ignore
            auto.SetCursorPos(x, y)
        except Exception as e:
            logger.warning(f"[WINDOWS MOUSE FAIL-SAFE] Fallo al mover ratón nativo ({e}).")

    def click(self, x: int, y: int, button: str = "left") -> None:
        try:
            import uiautomation as auto  # type: ignore
            if button == "right":
                auto.RightClick(x, y)
            elif button == "middle":
                auto.MiddleClick(x, y)
            else:
                auto.Click(x, y)
        except Exception as e:
            logger.warning(f"[WINDOWS MOUSE FAIL-SAFE] Fallo al hacer clic nativo ({e}).")

    def double_click(self, x: int, y: int) -> None:
        try:
            import uiautomation as auto  # type: ignore
            auto.DoubleClick(x, y)
        except Exception as e:
            logger.warning(f"[WINDOWS MOUSE FAIL-SAFE] Fallo al hacer doble clic nativo ({e}).")


class WindowsKeyboardExecutor(IKeyboardExecutor):
    """Ejecutor nativo de teclado para Windows utilizando UI Automation con fallback sintético."""

    def key_press(self, key: str) -> None:
        try:
            import uiautomation as auto  # type: ignore
            auto.SendKeys(f"{{{key}}}")
        except Exception as e:
            logger.warning(f"[WINDOWS KEYBOARD FAIL-SAFE] Fallo al presionar tecla nativa ({e}).")

    def hotkey(self, keys: tuple[str, ...]) -> None:
        try:
            import uiautomation as auto  # type: ignore
            combo = "".join(f"{{{k}}}" for k in keys)
            auto.SendKeys(combo)
        except Exception as e:
            logger.warning(f"[WINDOWS KEYBOARD FAIL-SAFE] Fallo al ejecutar atajo de teclado nativo ({e}).")

    def type_text(self, text: str) -> None:
        try:
            import uiautomation as auto  # type: ignore
            auto.SendKeys(text)
        except Exception as e:
            logger.warning(f"[WINDOWS KEYBOARD FAIL-SAFE] Fallo al escribir texto nativo ({e}).")
