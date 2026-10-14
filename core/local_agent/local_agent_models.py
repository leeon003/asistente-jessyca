"""Modelos de datos unificados y contratos para JESSYCA Local Agent (local_agent_models.py - Fase 45).

Define las estructuras de petición unificada, respuesta multimodal, métricas de voz y latencia,
así como el estado de contexto conversacional sin acoplamiento a permisos.

PRINCIPIOS DE DISEÑO E INVARIANTES:
1. UNIFIED EXPERIENCE: El usuario interactúa naturalmente sin conocer la arquitectura interna (Skills, Agents, Models, Tools, Graphs).
2. CONTEXT != AUTHORIZATION != MEMORY: El historial de conversación o memoria no otorgan permisos de ejecución.
3. SECURITY FIRST: Toda acción pasa por el SecurityPipeline y respeta la Parada de Emergencia.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from core.security_architecture import SecurityLevel

if TYPE_CHECKING:
    from core.action_intent_contract import ActionIntentContract


class InputModality(StrEnum):
    """Modalidades de entrada soportadas por el Agente Local."""

    TEXT = "text"
    VOICE = "voice"
    MULTIMODAL = "multimodal"
    IMAGE = "image"
    SCREEN = "screen"
    FILE = "file"


class AgentExecutionState(StrEnum):
    """Estados del ciclo de vida de ejecución de una petición."""

    IDLE = "IDLE"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    ANALYZING_INTENT = "ANALYZING_INTENT"
    PLANNING = "PLANNING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"
    EXECUTING = "EXECUTING"
    SYNTHESIZING_VOICE = "SYNTHESIZING_VOICE"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass
class LocalAgentMetrics:
    """Métricas integrales de calidad de voz, latencia y rendimiento del Agente Local."""

    task_id: str = ""
    correlation_id: str = ""
    request_id: str = ""
    capture_latency_ms: float = 0.0          # Tiempo de captura de entrada (audio/texto/pantalla)
    speech_end_ms: float = 0.0               # Timestamp/duración de detección de fin de habla
    stt_accuracy: float = 1.0                # Nivel de confianza / precisión transcripción (0.0 a 1.0)
    stt_latency_ms: float = 0.0              # Tiempo de procesamiento de Speech-to-Text
    classification_latency_ms: float = 0.0   # Tiempo de clasificación semántica de intención
    intent_latency_ms: float = 0.0           # Alias compatible de clasificación
    routing_latency_ms: float = 0.0          # Tiempo de enrutamiento de modelo/agente
    agent_routing_latency_ms: float = 0.0    # Alias compatible de enrutamiento
    model_load_latency_ms: float = 0.0       # Tiempo de carga/conmutación de modelo en VRAM
    inference_latency_ms: float = 0.0        # Tiempo de inferencia LLM
    model_inference_latency_ms: float = 0.0  # Alias compatible de inferencia
    authorization_latency_ms: float = 0.0    # Tiempo de autorización / evaluación de seguridad / JDE
    tool_execution_latency_ms: float = 0.0   # Tiempo de ejecución de herramienta
    execution_latency_ms: float = 0.0        # Alias compatible de ejecución
    verification_latency_ms: float = 0.0     # Tiempo de verificación post-ejecución en el SO
    first_audio_tts_latency_ms: float = 0.0  # Tiempo hasta emitir primer fragmento de audio (TTFT)
    planning_latency_ms: float = 0.0         # Tiempo de generación del SkillGraph o plan
    tts_latency_ms: float = 0.0              # Tiempo total de síntesis de voz Text-to-Speech
    total_latency_ms: float = 0.0            # Latencia total end-to-end
    wake_word_detected: bool = False         # Si se activó vía Wake Word
    wake_word_confidence: float = 1.0        # Confianza del detector de Wake Word
    wake_word_latency_ms: float = 0.0        # Latencia de detección de Wake Word
    interruption_handled: bool = False       # Si el usuario interrumpió / canceló durante el turno

    def __post_init__(self) -> None:
        if not self.request_id:
            self.request_id = self.correlation_id or self.task_id
        if not self.task_id:
            self.task_id = self.request_id
        if not self.correlation_id:
            self.correlation_id = self.request_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id or self.request_id,
            "correlation_id": self.correlation_id or self.request_id,
            "request_id": self.request_id or self.correlation_id or self.task_id,
            "capture_latency_ms": round(self.capture_latency_ms, 2),
            "speech_end_ms": round(self.speech_end_ms, 2),
            "stt_accuracy": round(self.stt_accuracy, 3),
            "stt_latency_ms": round(self.stt_latency_ms, 2),
            "classification_latency_ms": round(self.classification_latency_ms or self.intent_latency_ms, 2),
            "intent_latency_ms": round(self.intent_latency_ms or self.classification_latency_ms, 2),
            "routing_latency_ms": round(self.routing_latency_ms or self.agent_routing_latency_ms, 2),
            "agent_routing_latency_ms": round(self.agent_routing_latency_ms or self.routing_latency_ms, 2),
            "model_load_latency_ms": round(self.model_load_latency_ms, 2),
            "inference_latency_ms": round(self.inference_latency_ms or self.model_inference_latency_ms, 2),
            "model_inference_latency_ms": round(self.model_inference_latency_ms or self.inference_latency_ms, 2),
            "authorization_latency_ms": round(self.authorization_latency_ms, 2),
            "tool_execution_latency_ms": round(self.tool_execution_latency_ms or self.execution_latency_ms, 2),
            "execution_latency_ms": round(self.execution_latency_ms or self.tool_execution_latency_ms, 2),
            "verification_latency_ms": round(self.verification_latency_ms, 2),
            "first_audio_tts_latency_ms": round(self.first_audio_tts_latency_ms, 2),
            "planning_latency_ms": round(self.planning_latency_ms, 2),
            "tts_latency_ms": round(self.tts_latency_ms, 2),
            "total_latency_ms": round(self.total_latency_ms, 2),
            "wake_word_detected": self.wake_word_detected,
            "wake_word_confidence": round(self.wake_word_confidence, 3),
            "interruption_handled": self.interruption_handled,
        }


@dataclass
class JessycaRequest:
    """Petición unificada enviada al Agente Local JESSYCA."""

    request_id: str = field(default_factory=lambda: f"req-{uuid.uuid4().hex[:8]}")
    session_id: str = "default_session"
    modality: InputModality = InputModality.TEXT
    user_input: str = ""
    audio_data: bytes | None = None
    images: list[bytes] = field(default_factory=list)
    screen_capture: bytes | None = None
    file_attachments: list[str] = field(default_factory=list)
    browser_context: dict[str, Any] = field(default_factory=dict)
    require_wake_word: bool = False
    conversation_context: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    monotonic_deadline: float | None = None


@dataclass(frozen=True)
class ConversationTurn:
    """Turno conversacional inmutable en el historial."""

    turn_id: str = field(default_factory=lambda: f"turn-{uuid.uuid4().hex[:8]}")
    role: str = "USER"
    raw_input: str = ""
    normalized_input: str = ""
    user_prompt: str = ""
    assistant_response: str = ""
    intent: str = "unknown"
    intent_confidence: float = 1.0
    modality: InputModality = InputModality.TEXT
    tools_executed: tuple[str, ...] = ()
    security_verdict: str = "ALLOW"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "role": str(self.role),
            "raw_input": self.raw_input or self.user_prompt,
            "normalized_input": self.normalized_input,
            "user_prompt": self.user_prompt,
            "assistant_response": self.assistant_response,
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "modality": str(self.modality),
            "tools_executed": list(self.tools_executed),
            "security_verdict": self.security_verdict,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class JessycaResponse:
    """Respuesta consolidada unificada del Agente Local JESSYCA."""

    request_id: str
    session_id: str
    success: bool
    status: AgentExecutionState
    response_text: str
    spoken_text: str = ""
    intent: str = "unknown"
    selected_model: str = "auto"
    selected_agent: str = "auto"
    selected_skill: str = "auto"
    selected_graph: str = "auto"
    tools_executed: list[str] = field(default_factory=list)
    security_verdict: str = "ALLOW"
    security_level: SecurityLevel = SecurityLevel.SAFE
    requires_confirmation: bool = False
    requires_clarification: bool = False
    clarification_question: str | None = None
    original_transcript: str | None = None
    proposed_interpretation: str | None = None
    output_data: Any = None
    error: str | None = None
    metrics: LocalAgentMetrics = field(default_factory=LocalAgentMetrics)
    timestamp: float = field(default_factory=time.time)
    action_intent_contract: ActionIntentContract | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "success": self.success,
            "status": str(self.status),
            "response_text": self.response_text,
            "spoken_text": self.spoken_text,
            "intent": self.intent,
            "selected_model": self.selected_model,
            "selected_agent": self.selected_agent,
            "selected_skill": self.selected_skill,
            "selected_graph": self.selected_graph,
            "tools_executed": list(self.tools_executed),
            "security_verdict": self.security_verdict,
            "security_level": str(self.security_level),
            "requires_confirmation": self.requires_confirmation,
            "requires_clarification": self.requires_clarification,
            "clarification_question": self.clarification_question,
            "original_transcript": self.original_transcript,
            "proposed_interpretation": self.proposed_interpretation,
            "output_data": self.output_data,
            "error": self.error,
            "metrics": self.metrics.to_dict(),
            "timestamp": self.timestamp,
            "action_intent_contract": (
                self.action_intent_contract.model_dump()
                if self.action_intent_contract is not None
                else None
            ),
        }
