"""Gateway de WhatsApp Personal y Enrutador Remoto (Fase 6).

Módulo soberano para la interacción remota entre el propietario y JESSYCA.
Aislado estrictamente de CRM, tiendas y bots comerciales.
Gestiona autenticación biométrica/dispositivo, anti-replay, rate limiting,
reactivación WOL y despacho gobernado hacia Windows.
"""

from __future__ import annotations

import re
import secrets
import time
from typing import Any

from core.logger import get_logger
from core.remote.auth import OwnerAuthManager
from core.remote.models import (
    RemoteCommandType,
    RemoteExecutionResult,
    RemoteExecutionStatus,
    RemoteMessage,
)
from core.remote.task_router import RemoteTaskRouter
from core.remote.wol_controller import WakeOnLanController

logger = get_logger("jessyca.interfaces.whatsapp_personal")


class WhatsAppPersonalGateway:
    """Gateway de mensajes de WhatsApp Personal para el propietario."""

    def __init__(
        self,
        auth_manager: OwnerAuthManager | None = None,
        task_router: RemoteTaskRouter | None = None,
        wol_controller: WakeOnLanController | None = None,
        is_pc_online_override: bool | None = None,
    ) -> None:
        self.auth = auth_manager or OwnerAuthManager()
        self.router = task_router or RemoteTaskRouter()
        self.wol = wol_controller or WakeOnLanController()
        self._is_pc_online_override = is_pc_online_override

    def is_pc_online(self) -> bool:
        """Comprueba si la PC Windows está activa y alcanzable."""
        if self._is_pc_online_override is not None:
            return self._is_pc_online_override
        return self.wol.verify_pc_awake()

    def set_pc_online_override(self, online: bool | None) -> None:
        """Permite simular o fijar el estado de conexión de la PC para pruebas."""
        self._is_pc_online_override = online

    def process_inbound_whatsapp(
        self,
        sender_phone_jid: str,
        device_id: str,
        text: str,
        nonce: str | None = None,
        timestamp: float | None = None,
        signature: str | None = None,
    ) -> str:
        """Punto de entrada único para mensajes entrantes de WhatsApp."""
        msg_nonce = nonce or secrets.token_hex(16)
        msg_timestamp = timestamp if timestamp is not None else time.time()

        # 1. Autenticación de Remitente y Dispositivo
        valid_sender, reason = self.auth.verify_sender(sender_phone_jid, device_id)
        if not valid_sender:
            return f"⛔ Acceso denegado: {reason}"

        # 2. Control de Tasa (Rate Limiting)
        valid_rate, rate_msg = self.auth.check_rate_limit(sender_phone_jid)
        if not valid_rate:
            return f"⚠️ {rate_msg}"

        # 3. Protección contra Ataques de Repetición (Anti-Replay)
        valid_replay, replay_msg = self.auth.verify_anti_replay(msg_nonce, msg_timestamp)
        if not valid_replay:
            return f"⛔ Solicitud inválida: {replay_msg}"

        # 4. Verificación de confirmación pendiente (si el mensaje es "CONFIRMAR <code>")
        confirm_match = re.match(r"^confirmar\s+(\d{6})$", text.strip(), re.IGNORECASE)
        if confirm_match:
            code = confirm_match.group(1)
            # Buscar desafío
            found_cmd_id = None
            for cmd_id in list(self.auth._pending_challenges.keys()):
                found_cmd_id = cmd_id
                break

            if found_cmd_id:
                valid_code, c_msg = self.auth.verify_confirmation_challenge(found_cmd_id, code)
                if valid_code:
                    return f"✅ Operación confirmada. Procediendo con la ejecución segura."
                return f"❌ {c_msg}"
            return "No hay ninguna operación sensible esperando confirmación actualmente."

        # 5. Interpretar intención y estructurar RemoteMessage
        cmd_type, payload = self._classify_whatsapp_text(text)

        msg = RemoteMessage(
            message_id=f"wa_{secrets.token_hex(8)}",
            sender_phone_jid=sender_phone_jid,
            device_id=device_id,
            command_type=cmd_type,
            payload=payload,
            timestamp=msg_timestamp,
            nonce=msg_nonce,
        )

        # 6. Verificación de firma criptográfica si se proveyó
        if signature:
            msg.signature = signature
            valid_sig, sig_msg = self.auth.verify_signature(msg)
            if not valid_sig:
                return f"⛔ Error de integridad: {sig_msg}"

        # 7. Despacho especial para Wake-on-LAN
        if cmd_type == RemoteCommandType.WAKE_ON_LAN:
            return self._handle_wol_request(msg)

        # 8. Verificación de conectividad de la PC
        if not self.is_pc_online():
            return (
                "🔌 Tu PC se encuentra apagada o suspendida (Offline).\n"
                "JESSYCA no puede ejecutar esta tarea en este momento.\n\n"
                "👉 Si deseas encenderla de forma remota, responde: *Despierta la PC*"
            )

        # 9. Enrutamiento y ejecución supervisada en Windows
        result = self.router.route_command(msg)
        return result.message

    def _classify_whatsapp_text(self, text: str) -> tuple[RemoteCommandType | str, dict[str, Any]]:
        """Interpreta la intención en lenguaje natural para WhatsApp personal."""
        clean = text.strip().lower()

        # Wake-on-LAN
        if any(w in clean for w in ("despierta", "despertar", "prende", "encender", "wake on lan", "wol")):
            return RemoteCommandType.WAKE_ON_LAN, {"raw": text}

        # Ping / Disponibilidad
        if any(w in clean for w in ("estás ahí", "estas ahi", "ping", "hola", "disponible", "pc encendida")):
            return RemoteCommandType.PING_STATUS, {}

        # Estado de JESSYCA
        if any(w in clean for w in ("estado", "recursos", "ram", "vram", "gpu", "cpu", "cómo estás")):
            return RemoteCommandType.JESSYCA_STATUS, {}

        # Cancelar / Detener
        if any(w in clean for w in ("detente", "cancela", "cancelar", "para todo", "parada de emergencia", "stop")):
            return RemoteCommandType.CANCEL_TASK, {}

        # Apertura de Apps
        app_match = re.search(r"(?:abre|abrir|lanzar)\s+(?:el|la|los|las)?\s*([a-zA-Z0-9_\s]+)", clean)
        if app_match:
            app_name = app_match.group(1).strip()
            return RemoteCommandType.OPEN_APP, {"app_name": app_name}

        # Investigación
        research_match = re.search(r"(?:investiga|investigar|busca|averigua)\s+(.+)", clean)
        if research_match:
            query = research_match.group(1).strip()
            return RemoteCommandType.RESEARCH_TASK, {"query": query}

        # Tareas recientes
        if any(w in clean for w in ("tareas", "qué hiciste", "que hiciste", "resultados")):
            return RemoteCommandType.TASK_RESULTS, {}

        # Por defecto, consulta general
        return RemoteCommandType.RESEARCH_TASK, {"query": text}

    def _handle_wol_request(self, message: RemoteMessage) -> str:
        """Gestiona la reactivación por Wake-on-LAN con confirmación honesta."""
        if self.is_pc_online():
            return "Tu PC ya se encuentra encendida y JESSYCA está lista para recibir órdenes."

        # Transmisión del paquete
        sent, send_msg = self.wol.send_magic_packet()
        if not sent:
            return f"❌ No se pudo enviar el paquete de reactivación: {send_msg}"

        return (
            "📡 He transmitido el paquete de reactivación (Wake-on-LAN) hacia tu red doméstica.\n"
            "Esperando confirmación real de que tu PC ha respondido...\n"
            "_(Te notificaré tan pronto como el agente establezca el canal cifrado)_"
        )
