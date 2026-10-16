"""Modelos formales para el canal remoto de WhatsApp Personal y Wake-on-LAN (Fase 6).

Define tipos de comandos autorizados, listas blancas estrictas, estructuras de
mensajes cifrados/firmados, y estados de ejecución auditados.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class RemoteCommandType(StrEnum):
    """Acciones autorizadas para solicitud remota vía WhatsApp Personal."""

    PING_STATUS = "ping_status"
    WAKE_ON_LAN = "wake_on_lan"
    JESSYCA_STATUS = "jessyca_status"
    RESEARCH_TASK = "research_task"
    TASK_RESULTS = "task_results"
    CANCEL_TASK = "cancel_task"
    OPEN_APP = "open_app"


# Lista blanca inmutable de aplicaciones permitidas para apertura remota
ALLOWED_REMOTE_APPS: frozenset[str] = frozenset(
    {
        "chrome",
        "google chrome",
        "notepad",
        "bloc de notas",
        "calc",
        "calculator",
        "calculadora",
    }
)

# Patrones terminantemente prohibidos vía WhatsApp (cero consola remota, cero scripts)
FORBIDDEN_COMMAND_PATTERNS: frozenset[str] = frozenset(
    {
        "cmd",
        "powershell",
        "pwsh",
        "bash",
        "sh",
        "reg",
        "regedit",
        "format",
        "del",
        "rmdir",
        "remove-item",
        "net user",
        "net localgroup",
        "curl",
        "wget",
        "certutil",
        "vbs",
        "wscript",
        "cscript",
        "install",
        "msiexec",
        "pip install",
        "apt",
        "shutdown /s",
        "drop",
        "dump",
        "mimikatz",
    }
)


class RemoteExecutionStatus(StrEnum):
    """Taxonomía de estados del ciclo de ejecución remota."""

    PENDING = "pending"
    RECEIVED = "received"
    AUTHENTICATED = "authenticated"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED_UNAUTHORIZED = "rejected_unauthorized"
    REJECTED_FORBIDDEN = "rejected_forbidden"
    REJECTED_RATE_LIMIT = "rejected_rate_limit"
    REJECTED_REPLAY = "rejected_replay"
    BLOCKED_OFFLINE = "blocked_offline"
    LOCKED_STATION = "locked_station"


@dataclass
class RemoteMessage:
    """Mensaje entrante o saliente del protocolo de comunicación remota cifrada."""

    message_id: str
    sender_phone_jid: str
    device_id: str
    command_type: RemoteCommandType | str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    nonce: str = ""
    signature: str = ""
    is_confirmed: bool = False
    confirmation_code: str | None = None

    def canonical_bytes_for_signing(self) -> bytes:
        """Serialización canónica y determinista para firma HMAC."""
        canonical_dict = {
            "message_id": self.message_id,
            "sender_phone_jid": self.sender_phone_jid,
            "device_id": self.device_id,
            "command_type": str(self.command_type),
            "payload": self.payload,
            "timestamp": round(self.timestamp, 3),
            "nonce": self.nonce,
            "is_confirmed": self.is_confirmed,
        }
        raw_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
        return raw_json.encode("utf-8")


@dataclass
class RemoteExecutionResult:
    """Resultado formal y verificable de la ejecución de una acción remota."""

    command_id: str
    command_type: RemoteCommandType | str
    status: RemoteExecutionStatus
    success: bool
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    confirmation_prompt: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado a un diccionario estructurado."""
        return asdict(self)
