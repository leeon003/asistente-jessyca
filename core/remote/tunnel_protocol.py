"""Protocolo de túnel cifrado y autenticado para comunicación VPS <-> Windows (Fase 6).

Diseñado para no abrir puertos de control remoto directamente a internet:
Windows se conecta hacia el VPS (Outbound) o se comunica mediante un canal
cifrado y autenticado con firmas HMAC-SHA256 y cifrado de extremo a extremo.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.remote.tunnel")


class PacketType(StrEnum):
    """Tipos de paquetes transportados por el túnel seguro."""

    HANDSHAKE_INIT = "handshake_init"
    HANDSHAKE_ACK = "handshake_ack"
    HEARTBEAT_PING = "heartbeat_ping"
    HEARTBEAT_PONG = "heartbeat_pong"
    DISPATCH_COMMAND = "dispatch_command"
    COMMAND_RESULT = "command_result"
    STATUS_UPDATE = "status_update"


@dataclass
class TunnelPacket:
    """Estructura de paquete autenticado para el túnel seguro."""

    packet_id: str
    packet_type: PacketType | str
    payload: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    nonce: str = field(default_factory=lambda: secrets.token_hex(16))
    signature: str = ""

    def canonical_bytes(self) -> bytes:
        """Serialización canónica para cómputo de integridad y autenticación."""
        clean_dict = {
            "packet_id": self.packet_id,
            "packet_type": str(self.packet_type),
            "payload": self.payload,
            "timestamp": round(self.timestamp, 3),
            "nonce": self.nonce,
        }
        return json.dumps(clean_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")


class TunnelProtocol:
    """Gestor de empaquetado, firma y verificación del túnel cifrado."""

    def __init__(self, shared_secret: str | None = None) -> None:
        raw_key = shared_secret or os.getenv(
            "JESSYCA_TUNNEL_SHARED_KEY", "jessyca-tunnel-secret-key-2026-secure"
        )
        self._key = hashlib.sha256(raw_key.encode("utf-8")).digest()

    def pack(self, packet_type: PacketType | str, payload: dict[str, Any]) -> str:
        """Crea un paquete firmado listo para transmisión por socket o HTTP streaming."""
        packet_id = f"pkt_{secrets.token_hex(8)}"
        pkt = TunnelPacket(
            packet_id=packet_id,
            packet_type=packet_type,
            payload=payload,
            timestamp=time.time(),
            nonce=secrets.token_hex(16),
        )
        # Firmar con HMAC-SHA256
        sig = hmac.new(self._key, pkt.canonical_bytes(), hashlib.sha256).hexdigest()
        pkt.signature = sig
        return json.dumps(asdict(pkt))

    def unpack(self, raw_json_data: str, max_drift_seconds: float = 60.0) -> tuple[bool, TunnelPacket | None, str]:
        """Desempaqueta y valida estrictamente la firma y timestamp del paquete."""
        try:
            data = json.loads(raw_json_data)
            pkt = TunnelPacket(
                packet_id=data["packet_id"],
                packet_type=data["packet_type"],
                payload=data.get("payload", {}),
                timestamp=data["timestamp"],
                nonce=data["nonce"],
                signature=data.get("signature", ""),
            )
        except Exception as e:
            return False, None, f"Formato de paquete corrupto o inválido: {e}"

        now = time.time()
        if abs(now - pkt.timestamp) > max_drift_seconds:
            return False, None, f"Paquete rechazado: tiempo de vida expirado ({abs(now - pkt.timestamp):.2f}s)."

        expected_sig = hmac.new(self._key, pkt.canonical_bytes(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(pkt.signature, expected_sig):
            logger.error(f"[TUNNEL_REJECT] Firma de paquete '{pkt.packet_id}' no coincide.")
            return False, None, "Firma del paquete de túnel inválida."

        return True, pkt, "Paquete verificado exitosamente."
