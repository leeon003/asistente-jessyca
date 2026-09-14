"""Definición de los estados fundamentales para el ciclo de vida de sesión en JESSYCA 4.0."""

from __future__ import annotations

from enum import StrEnum


class SessionState(StrEnum):
    """Estados del ciclo de vida de una sesión conversacional y de ejecución en JESSYCA.

    Valores:
        IDLE: En reposo, a la espera de activación (Wake Word o comando directo).
        WAKEWORD: Palabra de activación detectada, inicializando captura de comando.
        LISTENING: Capturando flujo de audio o entrada del usuario.
        TRANSCRIBING: Procesando audio a texto (STT).
        ROUTING: Clasificando intención, evaluando enrutamiento (Fast Router / LLM).
        CONFIRMING: Esperando confirmación explícita del usuario para acciones sensibles.
        CLARIFYING: Esperando aclaración del usuario ante ambigüedad.
        EXECUTING: Ejecutando herramienta, skill o comando del sistema.
        VERIFYING: Verificando resultado de la acción o condiciones post-ejecución.
        RESPONDING: Emitiendo respuesta al usuario (TTS o texto).
    """

    IDLE = "IDLE"
    WAKEWORD = "WAKEWORD"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    ROUTING = "ROUTING"
    CONFIRMING = "CONFIRMING"
    CLARIFYING = "CLARIFYING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RESPONDING = "RESPONDING"

    def __str__(self) -> str:
        return self.value
