"""Gestor de Ciclo de Vida y Runtime para JESSYCA ORB — Núcleo Aurora 3D.

Orquesta de forma atómica y desacoplada:
1. El servidor FastAPI/Uvicorn con WebSockets.
2. La ventana nativa de escritorio de Windows 11 (Edge/Chromium App Mode).
3. El puente de integración (AuroraBridge) con StateMachine, EventBus, captura y TTS.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from typing import Any

import uvicorn

from core.logger import get_logger
from interfaces.aurora.bridge import AuroraBridge
from interfaces.aurora.server import AuroraServerManager
from interfaces.aurora.window_manager import AuroraWindowManager

logger = get_logger("jessyca.aurora.runtime")


class AuroraRuntime:
    """Runtime desacoplado del Orbe Aurora 3D para JESSYCA."""

    _active_runtime: AuroraRuntime | None = None

    def __init__(
        self,
        port: int = 8765,
        headless: bool = False,
        width: int = 720,
        height: int = 720,
    ) -> None:
        self.port = port
        self.headless = headless
        self.server_manager = AuroraServerManager(port=self.port)
        self.actual_port = self.server_manager.actual_port
        self.window_manager = AuroraWindowManager(
            port=self.actual_port,
            width=width,
            height=height,
        )
        self.bridge = AuroraBridge(server_manager=self.server_manager)

        self._server_thread: threading.Thread | None = None
        self._is_running = False
        self._server_obj: uvicorn.Server | None = None

    @classmethod
    def get_active_runtime(cls) -> AuroraRuntime | None:
        return cls._active_runtime

    def start(self) -> bool:
        """Inicia el servidor y la ventana de escritorio en modo seguro no bloqueante."""
        if self._is_running:
            logger.info("[AURORA RUNTIME] Ya se encuentra en ejecución.")
            return True

        logger.info(f"[AURORA RUNTIME] Iniciando servidor en puerto {self.actual_port}...")

        config = uvicorn.Config(
            app=self.server_manager.app,
            host="127.0.0.1",
            port=self.actual_port,
            log_level="warning",
            access_log=False,
        )
        self._server_obj = uvicorn.Server(config)

        def _run() -> None:
            try:
                self._server_obj.run()
            except Exception as e:
                logger.error(f"[AURORA RUNTIME] Error en servidor Uvicorn: {e}")

        self._server_thread = threading.Thread(target=_run, daemon=True, name="AuroraServerWorker")
        self._server_thread.start()

        # Esperar hasta que el puerto esté activo
        t0 = time.time()
        ready = False
        while time.time() - t0 < 3.0:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", self.actual_port)) == 0:
                    ready = True
                    break
            time.sleep(0.08)

        if not ready:
            logger.warning(f"[AURORA RUNTIME] Tiempo de espera agotado esperando puerto {self.actual_port}")

        # Lanzar ventana nativa en Windows 11 si no es modo headless
        if not self.headless:
            logger.info("[AURORA RUNTIME] Lanzando ventana de escritorio nativa Edge/Chromium...")
            self.window_manager.launch()

        self._is_running = True
        AuroraRuntime._active_runtime = self
        logger.info(f"[AURORA RUNTIME] Orbe Aurora 3D operativo exitosamente en http://127.0.0.1:{self.actual_port}")
        return True

    def stop(self) -> None:
        """Detiene ordenadamente la ventana, los WebSockets y el servidor."""
        if not self._is_running:
            return

        logger.info("[AURORA RUNTIME] Deteniendo Orbe Aurora...")
        self._is_running = False

        # 1. Cerrar ventana gráfica
        self.window_manager.close()

        # 2. Liberar recursos del bridge
        self.bridge.close()

        # 3. Detener servidor Uvicorn
        if self._server_obj:
            self._server_obj.should_exit = True

        if AuroraRuntime._active_runtime is self:
            AuroraRuntime._active_runtime = None

        logger.info("[AURORA RUNTIME] Orbe Aurora detenido y recursos liberados.")
