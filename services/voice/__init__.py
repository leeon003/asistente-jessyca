"""Paquete del subsistema de voz (services.voice - Fases 30, 51, 51.1 & 52).

Exporta los servicios de captura de audio, calibración, diagnósticos, VAD, Wake Word,
STT, TTS, controlador de Barge-in, sesiones continuas y el pipeline de orquestación.
"""

from typing import Any

from services.voice.audio_capture import (
    AmbientNoiseCalibrator,
    CalibratedVoiceCaptureEngine,
    MicrophoneDeviceInfo,
    MicrophoneDiagnostics,
    NoiseCalibrationResult,
    VoiceCaptureResult,
)
from services.voice.audio_device_manager import (
    AudioDeviceDescriptor,
    AudioDeviceManager,
    AudioDeviceSelectionReport,
    SignalValidationStatus,
    get_audio_device_manager,
)
from services.voice.audio_input import (
    AudioChunk,
    IAudioSource,
    MicrophoneAudioSource,
    SyntheticAudioSource,
)
from services.voice.barge_in_controller import BargeInController
from services.voice.continuous_voice_session import (
    AudioPreRollBuffer,
    ContinuousVoiceSession,
    VoiceSessionMode,
)
from services.voice.device_resolver import (
    ResolvedAudioDevice,
    VoiceDeviceResolver,
    get_voice_device_resolver,
)
from services.voice.push_to_talk import (
    PushToTalkController,
    PushToTalkState,
    PTTExecutionResult,
    TTSProviderComparisonItem,
    compare_tts_providers,
)
from services.voice.stt_event_adapter import STTEventAdapter
from services.voice.stt_service import (
    FasterWhisperSTTService,
    ISTTService,
    MockSTTService,
    TranscriptResult,
)
from services.voice.tts_provider import (
    BaseTTSProvider,
    EdgeTTSProvider,
    PocketTTSProvider,
    TTSManager,
    TTSMetrics,
    get_tts_manager,
)
from services.voice.tts_service import (
    DEFAULT_VOICE_NAME,
    EdgeTTSService,
    ITTSService,
    MockTTSService,
    TTSResult,
)
from services.voice.turn_manager import (
    PURE_INTERRUPTION_PHRASES,
    TurnManager,
    VoiceTurnState,
)
from services.voice.vad_service import (
    EnergyVADService,
    IVADService,
    VADEvent,
    VADResult,
    get_vad_service,
)
from services.voice.voice_confirmation import (
    VoiceConfirmationDecision,
    VoiceConfirmationEvaluator,
)
from services.voice.voice_diagnostics import (
    VoiceCaptureDiagnostic,
    VoiceDiscardReason,
    VoiceTelemetryCollector,
    get_voice_telemetry,
)
from services.voice.voice_errors import (
    AudioDeviceDisconnectedError,
    MicrophonePermissionDeniedError,
    MicrophoneUnavailableError,
    SileroVADUnavailableError,
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
from services.voice.natural_conversation_pipeline import (
    ConversationTurn,
    ConversationType,
    ConversationalContext,
    NaturalVoiceConversationPipeline,
)
from services.voice.voice_pipeline import (
    VoiceInteractionResult,
    VoicePipeline,
)
from services.voice.wake_word_service import (
    IWakeWordService,
    KeywordWakeWordService,
    WakeWordResult,
    get_wake_word_service,
)

__all__ = [
    "AmbientNoiseCalibrator",
    "AudioChunk",
    "AudioDeviceDescriptor",
    "AudioDeviceDisconnectedError",
    "AudioDeviceManager",
    "AudioDeviceSelectionReport",
    "AudioPreRollBuffer",
    "BargeInController",
    "BaseTTSProvider",
    "CalibratedVoiceCaptureEngine",
    "ContinuousVoiceSession",
    "ConversationTurn",
    "ConversationType",
    "ConversationalContext",
    "NaturalVoiceConversationPipeline",
    "DEFAULT_VOICE_NAME",
    "EdgeTTSProvider",
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
    "MicrophoneDeviceInfo",
    "MicrophoneDiagnostics",
    "MicrophonePermissionDeniedError",
    "MicrophoneUnavailableError",
    "MockSTTService",
    "MockTTSService",
    "NoiseCalibrationResult",
    "PURE_INTERRUPTION_PHRASES",
    "PocketTTSProvider",
    "ResolvedAudioDevice",
    "STTError",
    "PTTExecutionResult",
    "PushToTalkController",
    "PushToTalkState",
    "STTEventAdapter",
    "STTModelUnavailableError",
    "STTTimeoutError",
    "SignalValidationStatus",
    "SyntheticAudioSource",
    "TTSError",
    "TTSFailureError",
    "TTSManager",
    "TTSMetrics",
    "TTSResult",
    "TranscriptResult",
    "TurnManager",
    "VADError",
    "VADEvent",
    "VADResult",
    "VADTimeoutError",
    "VoiceAmbiguousConfirmationError",
    "VoiceCancelledError",
    "VoiceCaptureDiagnostic",
    "VoiceCaptureResult",
    "VoiceConfirmationDecision",
    "VoiceConfirmationError",
    "VoiceConfirmationEvaluator",
    "VoiceDeviceResolver",
    "VoiceDiscardReason",
    "VoiceError",
    "VoiceInteractionResult",
    "VoiceInterruptedError",
    "VoicePipeline",
    "VoiceSessionMode",
    "VoiceTelemetryCollector",
    "VoiceTurnState",
    "WakeWordError",
    "WakeWordResult",
    "get_audio_device_manager",
    "get_tts_manager",
    "get_vad_service",
    "get_voice_device_resolver",
    "get_voice_telemetry",
    "get_wake_word_service",
    "SileroVADService",
    "SileroVADUnavailableError",
    "OpenWakeWordAcousticService",
]


def __getattr__(name: str) -> Any:
    """Importación perezosa (lazy) de adaptadores neuronales opcionales."""
    if name == "SileroVADService":
        from services.voice.silero_vad_service import SileroVADService

        return SileroVADService
    if name == "OpenWakeWordAcousticService":
        from services.voice.openwakeword_service import OpenWakeWordAcousticService

        return OpenWakeWordAcousticService
    raise AttributeError(f"módulo {__name__!r} no tiene el atributo {name!r}")


