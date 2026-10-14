"""Conectores externos para JESSYCA (interfaces/external_connectors.py).

Prepara la integración de Jessyca con:
1. Open WebUI (vía /v1/chat/completions ya activo)
2. Chat de Tiendas Ramy (/api/v1/channels/ramy-chat)
3. CRM y Gestión de Leads (/api/v1/channels/crm)
4. WhatsApp VPS Gateway (/api/v1/channels/whatsapp)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest, JessycaResponse
from core.logger import get_logger

logger = get_logger("jessyca.interfaces.external_connectors")


class ExternalChannel(StrEnum):
    """Canales de mensajería externa integrables."""

    OPEN_WEBUI = "open_webui"
    WHATSAPP_VPS = "whatsapp_vps"
    TIENDAS_RAMY = "tiendas_ramy"
    CRM_LEADS = "crm_leads"


@dataclass
class InboundMessage:
    """Mensaje entrante desde una plataforma externa."""

    channel: ExternalChannel | str
    sender_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class OutboundMessage:
    """Respuesta formateada para la plataforma externa."""

    channel: ExternalChannel | str
    recipient_id: str
    text: str
    success: bool
    session_id: str
    intent: str
    requires_confirmation: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class ExternalConnectorBridge:
    """Puente unificado entre plataformas externas y el Agente Local Jessyca."""

    def __init__(self, agent: JessycaLocalAgent | None = None) -> None:
        self.agent = agent or JessycaLocalAgent.get_instance()

    def handle_inbound_message(self, message: InboundMessage) -> OutboundMessage:
        """Enruta un mensaje externo a través de la tubería unificada de Jessyca."""
        channel_name = str(message.channel.value if isinstance(message.channel, ExternalChannel) else message.channel)
        
        # Generar identificador canónico de sesión por canal
        session_id = f"{channel_name}_{message.sender_id}".replace("+", "").replace(" ", "_")

        meta = {
            "channel": channel_name,
            "sender_id": message.sender_id,
            **message.metadata,
        }

        req = JessycaRequest(
            user_input=message.text,
            session_id=session_id,
            metadata=meta,
        )

        logger.info(f"[EXTERNAL_INBOUND] Canal: '{channel_name}', Remitente: '{message.sender_id}', Texto: '{message.text[:60]}...'")

        resp: JessycaResponse = self.agent.interact(req)

        # Formatear según canal
        out_text = self._format_response_for_channel(channel_name, resp.response_text)

        outbound = OutboundMessage(
            channel=channel_name,
            recipient_id=message.sender_id,
            text=out_text,
            success=resp.success,
            session_id=session_id,
            intent=resp.intent,
            requires_confirmation=resp.requires_confirmation,
            metadata={
                "tools_executed": list(resp.tools_executed),
                "security_verdict": resp.security_verdict,
                "latency_ms": resp.metrics.total_latency_ms if resp.metrics else 0.0,
            },
        )

        logger.info(f"[EXTERNAL_OUTBOUND] Canal: '{channel_name}', Éxito: {resp.success}, Intención: '{resp.intent}'")
        return outbound

    def _format_response_for_channel(self, channel: str, text: str) -> str:
        """Adapta el formato del texto según las convenciones del canal."""
        if not text:
            return "No se obtuvo respuesta."

        clean = text.strip()

        if channel == ExternalChannel.WHATSAPP_VPS:
            # WhatsApp no interpreta markdown tables ni diffs complejos; usar formato amigable
            clean = clean.replace("```json", "*Datos:*").replace("```", "")
            return clean

        if channel == ExternalChannel.TIENDAS_RAMY:
            # Tono comercial y de servicio al cliente
            return clean

        if channel == ExternalChannel.CRM_LEADS:
            # Resumen conciso para historial de CRM
            return clean

        return clean


# Singleton
_bridge_instance: ExternalConnectorBridge | None = None


def get_external_connector_bridge() -> ExternalConnectorBridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = ExternalConnectorBridge()
    return _bridge_instance
