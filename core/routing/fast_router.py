"""Fast Router determinista y de baja latencia para JESSYCA 4.0 (Fase 69).

Clasifica rápidamente solicitudes conocidas y comandos directos sin requerir
inferencia en modelos de lenguaje (LLM), reduciendo latencia y consumo de recursos.
Dirige comandos a Skills, preguntas a LLM y saludos a respuestas conversacionales.
Integrado de forma asíncrona con el Event Bus y la State Machine.
"""

from __future__ import annotations

import re
import threading
import traceback
import unicodedata
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.bus import EventBus, get_event_bus
from core.events.base import (
    ActionProposed,
    ClarificationRequested,
    ErrorOccurred,
    IntentClassified,
    SpeakRequested,
    UtteranceFinal,
)
from core.logger import get_logger
from core.state.machine import StateMachine
from core.state.states import SessionState

logger = get_logger("jessyca.fast_router")


class RouteCategory(StrEnum):
    """Categorías principales de enrutamiento del Fast Router."""

    COMMAND = "COMMAND"              # Solicitud directa de acción ejecutable por Skill
    CONVERSATION = "CONVERSATION"    # Saludo, despedida o chitchat con respuesta local rápida
    QUESTION = "QUESTION"            # Pregunta conceptual o de conocimiento (requiere LLM)
    COMPLEX = "COMPLEX"              # Solicitud multi-paso o razonamiento profundo (requiere LLM)
    AMBIGUOUS = "AMBIGUOUS"          # Intención de comando sin target suficiente (requiere aclaración)


@dataclass
class RouteDecision:
    """Decisión estructurada y explicable producida por el Fast Router."""

    category: RouteCategory
    intent: str
    confidence: float = 1.0
    target_skill: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    raw_text: str = ""
    requires_confirmation: bool = False
    suggested_response: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convierte la decisión a formato diccionario."""
        return {
            "category": self.category.value,
            "intent": self.intent,
            "confidence": round(self.confidence, 3),
            "target_skill": self.target_skill,
            "parameters": self.parameters,
            "reason": self.reason,
            "raw_text": self.raw_text,
            "requires_confirmation": self.requires_confirmation,
            "suggested_response": self.suggested_response,
            "metadata": self.metadata,
        }


class FastRouter:
    """Enrutador rápido y determinista basado en reglas semánticas de alta precisión."""

    # Catálogo canónico de aplicaciones soportadas en windows.apps
    KNOWN_APPS: dict[str, tuple[str, str]] = {
        "chrome": ("chrome", "Chrome"),
        "google": ("chrome", "Google"),
        "google chrome": ("chrome", "Chrome"),
        "youtube": ("chrome", "YouTube"),
        "el youtube": ("chrome", "YouTube"),
        "el google": ("chrome", "Google"),
        "bloc de notas": ("notepad", "Notepad"),
        "bloc notas": ("notepad", "Notepad"),
        "notepad": ("notepad", "Notepad"),
        "notas": ("notepad", "Notepad"),
        "calculadora": ("calc", "Calculator"),
        "calc": ("calc", "Calculator"),
        "paint": ("paint", "Paint"),
        "mspaint": ("paint", "Paint"),
        "cmd": ("cmd", "CMD"),
        "consola": ("cmd", "CMD"),
        "terminal": ("cmd", "CMD"),
        "powershell": ("powershell", "PowerShell"),
        "edge": ("msedge", "Edge"),
        "microsoft edge": ("msedge", "Edge"),
        "navegador": ("chrome", "Browser"),
        "explorador": ("explorer", "Explorer"),
        "archivos": ("explorer", "Explorer"),
    }

    # Pronombres y términos que denotan ambigüedad o falta de target
    AMBIGUOUS_TARGETS: frozenset[str] = frozenset({
        "eso", "esto", "aquello", "algo", "una cosa", "la cosa", "aqui", "aquí", "alla", "allá", ""
    })

    def __init__(
        self,
        event_bus: EventBus | None = None,
        state_machine: StateMachine | None = None,
    ) -> None:
        """Inicializa el Fast Router con soporte opcional de Event Bus y State Machine."""
        self._event_bus = event_bus or get_event_bus()
        self._state_machine = state_machine
        self._lock = threading.Lock()
        self._started = False
        logger.info("[FAST_ROUTER] FastRouter inicializado con reglas deterministas.")

    @property
    def is_started(self) -> bool:
        """Indica si el router está suscrito al Event Bus."""
        return self._started

    def start(self) -> None:
        """Suscribe el router a UtteranceFinal en el Event Bus de forma idempotente."""
        with self._lock:
            if self._started:
                return
            self._event_bus.subscribe(UtteranceFinal, self.on_utterance_final)
            self._started = True
            logger.info("[FAST_ROUTER] FastRouter iniciado y suscrito a UtteranceFinal.")

    def stop(self) -> None:
        """Cancela la suscripción en el Event Bus."""
        with self._lock:
            if not self._started:
                return
            self._event_bus.unsubscribe(UtteranceFinal, self.on_utterance_final)
            self._started = False
            logger.info("[FAST_ROUTER] FastRouter detenido y desuscrito.")

    def __enter__(self) -> FastRouter:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def normalize(self, text: str) -> str:
        """Normaliza el texto eliminando puntuación exterior, acentos y prefijos de invocación."""
        clean = text.strip()
        # Eliminar signos de interrogación o exclamación exteriores pero conservar internos
        clean = re.sub(r"^[¿¡\s]+|[?!.\s]+$", "", clean)
        clean_lower = clean.lower()
        # Retirar prefijos de wake word comunes
        clean_lower = re.sub(r"^(oye|hola|hey|ok|bueno)?\s*(jessyca|jessica)[,\s]*", "", clean_lower).strip()
        return clean_lower

    def _strip_accents(self, s: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

    def route(self, text: str) -> RouteDecision:
        """Evalúa un texto transcrito y produce una RouteDecision determinista.

        Orden de evaluación prioritario para prevenir falsos positivos:
        1. Textos vacíos o no válidos.
        2. Preguntas definitorias, conceptuales y epistemológicas -> QUESTION (LLM).
        3. Fórmulas de cortesía, saludos y conversación social -> CONVERSATION.
        4. Solicitudes complejas o multi-paso -> COMPLEX (LLM).
        5. Comandos directos de hardware y aplicaciones (Windows Skills) -> COMMAND.
        6. Comandos destructivos (shutdown, delete) -> COMMAND con confirmación requerida.
        7. Detección de ambigüedad en verbos de acción sin target -> AMBIGUOUS.
        8. Fallback general -> QUESTION / LLM.
        """
        raw = text.strip()
        if not raw:
            return RouteDecision(
                category=RouteCategory.AMBIGUOUS,
                intent="empty_input",
                confidence=0.0,
                reason="Entrada de texto vacía",
                raw_text=raw,
            )

        norm = self.normalize(raw)
        norm_no_accents = self._strip_accents(norm)

        # ── 1. CONVERSACIÓN SOCIAL, SALUDOS Y CHITCHAT ────────────────────────
        # Ej: "¿Cómo estás?", "Buenos días", "Hola", "Cuéntame algo", "Gracias"
        if norm_no_accents in (
            "hola", "buenos dias", "buenas tardes", "buenas noches", "hey",
            "que tal", "como te va", "como estas", "como te encuentras"
        ):
            resp = "¡Hola! Estoy muy bien, lista para ayudarte. ¿Qué deseas hacer hoy?"
            if "buenos dias" in norm_no_accents:
                resp = "¡Buenos días! Espero que tengas una excelente jornada. ¿En qué te ayudo?"
            elif "buenas tardes" in norm_no_accents:
                resp = "¡Buenas tardes! ¿En qué puedo colaborar contigo?"
            elif "buenas noches" in norm_no_accents:
                resp = "¡Buenas noches! ¿En qué puedo asistirte antes de descansar?"

            return RouteDecision(
                category=RouteCategory.CONVERSATION,
                intent="greeting" if "hola" in norm_no_accents or "buen" in norm_no_accents else "chit_chat",
                confidence=0.98,
                reason="Saludo o interacción de cortesía identificada localmente",
                raw_text=raw,
                suggested_response=resp,
            )

        if any(norm_no_accents.startswith(p) for p in ("cuentame algo", "dime algo", "hablame de ti", "quien eres")):
            return RouteDecision(
                category=RouteCategory.CONVERSATION,
                intent="chit_chat",
                confidence=0.92,
                reason="Petición conversacional de chitchat",
                raw_text=raw,
                suggested_response="Soy JESSYCA, tu asistente de voz e inteligencia para Windows. Puedo abrir aplicaciones, controlar audio, tomar capturas y resolver tus dudas.",
            )

        if norm_no_accents in ("gracias", "muchas gracias", "te lo agradezco", "mil gracias"):
            return RouteDecision(
                category=RouteCategory.CONVERSATION,
                intent="courtesy",
                confidence=0.99,
                reason="Expresión de gratitud del usuario",
                raw_text=raw,
                suggested_response="¡De nada! Es un placer ayudarte.",
            )

        # ── 2. PREVENCIÓN DE FALSOS POSITIVOS: PREGUNTAS DEFINITORIAS Y CONCEPTUALES ──
        # Ej: "¿Qué significa la palabra abrir?", "¿Qué es la gravedad?", "Explícame física básica"
        is_question = raw.startswith("¿") or any(
            norm_no_accents.startswith(p) for p in (
                "que significa", "que quiere decir", "cual es el significado",
                "significado de", "define", "definicion de", "definicion",
                "que es", "que son", "por que", "porque", "como funciona",
                "como es", "de que color", "cuanto es", "cuantos", "quien fue",
                "explicame", "explica", "dame un concepto", "dame una definicion",
                "dime que es", "cuentame sobre", "hablame de"
            )
        )

        if is_question:
            # Caso especial: "¿Puedes abrir Chrome?" -> Petición indirecta con fórmula de cortesía
            is_polite_command = any(
                norm_no_accents.startswith(cmd_p) for cmd_p in (
                    "puedes abrir", "podrias abrir", "puedes cerrar", "podrias cerrar",
                    "puedes subir", "podrias subir", "puedes bajar", "podrias bajar",
                    "puedes tomar", "podrias tomar"
                )
            )
            if not is_polite_command:
                return RouteDecision(
                    category=RouteCategory.QUESTION,
                    intent="knowledge_query",
                    confidence=0.95,
                    reason="Pregunta definitoria, conceptual o de conocimiento general dirigida al LLM",
                    raw_text=raw,
                )

        # ── 3. DETECCIÓN DE SOLICITUDES COMPLEJAS / MULTI-PASO ─────────────────
        # Ej: "Genera un script que...", "Escribe un correo formal para..."
        is_complex = len(norm) > 160 or any(
            norm_no_accents.startswith(p) for p in (
                "genera un script", "escribe un codigo", "crea un programa",
                "redacta un ensayo", "haz un resumen detallado", "analiza el archivo",
                "compara las teorias", "planifica un itinerario"
            )
        )
        if is_complex:
            return RouteDecision(
                category=RouteCategory.COMPLEX,
                intent="complex_reasoning",
                confidence=0.90,
                reason="Solicitud extensa o con requerimiento de razonamiento profundo delegada al LLM",
                raw_text=raw,
            )

        # ── 4. COMANDOS DIRECTOS: CAPTURA DE PANTALLA (windows.screenshot) ─────
        # Ej: "toma una captura", "captura de pantalla", "screenshot"
        if any(w in norm_no_accents for w in ("toma una captura", "haz una captura", "captura la pantalla", "captura de pantalla", "screenshot", "saca una captura")):
            return RouteDecision(
                category=RouteCategory.COMMAND,
                intent="screenshot",
                confidence=0.98,
                target_skill="windows.screenshot",
                parameters={"prompt": "captura de pantalla"},
                reason="Comando directo de captura de pantalla para windows.screenshot",
                raw_text=raw,
            )

        # ── 5. COMANDOS DIRECTOS: CONTROL DE VOLUMEN (windows.audio) ───────────
        # Ej: "sube el volumen", "baja el volumen", "silencia el audio"
        if any(w in norm_no_accents for w in ("sube el volumen", "subir volumen", "aumenta el volumen", "mas volumen", "sube volumen")):
            return RouteDecision(
                category=RouteCategory.COMMAND,
                intent="volume_up",
                confidence=0.98,
                target_skill="windows.audio",
                parameters={"accion": "establecer_delta", "delta": 10, "direction": "up"},
                reason="Comando de incremento de volumen para windows.audio",
                raw_text=raw,
            )

        if any(w in norm_no_accents for w in ("baja el volumen", "bajar volumen", "disminuye el volumen", "menos volumen", "baja volumen")):
            return RouteDecision(
                category=RouteCategory.COMMAND,
                intent="volume_down",
                confidence=0.98,
                target_skill="windows.audio",
                parameters={"accion": "establecer_delta", "delta": -10, "direction": "down"},
                reason="Comando de reducción de volumen para windows.audio",
                raw_text=raw,
            )

        if any(w in norm_no_accents for w in ("silencia", "silenciar", "mute", "quitar sonido")):
            return RouteDecision(
                category=RouteCategory.COMMAND,
                intent="volume_mute",
                confidence=0.95,
                target_skill="windows.audio",
                parameters={"accion": "silenciar"},
                reason="Comando de silencio para windows.audio",
                raw_text=raw,
            )

        # ── 6. COMANDOS DIRECTOS: MULTIMEDIA (windows.media) ──────────────────
        if any(w in norm_no_accents for w in ("bailame", "un baile", "el baile", "pon un baile", "reproduce un video")):
            return RouteDecision(
                category=RouteCategory.COMMAND,
                intent="play_random_video",
                confidence=0.95,
                target_skill="windows.media",
                parameters={"accion": "play_random_video"},
                reason="Comando de reproducción multimedia para windows.media",
                raw_text=raw,
            )

        # ── 6.1. COMANDOS DIRECTOS: YOUTUBE Y REPRODUCCIÓN WEB (browser.youtube) ──
        # Ej: "abre youtube y reproduce Playing Your Face", "reproduce Playing Your Face en youtube", "reproduce la musica..."
        compound_yt = re.match(
            r"^(?:puedes\s+|podrias\s+)?(?:abre|abrir)\s+youtube\s+y\s+(?:reproduce|reproducir|pon|inicia)\s+(?:la\s+musica\s+|la\s+cancion\s+|el\s+video\s+|el\s+tema\s+)?(.*)$",
            norm_no_accents,
        )
        if compound_yt:
            song_q = compound_yt.group(1).strip()
            if song_q:
                return RouteDecision(
                    category=RouteCategory.COMMAND,
                    intent="youtube_play",
                    confidence=0.98,
                    target_skill="browser.youtube",
                    parameters={"query": song_q, "operation": "compound_open_and_play"},
                    reason=f"Tarea compuesta de apertura y reproducción de '{song_q}' en YouTube",
                    raw_text=raw,
                )

        search_yt = re.match(
            r"^(?:puedes\s+|podrias\s+)?(?:ahora\s*)?(?:busca|buscar)\s+(?:la\s+musica\s+|la\s+cancion\s+|el\s+video\s+|el\s+tema\s+)?(.*?)\s+en\s+youtube$",
            norm_no_accents,
        )
        if search_yt:
            search_q = search_yt.group(1).strip()
            if search_q:
                return RouteDecision(
                    category=RouteCategory.COMMAND,
                    intent="youtube_search",
                    confidence=0.96,
                    target_skill="browser.youtube",
                    parameters={"query": search_q, "operation": "search"},
                    reason=f"Comando de búsqueda específica de '{search_q}' en YouTube",
                    raw_text=raw,
                )

        play_yt = re.match(
            r"^(?:puedes\s+|podrias\s+)?(?:reproduce|reproducir|pon|inicia|iniciar)\s+(?:la\s+musica\s+|la\s+cancion\s+|el\s+video\s+|el\s+tema\s+)?(.*?)(?:\s+en\s+youtube)?$",
            norm_no_accents,
        )
        if play_yt and not any(w in norm_no_accents for w in ("baile", "un baile", "el baile", "calculadora", "notepad", "bloc")):
            song_q = play_yt.group(1).strip()
            if song_q:
                clean_song = re.sub(r"\s+en\s+youtube$", "", song_q).strip()
                if clean_song and clean_song not in self.AMBIGUOUS_TARGETS:
                    return RouteDecision(
                        category=RouteCategory.COMMAND,
                        intent="youtube_play",
                        confidence=0.95,
                        target_skill="browser.youtube",
                        parameters={"query": clean_song, "operation": "play"},
                        reason=f"Comando de reproducción de '{clean_song}' en YouTube",
                        raw_text=raw,
                    )

        # ── 7. COMANDOS DIRECTOS: ABRIR APLICACIONES (windows.apps / browser.open) ────────────
        open_prefix_match = re.match(
            r"^(puedes\s+|podrias\s+)?(abre|abrir|inicia|iniciar|ejecuta|ejecutar|lanza|lanzar)\s*(el|la|los|las|un|una)?\s*(.*)$",
            norm_no_accents,
        )
        if open_prefix_match:
            raw_target = open_prefix_match.group(4).strip()

            # Comprobar caso ambiguo: sin target o target genérico ("eso", "esto")
            if not raw_target or raw_target in self.AMBIGUOUS_TARGETS:
                return RouteDecision(
                    category=RouteCategory.AMBIGUOUS,
                    intent="open_application",
                    confidence=0.35,
                    reason=f"Comando 'abrir' sin objetivo válido especificado (target='{raw_target}')",
                    raw_text=raw,
                    suggested_response="¿Qué aplicación o programa deseas que abra?",
                )

            # Sitios web conocidos en browser.open (previene intentar youtube.exe o google.exe)
            if raw_target in ("youtube", "el youtube"):
                return RouteDecision(
                    category=RouteCategory.COMMAND,
                    intent="open_browser",
                    confidence=0.97,
                    target_skill="browser.open",
                    parameters={"url": "https://www.youtube.com", "target": "YouTube"},
                    reason="Apertura directa de YouTube en el navegador",
                    raw_text=raw,
                )
            if raw_target in ("google", "el google"):
                return RouteDecision(
                    category=RouteCategory.COMMAND,
                    intent="open_browser",
                    confidence=0.97,
                    target_skill="browser.open",
                    parameters={"url": "https://www.google.com", "target": "Google"},
                    reason="Apertura directa de Google en el navegador",
                    raw_text=raw,
                )

            # Resolver aplicación en catálogo conocido
            app_tuple = self._resolve_known_app(raw_target)
            if app_tuple:
                app_exec, app_display = app_tuple
                return RouteDecision(
                    category=RouteCategory.COMMAND,
                    intent="open_application",
                    confidence=0.96,
                    target_skill="windows.apps",
                    parameters={"app_name": app_exec, "target": app_display},
                    reason=f"Comando directo de apertura de '{app_display}' para windows.apps",
                    raw_text=raw,
                )

            # Si tiene varias palabras o estructura de frase compleja, no es un comando simple de app
            if len(raw_target.split()) > 3:
                return RouteDecision(
                    category=RouteCategory.QUESTION,
                    intent="general_query",
                    confidence=0.60,
                    reason="Frase con 'abrir' pero estructura gramatical amplia; delegada al Orchestrator",
                    raw_text=raw,
                )

            # Si es una sola palabra plausible de aplicación
            return RouteDecision(
                category=RouteCategory.COMMAND,
                intent="open_application",
                confidence=0.85,
                target_skill="windows.apps",
                parameters={"app_name": raw_target, "target": raw_target},
                reason=f"Apertura de aplicación por nombre directo '{raw_target}'",
                raw_text=raw,
            )

        # ── 8. COMANDOS DESTRUCTIVOS / CIERRE DE APLICACIONES ─────────────────
        close_prefix_match = re.match(
            r"^(puedes\s+|podrias\s+)?(cierra|cerrar|apaga|apagar|deten|detener|termina|terminar)\s*(el|la|los|las|un|una)?\s*(.*)$",
            norm_no_accents,
        )
        if close_prefix_match:
            action_verb = close_prefix_match.group(2)
            raw_target = close_prefix_match.group(4).strip()

            # Caso destructivo de sistema: "apaga la computadora", "reinicia el equipo"
            if action_verb in ("apaga", "apagar", "reinicia", "reiniciar") and any(
                s in raw_target for s in ("computadora", "equipo", "pc", "sistema", "ordenador")
            ):
                is_reboot = "reinici" in action_verb or "reinici" in raw_target
                return RouteDecision(
                    category=RouteCategory.COMMAND,
                    intent="system_reboot" if is_reboot else "system_shutdown",
                    confidence=0.95,
                    target_skill="system",
                    parameters={"action": "reboot" if is_reboot else "shutdown"},
                    reason="Acción crítica de sistema que requiere confirmación explícita",
                    raw_text=raw,
                    requires_confirmation=True,
                )

            if not raw_target or raw_target in self.AMBIGUOUS_TARGETS:
                return RouteDecision(
                    category=RouteCategory.AMBIGUOUS,
                    intent="close_application",
                    confidence=0.30,
                    reason="Comando 'cerrar' sin objetivo especificado; no se ejecuta a ciegas",
                    raw_text=raw,
                    suggested_response="¿Qué aplicación o ventana deseas cerrar?",
                )

            app_tuple = self._resolve_known_app(raw_target)
            if app_tuple:
                app_exec, app_display = app_tuple
                return RouteDecision(
                    category=RouteCategory.COMMAND,
                    intent="close_application",
                    confidence=0.94,
                    target_skill="windows.apps",
                    parameters={"app_name": app_exec, "target": app_display},
                    reason=f"Comando de cierre de '{app_display}' para windows.apps",
                    raw_text=raw,
                    requires_confirmation=False,
                )

        # ── 9. COMANDO DESTRUCTIVO DE ARCHIVOS (delete_file) ───────────────────
        if any(norm_no_accents.startswith(p) for p in ("elimina ", "eliminar ", "borra ", "borrar ")):
            file_target = re.sub(r"^(elimina(r)?|borra(r)?)\s*(el\s*archivo)?\s*", "", norm_no_accents).strip()
            if file_target:
                return RouteDecision(
                    category=RouteCategory.COMMAND,
                    intent="delete_file",
                    confidence=0.90,
                    target_skill="files.delete",
                    parameters={"path": file_target},
                    reason="Comando destructivo de eliminación de archivos sujeto a confirmación",
                    raw_text=raw,
                    requires_confirmation=True,
                )

        # ── 10. FALLBACK DETERMINISTA: CONSULTA GENERAL AL ORCHESTRATOR / LLM ─
        return RouteDecision(
            category=RouteCategory.QUESTION,
            intent="general_query",
            confidence=0.50,
            reason="Petición sin regla determinista previa; delegada al Orchestrator/LLM",
            raw_text=raw,
        )

    def _resolve_known_app(self, raw_name: str) -> tuple[str, str] | None:
        """Busca una aplicación en el catálogo conocido tolerando variaciones."""
        clean = raw_name.strip().lower()
        if clean in self.KNOWN_APPS:
            return self.KNOWN_APPS[clean]

        for k, v in self.KNOWN_APPS.items():
            if clean.startswith(k) or k in clean:
                return v

        return None

    async def on_utterance_final(self, event: UtteranceFinal) -> None:
        """Handler asíncrono para eventos UtteranceFinal recibido desde el Event Bus."""
        raw_text = (event.text or "").strip()
        if not raw_text:
            return

        session_id = event.session_id or (
            self._state_machine.session_id if self._state_machine is not None else "default_session"
        )

        try:
            decision = self.route(raw_text)
            logger.info(
                f"[FAST_ROUTER] Decisión para '{raw_text}': {decision.category.value} / {decision.intent} "
                f"(confianza={decision.confidence:.2f})"
            )

            # Publicar IntentClassified
            intent_event = IntentClassified(
                intent=decision.intent,
                confidence=decision.confidence,
                slots=decision.parameters,
                raw_text=raw_text,
                session_id=session_id,
                metadata={
                    "category": decision.category.value,
                    "reason": decision.reason,
                    **event.metadata,
                },
            )
            await self._event_bus.publish(intent_event)

            # Enrutamiento de acción
            if decision.category == RouteCategory.COMMAND and decision.confidence >= 0.80:
                action_id = getattr(event, "action_id", None) or f"act-{uuid.uuid4().hex[:8]}"
                cmd_params = dict(decision.parameters)
                cmd_params.setdefault("action_id", action_id)
                action_event = ActionProposed(
                    action_name=decision.target_skill or decision.intent,
                    action_id=action_id,
                    parameters=cmd_params,
                    source="fast_router",
                    session_id=session_id,
                    metadata={
                        "intent": decision.intent,
                        "requires_confirmation": decision.requires_confirmation,
                        "action_id": action_id,
                        **event.metadata,
                    },
                )
                await self._event_bus.publish(action_event)

                if self._state_machine is not None:
                    if decision.requires_confirmation:
                        if self._state_machine.can_transition_to(SessionState.CONFIRMING):
                            self._state_machine.transition_to(SessionState.CONFIRMING)
                    else:
                        if self._state_machine.can_transition_to(SessionState.EXECUTING):
                            self._state_machine.transition_to(SessionState.EXECUTING)

            elif (
                decision.category == RouteCategory.CONVERSATION
                and decision.suggested_response
                and decision.confidence >= 0.80
            ):
                speak_event = SpeakRequested(
                    text=decision.suggested_response,
                    session_id=session_id,
                    metadata={"intent": decision.intent, "source": "fast_router", **event.metadata},
                )
                await self._event_bus.publish(speak_event)

                if self._state_machine is not None and self._state_machine.can_transition_to(SessionState.RESPONDING):
                    self._state_machine.transition_to(SessionState.RESPONDING)

            elif decision.category == RouteCategory.AMBIGUOUS and decision.suggested_response:
                clarif_event = ClarificationRequested(
                    question=decision.suggested_response,
                    original_text=raw_text,
                    session_id=session_id,
                    context={"intent": decision.intent},
                    metadata={"source": "fast_router", **event.metadata},
                )
                await self._event_bus.publish(clarif_event)

                if self._state_machine is not None and self._state_machine.can_transition_to(SessionState.CLARIFYING):
                    self._state_machine.transition_to(SessionState.CLARIFYING)

        except Exception as exc:
            logger.error(f"[FAST_ROUTER] Error procesando UtteranceFinal: {exc}", exc_info=True)
            try:
                err_event = ErrorOccurred(
                    error_message=str(exc),
                    error_type=exc.__class__.__name__,
                    session_id=session_id,
                    details={"raw_text": raw_text},
                    traceback=traceback.format_exc(),
                )
                await self._event_bus.publish(err_event)
            except Exception as bus_err:
                logger.error(f"[FAST_ROUTER] Error publicando ErrorOccurred: {bus_err}")
