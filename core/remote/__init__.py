"""Módulo de conexión y gobernanza remota de JESSYCA (Fase 6)."""

from core.remote.auth import OwnerAuthManager
from core.remote.models import (
    ALLOWED_REMOTE_APPS,
    FORBIDDEN_COMMAND_PATTERNS,
    RemoteCommandType,
    RemoteExecutionResult,
    RemoteExecutionStatus,
    RemoteMessage,
)
from core.remote.task_router import RemoteTaskRouter
from core.remote.tunnel_protocol import PacketType, TunnelPacket, TunnelProtocol
from core.remote.wol_controller import WakeOnLanController

__all__ = [
    "OwnerAuthManager",
    "ALLOWED_REMOTE_APPS",
    "FORBIDDEN_COMMAND_PATTERNS",
    "RemoteCommandType",
    "RemoteExecutionResult",
    "RemoteExecutionStatus",
    "RemoteMessage",
    "RemoteTaskRouter",
    "PacketType",
    "TunnelPacket",
    "TunnelProtocol",
    "WakeOnLanController",
]
