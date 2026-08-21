"""Excepciones formales y tipadas para el pipeline de voz (voice_errors.py - Fase 13).

Define las clases de error para captura de audio, VAD, palabra de activación, STT y TTS.
"""

from __future__ import annotations

from core.exceptions import MCPError


class VoiceError(MCPError):
    """Error base del subsistema de voz."""

    pass


class MicrophoneUnavailableError(VoiceError):
    """Error emitido cuando no se detecta o no está disponible el micrófono."""

    pass


class MicrophonePermissionDeniedError(VoiceError):
    """Error emitido cuando el sistema operativo deniega acceso al micrófono."""

    pass


class AudioDeviceDisconnectedError(VoiceError):
    """Error emitido cuando el dispositivo de audio se desconecta durante la captura."""

    pass


class VADError(VoiceError):
    """Error emitido durante el procesamiento de Voice Activity Detection."""

    pass


class VADTimeoutError(VADError):
    """Error emitido cuando expira el tiempo de espera por voz o silencio."""

    pass


class WakeWordError(VoiceError):
    """Error emitido durante la detección de la palabra de activación."""

    pass


class STTError(VoiceError):
    """Error base para fallos de transcripción Speech-to-Text."""

    pass


class STTTimeoutError(STTError):
    """Error emitido cuando expira el tiempo límite de inferencia de STT."""

    pass


class STTModelUnavailableError(STTError):
    """Error emitido cuando el modelo de STT (faster-whisper) no está disponible."""

    pass


class TTSError(VoiceError):
    """Error base para fallos de síntesis de voz Text-to-Speech."""

    pass


class TTSFailureError(TTSError):
    """Error emitido cuando el motor de TTS (edge-tts) falla en generar audio."""

    pass


class VoiceCancelledError(VoiceError):
    """Error emitido cuando la operación de voz es cancelada explícitamente."""

    pass
