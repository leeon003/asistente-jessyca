"""Servidor FastAPI y canal WebSocket para JESSYCA ORB — Núcleo Aurora.

Proporciona:
1. Servido de activos estáticos 3D (Three.js, shaders, CSS, HTML).
2. Canal WebSocket bidireccional (/ws/aurora) para sincronización de estados y telemetría de audio.
3. API REST (/api/state, /api/themes, /api/health) desacoplada del cerebro cognitivo.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from interfaces.aurora.audio_adapter import AuroraAudioAdapter
from interfaces.aurora.visual_states import (
    AURORA_THEMES,
    AuroraVisualState,
    SessionStateToAuroraAdapter,
)

logger = logging.getLogger("jessyca.aurora.server")
STATIC_DIR = Path(__file__).resolve().parent / "static"


class AuroraServerManager:
    """Gestor del servidor local y orquestador de clientes WebSocket."""

    def __init__(self, port: int = 8765) -> None:
        self.requested_port = port
        self.actual_port = self._find_available_port(port)
        self.app = FastAPI(title="JESSYCA ORB — Núcleo Aurora 3D API")
        self.active_websockets: set[WebSocket] = set()
        self.current_state: AuroraVisualState = AuroraVisualState.IDLE
        self.audio_adapter = AuroraAudioAdapter()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._setup_routes()

    @staticmethod
    def _find_available_port(start_port: int) -> int:
        """Encuentra un puerto TCP disponible a partir del solicitado."""
        for p in range(start_port, start_port + 50):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", p)) != 0:
                    return p
        return start_port

    def _setup_routes(self) -> None:
        # Habilitar CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Montar archivos estáticos
        if STATIC_DIR.exists():
            self.app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @self.app.get("/")
        async def get_index() -> FileResponse:
            index_path = STATIC_DIR / "index.html"
            return FileResponse(str(index_path))

        @self.app.get("/api/health")
        async def health() -> dict[str, Any]:
            return {
                "status": "HEALTHY",
                "component": "JESSYCA_ORB_AURORA_3D",
                "active_state": self.current_state.value,
                "clients_connected": len(self.active_websockets),
                "port": self.actual_port,
            }

        @self.app.get("/api/themes")
        async def get_themes() -> dict[str, Any]:
            result: dict[str, Any] = {}
            for state, theme in AURORA_THEMES.items():
                result[state.value] = {
                    "primary_color": theme.primary_color,
                    "secondary_color": theme.secondary_color,
                    "accent_color": theme.accent_color,
                    "core_pulse_speed": theme.core_pulse_speed,
                    "noise_displacement": theme.noise_displacement,
                    "orbital_speed": theme.orbital_speed,
                    "particle_activity": theme.particle_activity,
                    "glow_intensity": theme.glow_intensity,
                    "description": theme.description,
                }
            return result

        @self.app.on_event("startup")
        async def on_startup() -> None:
            self.loop = asyncio.get_running_loop()
            logger.info("[AURORA SERVER] Event loop registrado para broadcasting seguro.")

        @self.app.post("/api/accent")
        async def trigger_accent_endpoint(payload: dict[str, Any] | None = None) -> dict[str, Any]:
            boost = float(payload.get("boost", 1.0)) if payload else 1.0
            color = payload.get("color") if payload else None
            await self.broadcast_accent(boost, color)
            return {"success": True, "boost": boost}

        @self.app.post("/api/state")
        async def set_state_endpoint(payload: dict[str, str]) -> dict[str, Any]:
            state_str = payload.get("state", "IDLE").upper()
            try:
                target_state = AuroraVisualState(state_str)
            except ValueError:
                # Intento de conversión desde SessionState granular
                target_state = SessionStateToAuroraAdapter.to_granular_visual_state(state_str)

            await self.broadcast_state(target_state)
            return {"success": True, "new_state": target_state.value}

        @self.app.post("/api/audio_metrics")
        async def set_audio_metrics_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
            await self.broadcast_audio_metrics(payload)
            return {"success": True}

        @self.app.websocket("/ws/aurora")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            await websocket.accept()
            self.active_websockets.add(websocket)
            logger.info(f"[AURORA WS] Cliente conectado. Total: {len(self.active_websockets)}")

            # Enviar estado inicial
            await websocket.send_json({
                "type": "state_update",
                "state": self.current_state.value,
            })

            try:
                while True:
                    data = await websocket.receive_text()
                    try:
                        msg = json.loads(data)
                        msg_type = msg.get("type")
                        if msg_type == "state_change":
                            raw_state = msg.get("state", "IDLE")
                            try:
                                self.current_state = AuroraVisualState(raw_state)
                            except ValueError:
                                pass
                            # Retransmitir a otros clientes
                            await self._broadcast_raw({
                                "type": "state_update",
                                "state": self.current_state.value,
                            }, exclude=websocket)
                        elif msg_type in ("audio_metrics", "audio_level"):
                            # Retransmitir métricas de audio entrantes
                            await self._broadcast_raw(msg, exclude=websocket)
                        elif msg_type == "accent_trigger":
                            await self._broadcast_raw(msg, exclude=websocket)
                    except json.JSONDecodeError:
                        pass
            except WebSocketDisconnect:
                self.active_websockets.discard(websocket)
                logger.info(f"[AURORA WS] Cliente desconectado. Restantes: {len(self.active_websockets)}")

    async def broadcast_state(self, state: AuroraVisualState) -> None:
        """Difunde un nuevo estado visual a todos los visualizadores conectados."""
        self.current_state = state
        await self._broadcast_raw({
            "type": "state_update",
            "state": state.value,
        })

    async def broadcast_audio_metrics(self, metrics_dict: dict[str, Any]) -> None:
        """Difunde métricas de modulación de audio a los shaders."""
        await self._broadcast_raw({
            "type": "audio_metrics",
            **metrics_dict,
        })

    async def broadcast_accent(self, boost: float = 1.0, color: str | None = None) -> None:
        """Difunde un pulso de onda de choque de acción/acento."""
        await self._broadcast_raw({
            "type": "accent_trigger",
            "boost": boost,
            "color": color,
        })

    def broadcast_state_sync(self, state: AuroraVisualState | str) -> None:
        """Difusión no bloqueante y thread-safe de estado desde hilos de trabajo sincrónicos."""
        try:
            target = state if isinstance(state, AuroraVisualState) else AuroraVisualState(str(state).upper())
        except ValueError:
            target = SessionStateToAuroraAdapter.to_granular_visual_state(str(state))
        self.current_state = target
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast_state(target), self.loop)

    def broadcast_audio_metrics_sync(self, metrics_dict: dict[str, Any]) -> None:
        """Difusión no bloqueante y thread-safe de métricas de audio."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast_audio_metrics(metrics_dict), self.loop)

    def broadcast_accent_sync(self, boost: float = 1.0, color: str | None = None) -> None:
        """Difusión no bloqueante y thread-safe de pulso de acento."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast_accent(boost, color), self.loop)

    async def _broadcast_raw(self, payload: dict[str, Any], exclude: WebSocket | None = None) -> None:
        disconnected = set()
        for ws in self.active_websockets:
            if ws is exclude:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                disconnected.add(ws)
        self.active_websockets.difference_update(disconnected)
