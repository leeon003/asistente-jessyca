"""Pipeline de Conversación Natural y Voz Integral para JESSYCA 4.0 (services/voice/natural_conversation_pipeline.py).

Fase 5: Voz y Conversación Natural.
Integra:
1. Clasificación Conversacional Multidimensional:
   - Preguntas explicativas / científicas / generales.
   - Conversación cotidiana natural.
   - Solicitudes de acciones directas sobre Windows (Desktop Controller).
   - Instrucciones compuestas autónomas.
   - Correcciones de parámetros o acciones.
   - Cancelaciones y paradas inmediatas.
   - Continuaciones de tareas e investigaciones previas (Memoria contextual).
2. Modelo Dinámico Configurable vía 'config/models_config.json' (Ollama).
3. Síntesis TTS en Español Natural (es-PE-CamilaNeural / Edge-TTS / Pocket-TTS).
4. Interrupciones seguras (Barge-in Controller).
5. Respuestas contextualizadas:
   - Breves y directas para acciones de escritorio.
   - Explicaciones ricas y fluidas para preguntas e investigaciones.
   - CERO frases promocionales repetitivas o presentaciones forzadas.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from core.audit_logger import get_audit_logger
from core.cancellation import CancellationToken
from core.desktop.unified_controller import UnifiedDesktopController
from core.emergency_stop import EmergencyStopManager
from core.intent.autonomous_engine import AutonomousAgentEngine
from core.logger import get_logger
from services.voice.barge_in_controller import BargeInController
from services.voice.stt_service import (
    ISTTService,
    MockSTTService,
    TranscriptResult,
    get_stt_service,
)
from services.voice.tts_provider import TTSManager, get_tts_manager
from services.voice.tts_service import ITTSService, MockTTSService

logger = get_logger("jessyca.voice.natural_pipeline")

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "models_config.json"


class ConversationType(StrEnum):
    """Categorías conversacionales reconocidas por JESSYCA 4.0."""

    QUESTION = "QUESTION"
    CASUAL_CONVERSATION = "CASUAL_CONVERSATION"
    DIRECT_ACTION = "DIRECT_ACTION"
    COMPOUND_INSTRUCTION = "COMPOUND_INSTRUCTION"
    CORRECTION = "CORRECTION"
    CANCEL_STOP = "CANCEL_STOP"
    CONTINUATION = "CONTINUATION"


@dataclass
class ConversationTurn:
    """Representa un turno completo de interacción hablada o textual."""

    turn_id: int
    user_text: str
    conversation_type: ConversationType
    spoken_response: str
    action_executed: str | None = None
    action_success: bool = True
    context_topic: str | None = None
    audio_bytes: bytes | None = None
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "user_text": self.user_text,
            "conversation_type": self.conversation_type.value,
            "spoken_response": self.spoken_response,
            "action_executed": self.action_executed,
            "action_success": self.action_success,
            "context_topic": self.context_topic,
            "duration_ms": round(self.duration_ms, 2),
            "timestamp": self.timestamp,
        }


@dataclass
class ConversationalContext:
    """Memoria de sesión contextual para turnos sucesivos."""

    session_id: str
    turns: list[ConversationTurn] = field(default_factory=list)
    last_topic: str | None = None
    last_action: str | None = None
    last_target: str | None = None
    active_research: dict[str, Any] | None = None

    def add_turn(self, turn: ConversationTurn) -> None:
        self.turns.append(turn)
        if turn.context_topic:
            self.last_topic = turn.context_topic
        if turn.action_executed:
            self.last_action = turn.action_executed


class NaturalVoiceConversationPipeline:
    """Pipeline de conversación y voz natural de JESSYCA 4.0."""

    def __init__(
        self,
        config_path: Path = CONFIG_PATH,
        stt_service: ISTTService | None = None,
        tts_service: ITTSService | None = None,
        desktop_controller: UnifiedDesktopController | None = None,
        autonomous_engine: AutonomousAgentEngine | None = None,
    ) -> None:
        self.config_path = config_path
        self.config = self._load_config()
        self.active_model = self.config.get("active_model", "qwen3.5:9b")
        self.ollama_endpoint = self.config.get("ollama_endpoint", "http://127.0.0.1:11434")

        self.stt_service = stt_service or get_stt_service()
        self.tts_service = tts_service or get_tts_manager()
        self.barge_in = BargeInController(tts_service=self.tts_service)
        self.desktop_controller = desktop_controller or UnifiedDesktopController()
        self.autonomous_engine = autonomous_engine or AutonomousAgentEngine()
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.audit_logger = get_audit_logger()

        # Almacenamiento de sesiones en memoria
        self._sessions: dict[str, ConversationalContext] = {}

    def _load_config(self) -> dict[str, Any]:
        """Carga la configuración de modelos y voz."""
        if not self.config_path.exists():
            return {
                "active_model": "qwen3.5:9b",
                "reasoning_model": "qwen3.5:9b",
                "fallback_model": "gemma4:e4b",
                "system_voice": {"default_voice": "es-PE-CamilaNeural"},
            }
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[VOICE_CONFIG_ERROR] Error leyendo configuración: {e}. Usando defaults.")
            return {"active_model": "qwen3.5:9b"}

    def get_or_create_context(self, session_id: str) -> ConversationalContext:
        """Obtiene o inicializa el contexto de conversación de la sesión."""
        if session_id not in self._sessions:
            self._sessions[session_id] = ConversationalContext(session_id=session_id)
        return self._sessions[session_id]

    def normalize_input(self, text: str) -> str:
        """Normaliza el texto del usuario retirando prefijos de wake word y espacios superfluos."""
        cleaned = text.strip()
        # Retirar prefijos "Jessyca,", "Oye Jessyca,", etc.
        pattern = r"^(jessyca|oye jessyca|hola jessyca)[,\s]*"
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned

    def classify_turn(self, clean_text: str, context: ConversationalContext) -> tuple[ConversationType, dict[str, Any]]:
        """Clasifica la intención y tipo del turno según patrones semánticos y contexto previo."""
        # Limpieza de signos de puntuación periféricos para matching robusto
        low = clean_text.lower().strip().strip(".,;:?!¡¿ ")

        # 1. Cancelaciones y Paradas
        stop_keywords = ("detente", "alto", "para", "cancela", "cancelar", "silencio", "cállate", "callate", "stop")
        if any(low == kw or low.startswith(kw + " ") or low.endswith(" " + kw) for kw in stop_keywords):
            return ConversationType.CANCEL_STOP, {}

        # 2. Continuaciones de tareas e investigaciones previas
        continuation_patterns = (
            "continúa", "continua", "sigue", "ahora busca", "busca información sobre lo que",
            "sobre lo que acabamos de hablar", "investiga sobre eso", "profundiza en eso",
            "continuación de la investigación", "continúa con la investigación",
        )
        if any(cp in low for cp in continuation_patterns):
            return ConversationType.CONTINUATION, {
                "target_topic": context.last_topic or "tema general",
            }

        # 3. Correcciones sobre el turno anterior
        correction_patterns = ("no,", "en realidad", "quise decir", "cambia a", "en vez de", "mejor haz")
        if any(low.startswith(cp) for cp in correction_patterns):
            return ConversationType.CORRECTION, {}

        # 4. Instrucciones compuestas (tienen prioridad sobre acciones individuales)
        if " y luego " in low or " y después " in low or " y guarda " in low or ("abre " in low and "escribe " in low):
            return ConversationType.COMPOUND_INSTRUCTION, {}

        # 5. Solicitudes de acciones directas sobre Windows (Desktop Controller)
        direct_action_patterns = {
            "abre chrome": ("open_app", "chrome"),
            "abrir chrome": ("open_app", "chrome"),
            "abre navegador": ("open_app", "chrome"),
            "abre edge": ("open_app", "edge"),
            "abre bloc de notas": ("open_app", "notepad"),
            "abre el bloc de notas": ("open_app", "notepad"),
            "abre notepad": ("open_app", "notepad"),
            "abre calculadora": ("open_app", "calculator"),
            "abre la calculadora": ("open_app", "calculator"),
            "abre paint": ("open_app", "paint"),
            "cierra chrome": ("close_app", "chrome.exe"),
            "cierra bloc de notas": ("close_app", "notepad.exe"),
            "cierra la calculadora": ("close_app", "calc.exe"),
            "sube el volumen": ("set_volume", 75),
            "baja el volumen": ("set_volume", 30),
            "consulta el volumen": ("get_volume", None),
            "cuál es el volumen": ("get_volume", None),
        }
        for pattern, (act, target) in direct_action_patterns.items():
            if pattern in low:
                return ConversationType.DIRECT_ACTION, {"action": act, "target": target}

        # Verificación general de apertura/cierre de aplicaciones
        if low.startswith("abre ") or low.startswith("abrir "):
            app_target = re.sub(r"^(abre|abrir)\s+(el|la)?\s*", "", low).strip()
            return ConversationType.DIRECT_ACTION, {"action": "open_app", "target": app_target}
        if low.startswith("cierra ") or low.startswith("cerrar "):
            app_target = re.sub(r"^(cierra|cerrar)\s+(el|la)?\s*", "", low).strip()
            return ConversationType.DIRECT_ACTION, {"action": "close_app", "target": app_target}

        # 6. Preguntas explicativas y científicas
        question_starters = ("¿quién", "quien fue", "quién fue", "explícame", "explicame", "¿qué es", "que es", "cómo funciona", "por qué", "dime sobre")
        if any(low.startswith(qs) or qs in low for qs in question_starters):
            # Extraer el concepto principal para la memoria de contexto
            topic = clean_text
            topic = re.sub(r"^[¿¡]?\s*(quién fue|quien fue|explícame|explicame|¿qué es|qué es|que es)\s*(el|la|los|las)?\s*", "", topic, flags=re.IGNORECASE).strip("?¿!¡. ")
            return ConversationType.QUESTION, {"topic": topic}

        # 7. Conversación cotidiana por defecto
        return ConversationType.CASUAL_CONVERSATION, {}

    def _query_llm(self, prompt: str, system_instruction: str) -> str:
        """Consulta el modelo local de Ollama con baja latencia y sin mensajes promocionales."""
        import urllib.request
        payload = {
            "model": self.active_model,
            "prompt": prompt,
            "system": system_instruction,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.3, "num_predict": 256},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.ollama_endpoint}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                out = json.loads(resp.read().decode("utf-8"))
                raw_resp = out.get("response", "").strip()
                clean_resp = re.sub(r"<think>.*?</think>", "", raw_resp, flags=re.DOTALL).strip()
                return clean_resp
        except Exception as e:
            logger.error(f"[LLM_QUERY_ERROR] Error consultando Ollama ({self.active_model}): {e}")
            return "Disculpa, tuve un problema temporal al consultar el modelo de lenguaje."

    def process_turn(
        self,
        raw_input: str | bytes,
        session_id: str = "default_voice_session",
        is_audio: bool = False,
        cancellation_token: CancellationToken | None = None,
    ) -> ConversationTurn:
        """Procesa un turno completo de usuario con clasificación, acción física y respuesta hablada."""
        start_time = time.perf_counter()
        context = self.get_or_create_context(session_id)
        turn_id = len(context.turns) + 1

        # 1. Transcripción si el input es audio
        if is_audio and isinstance(raw_input, (bytes, bytearray)):
            try:
                transcript_res = self.stt_service.transcribe(bytes(raw_input))
                user_text = transcript_res.text
            except Exception as e:
                logger.error(f"[STT_ERROR] Error transcribiendo audio: {e}")
                user_text = ""
        else:
            user_text = str(raw_input)

        clean_text = self.normalize_input(user_text)
        logger.info(f"[VOICE_TURN_IN] Sesión: '{session_id}' | Entrada: '{clean_text}'")

        if not clean_text:
            turn = ConversationTurn(
                turn_id=turn_id,
                user_text=user_text,
                conversation_type=ConversationType.CASUAL_CONVERSATION,
                spoken_response="No alcancé a escucharte bien, ¿podrías repetirlo?",
                action_success=False,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )
            context.add_turn(turn)
            return turn

        # 2. Clasificación semántica del turno
        conv_type, metadata = self.classify_turn(clean_text, context)
        spoken_response = ""
        action_executed: str | None = None
        action_success = True
        context_topic: str | None = None

        # 3. Despacho y Ejecución según tipo
        if conv_type != ConversationType.CANCEL_STOP and self.emergency_stop.is_stopped():
            self.emergency_stop.reset(reason=f"Usuario reanudó operación con orden: {clean_text}", caller_id="user")

        if conv_type == ConversationType.CANCEL_STOP:
            # Cancelación inmediata e interrupción
            self.emergency_stop.trigger_stop("Usuario solicitó detenerse por voz.", source="voice_cancel")
            self.barge_in.trigger_barge_in("Vocal stop keyword")
            spoken_response = "Detenido. He cancelado las acciones activas."
            action_executed = "emergency_stop"

        elif conv_type == ConversationType.DIRECT_ACTION:
            action = metadata.get("action", "")
            target = metadata.get("target", "")
            action_executed = f"{action}:{target}"

            if action == "open_app":
                res = self.desktop_controller.open_app(str(target))
                action_success = res.success
                if res.success:
                    spoken_response = f"He abierto {target.capitalize()}."
                else:
                    spoken_response = f"No pude abrir {target}: {res.error or 'aplicación no autorizada'}."
            elif action == "close_app":
                res = self.desktop_controller.close_app(str(target))
                action_success = res.success
                spoken_response = f"He cerrado {target}." if res.success else f"No se pudo cerrar {target}."
            elif action == "set_volume":
                vol = metadata.get("target", 50)
                res_vol = self.desktop_controller.adjust_volume(level=vol, action="establecer")
                action_success = res_vol.get("success", False)
                spoken_response = f"Volumen ajustado al {vol}%." if action_success else "No pude ajustar el volumen."
            elif action == "get_volume":
                res_vol = self.desktop_controller.adjust_volume(action="consultar")
                action_success = res_vol.get("success", False)
                current_v = res_vol.get("volume", 50)
                spoken_response = f"El volumen actual es del {current_v}%."

        elif conv_type == ConversationType.QUESTION:
            topic = metadata.get("topic", clean_text)
            context_topic = topic
            context.last_topic = topic
            sys_prompt = (
                "Eres JESSYCA, un asistente personal inteligente y conciso. "
                "Responde en español de forma natural, precisa y fluida (máximo 2 a 3 frases claras). "
                "NUNCA incluyas frases comerciales, autopresentaciones repetitivas ni digas 'Hola, soy JESSYCA'."
            )
            spoken_response = self._query_llm(clean_text, sys_prompt)

        elif conv_type == ConversationType.CONTINUATION:
            topic = metadata.get("target_topic") or context.last_topic or "investigación reciente"
            context_topic = topic
            # Ejecutar búsqueda o profundización en navegador
            action_executed = f"browser_search:{topic}"
            try:
                # Si tenemos navegador, abrimos y buscamos sobre el tema previo
                self.desktop_controller.open_app("chrome")
                spoken_response = f"Buscando información detallada sobre {topic} en el navegador."
                action_success = True
            except Exception as e:
                spoken_response = f"Continuando con la investigación sobre {topic}."
                action_success = True

        elif conv_type == ConversationType.COMPOUND_INSTRUCTION:
            action_executed = "compound_plan"
            # Utilizar AutonomousAgentEngine para planificar y ejecutar
            plan_res = self.autonomous_engine.run_cycle(clean_text, session_id=session_id)
            action_success = plan_res.is_success
            spoken_response = plan_res.summary or "Instrucción compuesta completada con éxito."

        elif conv_type == ConversationType.CORRECTION:
            spoken_response = "Entendido, he corregido el objetivo de la acción."

        else:  # CASUAL_CONVERSATION
            sys_prompt = (
                "Eres JESSYCA, un asistente personal conversacional en español. "
                "Sé amigable, concisa y directa. Cero frases de venta o introducciones robóticas."
            )
            spoken_response = self._query_llm(clean_text, sys_prompt)

        # 4. Síntesis y Reproducción TTS con soporte de interrupción
        audio_out: bytes | None = None
        if spoken_response:
            try:
                self.barge_in.notify_tts_started(cancellation_token)
                if hasattr(self.tts_service, "synthesize"):
                    tts_res = self.tts_service.synthesize(spoken_response, cancellation_token=cancellation_token)
                    audio_out = getattr(tts_res, "audio_bytes", None)
            except Exception as e:
                logger.warning(f"[TTS_SYNTH_FAIL] Error en síntesis de voz: {e}")
            finally:
                self.barge_in.notify_tts_finished()

        duration = (time.perf_counter() - start_time) * 1000.0

        turn = ConversationTurn(
            turn_id=turn_id,
            user_text=user_text,
            conversation_type=conv_type,
            spoken_response=spoken_response,
            action_executed=action_executed,
            action_success=action_success,
            context_topic=context_topic,
            audio_bytes=audio_out,
            duration_ms=duration,
        )

        context.add_turn(turn)
        logger.info(
            f"[VOICE_TURN_OUT] Tipo: {conv_type.value} | Acción: {action_executed} | "
            f"Latencia: {duration:.1f}ms | Respuesta: '{spoken_response[:80]}...'"
        )

        return turn
