"""Controlador de Wake-on-LAN (WOL) seguro para reactivación de PC (Fase 6).

Genera paquetes mágicos estándar (Sync 6x 0xFF + 16x MAC), despacha por socket UDP
con broadcast hacia la red doméstica autorizada, y realiza verificación determinista
del estado en línea de Windows sin emitir falsos éxitos.
"""

from __future__ import annotations

import re
import socket
import time
from typing import Callable

from core.logger import get_logger

logger = get_logger("jessyca.remote.wol")

DEFAULT_TARGET_MAC = "04-7C-16-6E-B4-70"
DEFAULT_BROADCAST_IP = "192.168.1.255"
DEFAULT_WOL_PORT = 9


class WakeOnLanController:
    """Controlador soberano para la construcción, envío y verificación de Wake-on-LAN."""

    def __init__(
        self,
        target_mac: str = DEFAULT_TARGET_MAC,
        broadcast_ip: str = DEFAULT_BROADCAST_IP,
        wol_port: int = DEFAULT_WOL_PORT,
        agent_host: str = "127.0.0.1",
        agent_port: int = 8088,
    ) -> None:
        self.target_mac = target_mac
        self.broadcast_ip = broadcast_ip
        self.wol_port = wol_port
        self.agent_host = agent_host
        self.agent_port = agent_port

    @staticmethod
    def format_mac_bytes(mac: str) -> bytes:
        """Limpia y convierte la dirección MAC en una secuencia de 6 bytes."""
        clean_mac = re.sub(r"[^0-9a-fA-F]", "", mac)
        if len(clean_mac) != 12:
            raise ValueError(f"Dirección MAC inválida: '{mac}' (debe contener 12 dígitos hexadecimales).")
        return bytes.fromhex(clean_mac)

    @classmethod
    def create_magic_packet(cls, mac: str) -> bytes:
        """Construye el Magic Packet estándar (6 bytes 0xFF + 16 repeticiones de la MAC = 102 bytes)."""
        mac_bytes = cls.format_mac_bytes(mac)
        sync_stream = b"\xff" * 6
        payload = sync_stream + (mac_bytes * 16)
        if len(payload) != 102:
            raise ValueError("Error interno al ensamblar la longitud del Magic Packet.")
        return payload

    def send_magic_packet(
        self,
        mac: str | None = None,
        broadcast_ip: str | None = None,
        port: int | None = None,
    ) -> tuple[bool, str]:
        """Envía el Magic Packet vía UDP broadcast con socket de red."""
        target_mac = mac or self.target_mac
        target_ip = broadcast_ip or self.broadcast_ip
        target_port = port or self.wol_port

        try:
            packet = self.create_magic_packet(target_mac)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.settimeout(3.0)
                sock.sendto(packet, (target_ip, target_port))

            logger.info(
                f"[WOL_SENT] Magic Packet transmitido a {target_ip}:{target_port} para MAC={target_mac}"
            )
            return True, f"Magic Packet transmitido hacia {target_mac} vía {target_ip}:{target_port}."
        except Exception as e:
            logger.error(f"[WOL_ERROR] Fallo al enviar Magic Packet: {e}")
            return False, f"Fallo al transmitir Magic Packet: {e}"

    def verify_pc_awake(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float = 2.0,
    ) -> bool:
        """Verifica físicamente si el agente de la PC está escuchando en red (cero falsos positivos)."""
        target_host = host or self.agent_host
        target_port = port or self.agent_port

        try:
            with socket.create_connection((target_host, target_port), timeout=timeout):
                logger.info(f"[WOL_VERIFIED] Conexión TCP exitosa a {target_host}:{target_port}")
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def trigger_wake_and_poll(
        self,
        max_wait_seconds: float = 15.0,
        poll_interval: float = 2.0,
        probe_fn: Callable[[], bool] | None = None,
    ) -> tuple[bool, str]:
        """Dispara el Magic Packet y sondea periódicamente hasta confirmar que la PC respondió."""
        sent, msg = self.send_magic_packet()
        if not sent:
            return False, msg

        check_probe = probe_fn or self.verify_pc_awake
        start_time = time.time()

        while time.time() - start_time < max_wait_seconds:
            time.sleep(poll_interval)
            if check_probe():
                return True, "La PC se ha reactivado y JESSYCA se encuentra en línea."

        logger.warning("[WOL_TIMEOUT] Se envió el Magic Packet pero la PC no respondió a tiempo.")
        return False, (
            "Se envió la solicitud de reactivación a la red doméstica, pero la PC aún no responde. "
            "Verifica que el equipo esté en suspensión (S3) o hibernación (S4), o si requiere encendido manual."
        )
