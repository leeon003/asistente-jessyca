"""Suite de pruebas para ExternalConnectorBridge (WhatsApp, Tiendas Ramy, CRM)."""

from __future__ import annotations

import pytest

from interfaces.external_connectors import (
    ExternalChannel,
    ExternalConnectorBridge,
    InboundMessage,
)


def test_01_whatsapp_inbound_flow():
    """Valida recepción y respuesta de un mensaje de WhatsApp VPS."""
    bridge = ExternalConnectorBridge()
    msg = InboundMessage(
        channel=ExternalChannel.WHATSAPP_VPS,
        sender_id="51987654321",
        text="Hola Jessyca, ¿qué hora es?",
    )
    res = bridge.handle_inbound_message(msg)
    assert res.channel == ExternalChannel.WHATSAPP_VPS
    assert res.recipient_id == "51987654321"
    assert res.session_id == "whatsapp_vps_51987654321"
    assert res.success is True
    assert len(res.text) > 0


def test_02_tiendas_ramy_inbound_flow():
    """Valida interacción desde el chat de Tiendas Ramy."""
    bridge = ExternalConnectorBridge()
    msg = InboundMessage(
        channel=ExternalChannel.TIENDAS_RAMY,
        sender_id="client_ramy_101",
        text="Hola, necesito información de atención",
    )
    res = bridge.handle_inbound_message(msg)
    assert res.channel == ExternalChannel.TIENDAS_RAMY
    assert res.session_id == "tiendas_ramy_client_ramy_101"
    assert res.success is True


def test_03_crm_leads_inbound_flow():
    """Valida mensaje de lead entrante desde CRM."""
    bridge = ExternalConnectorBridge()
    msg = InboundMessage(
        channel=ExternalChannel.CRM_LEADS,
        sender_id="lead_crm_889",
        text="Registrar consulta técnica de soporte",
        metadata={"client_name": "Juan Perez", "priority": "high"},
    )
    res = bridge.handle_inbound_message(msg)
    assert res.channel == ExternalChannel.CRM_LEADS
    assert res.recipient_id == "lead_crm_889"
    assert res.success is True
