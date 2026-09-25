"""Paquete JESSYCA Web Bridge (OpenAI-Compatible Bridge).

Adaptador HTTP compatible con la API de OpenAI para interacción con Open WebUI.
"""

from __future__ import annotations

from interfaces.webui_bridge.adapter import PUBLIC_MODEL_NAME
from interfaces.webui_bridge.app import create_webui_bridge_app
from interfaces.webui_bridge.server import run_webui_server

__all__ = [
    "PUBLIC_MODEL_NAME",
    "create_webui_bridge_app",
    "run_webui_server",
]
