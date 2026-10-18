"""Lanzador Oficial y CLI del Prototipo Independiente JESSYCA ORB — Núcleo Aurora 3D.

Ejecutar con:
    python -m interfaces.aurora.launcher
    python -m interfaces.aurora.launcher --port 8765 --simulate-audio
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import threading
import time
from typing import Any

import uvicorn

from interfaces.aurora.audio_adapter import AuroraAudioAdapter
from interfaces.aurora.server import AuroraServerManager
from interfaces.aurora.visual_states import AuroraVisualState
from interfaces.aurora.window_manager import AuroraWindowManager

# Asegurar UTF-8 en Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class AuroraPrototypeRunner:
    """Ejecutor principal del prototipo independiente de Núcleo Aurora."""

    def __init__(
        self,
        port: int = 8765,
        headless: bool = False,
        simulate_audio: bool = True,
    ) -> None:
        self.port = port
        self.headless = headless
        self.simulate_audio = simulate_audio
        self.server_manager = AuroraServerManager(port=self.port)
        self.actual_port = self.server_manager.actual_port
        self.window_manager = AuroraWindowManager(port=self.actual_port)
        self.audio_adapter = AuroraAudioAdapter()
        self._stop_event = threading.Event()
        self._server_thread: threading.Thread | None = None
        self._audio_sim_thread: threading.Thread | None = None

    def _run_server(self) -> None:
        config = uvicorn.Config(
            app=self.server_manager.app,
            host="127.0.0.1",
            port=self.actual_port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server.run()

    def _audio_simulation_loop(self) -> None:
        """Genera fluctuaciones suaves de energía acústica para demostrar la reactividad de los shaders."""
        t_start = time.time()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while not self._stop_event.is_set():
            elapsed = time.time() - t_start
            state = self.server_manager.current_state

            metrics = self.audio_adapter.generate_simulated_metrics(state, elapsed)
            # Enviar al WebSocket
            try:
                loop.run_until_complete(
                    self.server_manager.broadcast_audio_metrics(metrics.to_dict())
                )
            except Exception:
                pass
            time.sleep(0.04)  # ~25 Hz de actualización de audio

    def start(self) -> None:
        banner = r"""
╔═══════════════════════════════════════════════════════════════════════╗
║             J E S S Y C A   O R B  —  N Ú C L E O   A U R O R A       ║
║                     PROTOTIPO 3D INDEPENDIENTE                        ║
║                                                                       ║
║  ✓ WebGL 2.0 Hardware Accelerated    ✓ Shaders GLSL de Deformación    ║
║  ✓ Membrana Holográfica Fresnel      ✓ 3 Anillos Orbitales 3D         ║
║  ✓ Enjambre de Partículas Dinámico   ✓ Panel de Estados Simulado      ║
╚═══════════════════════════════════════════════════════════════════════╝
"""
        print(banner)
        print(f"  [+] Servidor local activo en: http://127.0.0.1:{self.actual_port}")
        print(f"  [+] Modo simulación de audio: {'ACTIVO' if self.simulate_audio else 'INACTIVO'}")

        # 1. Iniciar servidor en hilo daemon
        self._server_thread = threading.Thread(target=self._run_server, daemon=True)
        self._server_thread.start()
        time.sleep(0.8)

        # 2. Iniciar simulación de audio si procede
        if self.simulate_audio:
            self._audio_sim_thread = threading.Thread(target=self._audio_simulation_loop, daemon=True)
            self._audio_sim_thread.start()

        # 3. Lanzar ventana nativa si no es headless
        if not self.headless:
            print("  [+] Abriendo ventana de escritorio Windows 11...")
            self.window_manager.launch()
        else:
            print("  [+] Modo Headless activo. Accede mediante navegador a la URL anterior.")

        print("\n  >> Presiona Ctrl+C en cualquier momento para detener el prototipo.\n")

    def stop(self) -> None:
        print("\n  [!] Deteniendo Núcleo Aurora y liberando recursos...")
        self._stop_event.set()
        self.window_manager.close()
        print("  [✓] Prototipo detenido limpiamente.")


def main() -> None:
    parser = argparse.ArgumentParser(description="JESSYCA ORB — Núcleo Aurora 3D Launcher")
    parser.add_argument("--port", type=int, default=8765, help="Puerto del servidor (default: 8765)")
    parser.add_argument("--headless", action="store_true", help="Iniciar solo el servidor sin abrir ventana")
    parser.add_argument("--no-audio-sim", action="store_true", help="Desactivar la modulación sintética de audio")
    args = parser.parse_args()

    runner = AuroraPrototypeRunner(
        port=args.port,
        headless=args.headless,
        simulate_audio=not args.no_audio_sim,
    )

    def sig_handler(sig: Any, frame: Any) -> None:
        runner.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    runner.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        runner.stop()


if __name__ == "__main__":
    main()
