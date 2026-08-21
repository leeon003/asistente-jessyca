"""Paquete del subsistema de voz (services.voice - Fase 13: Voice Pipeline).

Exporta los servicios de captura de audio, VAD, Wake Word, STT (faster-whisper), TTS (edge-tts)
y el pipeline de orquestación segura.
"""

from services.voice.audio_input import (
    AudioChunk,
    IAudioSource,
    MicrophoneAudioSource,
    SyntheticAudioSource,
)
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
    VoiceCancelledError,
    VoiceError,
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
    "TTSFailureError",
    "TTSResult",
    "TTSError",
    "TranscriptResult",
    "VADError",
    "VADEvent",
    "VADResult",
    "VADTimeoutError",
    "VoiceCancelledError",
    "VoiceError",
    "VoiceInteractionResult",
    "VoicePipeline",
    "WakeWordError",
    "WakeWordResult",
]
