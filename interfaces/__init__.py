"""Paquete de interfaces de usuario para JESSYCA (modo texto y modo voz)."""

from interfaces.modo_texto import iniciar_modo_texto
from interfaces.modo_voz import VoiceSpeaker, iniciar_modo_voz

__all__ = [
    "VoiceSpeaker",
    "iniciar_modo_texto",
    "iniciar_modo_voz",
]
