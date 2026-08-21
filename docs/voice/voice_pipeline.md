# PIPELINE DE VOZ — JESSYCA 3.0 (FASE 13)

## 1. Arquitectura del Voice Pipeline

El subsistema de voz implementado en `services/voice/` permite la interacción por lenguaje natural hablado mediante una arquitectura completamente desacoplada y gobernada por el sistema de seguridad central:

```text
┌─────────────────────────────────────────────────────────────┐
│                      MICROPHONE / AUDIO                     │
│               (services/voice/audio_input.py)               │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                         VAD SERVICE                         │
│             (services/voice/vad_service.py)                 │
│      (speech_start, speech_end, silence, timeout)           │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      WAKE WORD SERVICE                      │
│          (services/voice/wake_word_service.py)              │
│            ("Jessyca" -> WAKE WORD != AUTH)                 │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                         STT SERVICE                         │
│            (services/voice/stt_service.py)                  │
│       (faster-whisper -> TranscriptResult tipado)           │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     TEXT / ORCHESTRATOR                     │
│         (Mismo pipeline de ejecución que texto)             │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  MODEL ROUTER / AGENT SYSTEM                │
│             (DesktopAgent, SystemAgent, FileAgent)          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       SECURITY LAYER                        │
│    (RiskEngine -> PermissionMgr -> ConfirmationMgr -> ...)  │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                         EXECUTION                           │
│                      (Windows MCP Tool)                     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                         TTS SERVICE                         │
│            (services/voice/tts_service.py)                  │
│     (edge-tts: es-PE-CamilaNeural, no bloqueante)           │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                           SPEAKER                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Invariante Inmutable de Seguridad

- **`VOICE INPUT = UNTRUSTED DATA`**:
  - La voz sigue exactamente el mismo pipeline que texto.
  - Cero creación de `VoiceSecurity` o mecanismos de bypass separados.
  - La detección de la palabra clave de activación ("Jessyca") o una transcripción exitosa **NO CONSTITUYE AUTORIZACIÓN**.
  - Toda acción resultante se evalúa de manera determinista en el `SecurityPipeline` (`RiskEngine`, `PermissionManager`, `ConfirmationManager`, `ActionGuard`).

---

## 3. Componentes Implementados

1. **Captura de Audio (`services/voice/audio_input.py`)**:
   - `AudioChunk`: Fragmento de audio inmutable con cálculo RMS de energía y timestamp.
   - `MicrophoneAudioSource` y `SyntheticAudioSource` para pruebas en memoria y CI/CD sin micrófono físico.
2. **Detección de Actividad de Voz (`services/voice/vad_service.py`)**:
   - `EnergyVADService`: Detección de inicio/fin de habla, silencios y timeouts para acotar el uso de CPU.
3. **Palabra de Activación (`services/voice/wake_word_service.py`)**:
   - `KeywordWakeWordService`: Reconocimiento local de "Jessyca" en memoria efímera.
4. **Speech-to-Text (`services/voice/stt_service.py`)**:
   - `FasterWhisperSTTService` / `MockSTTService`: Transcripción estructurada a `TranscriptResult`.
5. **Text-to-Speech (`services/voice/tts_service.py`)**:
   - `EdgeTTSService` / `MockTTSService`: Síntesis de voz con `es-PE-CamilaNeural`, no bloqueante y con soporte para `CancellationToken`.
6. **Orquestador (`services/voice/voice_pipeline.py`)**:
   - `VoicePipeline`: Coordinación completa con control de fallos, parada de emergencia y cancelación.

---

## 4. Resultados de Verificación

| Métrica / Suite | Pruebas | Resultado |
|:---|:---:|:---:|
| **`pytest tests/voice/test_voice_pipeline.py`** | 9 pruebas | ✅ **9 / 9 PASS** |
| **`ruff check services/voice tests/voice`** | Reglas de estilo | ✅ **All checks passed!** |
| **`mypy`** | Tipado estático | ✅ **0 errores en el paquete** |
