"""Paquete del subsistema de voz (services.voice - Fase 30: Voice Assistant 2.0).

Exporta los servicios de captura de audio, VAD, Wake Word, STT (faster-whisper), TTS (edge-tts),
controlador de Barge-in, evaluador seguro de confirmaciones por voz y el pipeline de orquestación.
"""

from services.voice.audio_input import (
    AudioChunk,
    IAudioSource,
    MicrophoneAudioSource,
    SyntheticAudioSource,
)
from services.voice.barge_in_controller import BargeInController
from services.voice.stt_service import (
    FasterWhisperSTTService,
    ISTTService,
    MockSTTService,
    TranscriptResult,
)
from services.voice.tts_service import (
    DEFAULT_VOICE_NAME,
    EdgeTTSService,
    ITTSService,
    MockTTSService,
    TTSResult,
)
from services.voice.vad_service import (
    EnergyVADService,
    IVADService,
    VADEvent,
    VADResult,
)
from services.voice.voice_confirmation import (
    VoiceConfirmationDecision,
    VoiceConfirmationEvaluator,
)
from services.voice.voice_errors import (
    AudioDeviceDisconnectedError,
    MicrophonePermissionDeniedError,
    MicrophoneUnavailableError,
    STTError,
    STTModelUnavailableError,
    STTTimeoutError,
    TTSError,
    TTSFailureError,
    VADError,
    VADTimeoutError,
    VoiceAmbiguousConfirmationError,
    VoiceCancelledError,
    VoiceConfirmationError,
    VoiceError,
    VoiceInterruptedError,
    WakeWordError,
)
from services.voice.voice_pipeline import (
    VoiceInteractionResult,
    VoicePipeline,
)
from services.voice.wake_word_service import (
    IWakeWordService,
    KeywordWakeWordService,
    WakeWordResult,
)

__all__ = [
    "AudioChunk",
    "AudioDeviceDisconnectedError",
    "BargeInController",
    "DEFAULT_VOICE_NAME",
    "EdgeTTSService",
    "EnergyVADService",
    "FasterWhisperSTTService",
    "IAudioSource",
    "ISTTService",
    "ITTSService",
    "IVADService",
    "IWakeWordService",
    "KeywordWakeWordService",
    "MicrophoneAudioSource",
    "MicrophonePermissionDeniedError",
    "MicrophoneUnavailableError",
    "MockSTTService",
    "MockTTSService",
    "STTError",
    "STTModelUnavailableError",
    "STTTimeoutError",
    "SyntheticAudioSource",
    "TTSError",
    "TTSFailureError",
    "TTSResult",
    "TranscriptResult",
    "VADError",
    "VADEvent",
    "VADResult",
    "VADTimeoutError",
    "VoiceAmbiguousConfirmationError",
    "VoiceCancelledError",
    "VoiceConfirmationDecision",
    "VoiceConfirmationError",
    "VoiceConfirmationEvaluator",
    "VoiceError",
    "VoiceInteractionResult",
    "VoiceInterruptedError",
    "VoicePipeline",
    "WakeWordError",
    "WakeWordResult",
]
