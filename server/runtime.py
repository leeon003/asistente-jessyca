"""server/runtime.py
Runtime del servidor FastMCP para el modo DEMO interactivo de JESSYCA 3.0.

Gestiona el ciclo de vida (start, stop, is_running, health) del servidor MCP
ejecutándose en segundo plano (daemon thread) sin bloquear la interfaz de usuario ni la voz.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from core.logger import get_logger
from server.app import JessycaMCPServer, create_mcp_server
from server.health import HealthCheckResult

logger = get_logger("jessyca.server.runtime")


class MCPDemoRuntime:
    """Administrador de ciclo de vida del servidor MCP para modo DEMO de JESSYCA."""

    def __init__(
        self,
        server: JessycaMCPServer | None = None,
        host: str | None = None,
        port: int | None = None,
        transport: str | None = None,
    ) -> None:
        from config.manager import get_settings

        settings = get_settings()
        self.host = host or getattr(settings, "MCP_SERVER_HOST", "127.0.0.1")
        self.port = port or getattr(settings, "MCP_SERVER_PORT", 8000)
        self.transport = (
            transport
            or getattr(settings, "MCP_DEMO_TRANSPORT", "streamable-http")
        )

        self._server = server or create_mcp_server()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._started = False

    @property
    def server(self) -> JessycaMCPServer:
        """Instancia del servidor MCP subyacente."""
        return self._server

    @property
    def is_running(self) -> bool:
        """Determina si el servidor MCP está actualmente en ejecución."""
        with self._lock:
            if not self._started or self._thread is None:
                return False
            return self._thread.is_alive() and self._server.is_running

    def start(self, timeout_sec: float = 3.0) -> bool:
        """Inicia el servidor MCP en un hilo en segundo plano (non-blocking).

        Args:
            timeout_sec: Tiempo máximo en segundos para esperar la confirmación de arranque.

        Returns:
            True si el servidor inició exitosamente.
        """
        with self._lock:
            if self._started and self._thread is not None and self._thread.is_alive():
                logger.info(f"[MCP RUNTIME] Servidor MCP ya se encuentra corriendo en {self.host}:{self.port}")
                return True

            logger.info(
                f"[DEMO] Iniciando servidor MCP en background ({self.host}:{self.port}, transporte: {self.transport})..."
            )

            def _run_server() -> None:
                try:
                    self._server.run(
                        transport=self.transport,
                        show_banner=False,
                    )
                except Exception as e:
                    logger.warning(f"[MCP RUNTIME] Excepción en runtime de FastMCP: {e}")

            self._thread = threading.Thread(
                target=_run_server,
                name="Jessyca-MCPDemoRuntime-Worker",
                daemon=True,
            )
            self._thread.start()
            self._started = True

        # Esperar hasta que esté en estado RUNNING o timeout
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            if self._server.is_running:
                logger.info(f"[DEMO] MCP iniciado exitosamente en {self.host}:{self.port}")
                return True
            time.sleep(0.05)

        logger.info(f"[DEMO] MCP Worker iniciado en segundo plano ({self.host}:{self.port})")
        return True

    def stop(self, timeout_sec: float = 2.0) -> None:
        """Detiene limpiamente el servidor MCP y su hilo en segundo plano."""
        with self._lock:
            if not self._started:
                return

            logger.info("[DEMO] Deteniendo servidor MCP...")
            try:
                self._server.shutdown()
            except Exception as e:
                logger.warning(f"[MCP RUNTIME] Error al apagar servidor MCP: {e}")

            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=timeout_sec)
                self._thread = None

            self._started = False
            logger.info("[DEMO] Servidor MCP detenido limpiamente.")

    def health(self) -> HealthCheckResult:
        """Consulta el estado de salud del servidor MCP."""
        return self._server.check_health()

    def to_dict(self) -> dict[str, Any]:
        """Representación estructurada del estado del runtime MCP."""
        return {
            "host": self.host,
            "port": self.port,
            "transport": self.transport,
            "is_running": self.is_running,
            "server_name": self._server.server_name,
            "version": self._server.version,
        }


# Instancia singleton para la sesión
_global_demo_runtime: MCPDemoRuntime | None = None


def get_mcp_demo_runtime() -> MCPDemoRuntime:
    """Obtiene la instancia singleton del MCPDemoRuntime."""
    global _global_demo_runtime
    if _global_demo_runtime is None:
        _global_demo_runtime = MCPDemoRuntime()
    return _global_demo_runtime


__all__ = [
    "MCPDemoRuntime",
    "get_mcp_demo_runtime",
]
