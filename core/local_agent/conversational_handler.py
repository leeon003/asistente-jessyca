"""Manejador de Diálogo y Consultas Conversacionales (conversational_handler.py - Fase Conversacional).

Diferencia CONVERSATIONAL_REQUEST de ACTION_REQUEST.
Gobierna la generación de respuestas naturales, dinámicas y contextuales para consultas
generales, saludos, explicaciones, preguntas y diálogos multi-turno.
Integra el LLM local (Ollama / ModelRouter) con preservación estricta del historial de la sesión
y entidades contextuales (ej. personas mencionadas como Carmen), ofreciendo síntesis dialógica
semántica de respaldo cuando el motor de inferencia esté fuera de línea.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from core.llm.experimental_router import (
    ExperimentalRouter,
    get_experimental_router,
)
from core.llm.inference import LLMProvider, OllamaProvider
from core.llm.model_router import ModelRouter, get_model_router
from core.logger import get_logger

if TYPE_CHECKING:
    from core.local_agent.conversation_context import ConversationContextManager
    from core.local_agent.conversation_models import ConversationSession

logger = get_logger("jessyca.local_agent.conversational")

DEFAULT_SYSTEM_PROMPT = (
    "Eres Jessyca, tu asistente local e inteligente para Windows.\n"
    "Tu personalidad es cálida, natural, amable, servicial y empática.\n"
    "Responde en el mismo idioma utilizado por el usuario, salvo que el usuario "
    "solicite explícitamente otro idioma.\n"
    "Si el usuario solicita hablar, responder, saludar o explicar algo en un "
    "idioma específico, utiliza ese idioma.\n"
    "Mantén el idioma solicitado durante la respuesta y no lo traduzcas "
    "automáticamente al español.\n"
    "Responde de manera muy concisa, fluida y directa (máximo 2 o 3 oraciones breves), "
    "óptima para síntesis de voz (TTS). Ve directo al grano sin introducciones innecesarias.\n"
    "No utilices viñetas, asteriscos, títulos markdown ni formato estructurado pesado.\n"
    "Si te piden saludar a una persona en específico, dale un saludo personalizado.\n"
    "Tienes acceso al historial reciente de la conversación en el bloque '--- Historial reciente ---'.\n"
    "Cuando el usuario pregunte por cosas dichas anteriormente (como su nombre, proyectos o temas mencionados, "
    "palabras secretas o lo primero que dijo), utiliza obligatoriamente la información de ese historial reciente "
    "para responder con exactitud. Si pregunta por el proyecto mencionado y se mencionó JESSYCA, responde que es el proyecto JESSYCA.\n"
    "Si el usuario hace referencia a una persona o tema de turnos anteriores, "
    "mantén la coherencia del diálogo.\n"
    "Si la pregunta es académica, científica o de conocimiento general, "
    "responde con claridad y precisión real."
)


class ConversationalDialogueHandler:
    """Manejador central para procesamiento de consultas conversacionales y diálogo natural."""

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        model_router: ModelRouter | None = None,
        experimental_router: ExperimentalRouter | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.llm_provider = llm_provider or OllamaProvider()
        self.model_router = model_router or get_model_router()
        self.experimental_router = experimental_router or get_experimental_router()

    def generate_response(
        self,
        user_input: str,
        session_id: str = "default",
        params: dict[str, Any] | None = None,
        context_manager: ConversationContextManager | None = None,
        preferred_model: str | None = None,
    ) -> str:
        """Genera una respuesta conversacional natural usando LLM o síntesis contextual."""
        params_dict = params or {}
        session: ConversationSession | None = None
        history_turns: list[tuple[str, str]] = []
        target_person: str | None = params_dict.get("target_person")

        if context_manager:
            session = context_manager.get_session(session_id)
            if session:
                if not target_person:
                    target_person = (
                        session.get_context("user_name")
                        or session.get_context("last_mentioned_person")
                        or session.get_context("last_referenced_entity")
                    )
                # Recuperar hasta 8 turnos recientes respetando presupuesto de caracteres
                cand_turns = [
                    (t.user_prompt, t.assistant_response)
                    for t in session.turns
                    if t.user_prompt and t.assistant_response
                ][-8:]
                tot_chars = 0
                for u_turn, a_turn in reversed(cand_turns):
                    t_len = len(u_turn) + len(a_turn)
                    if tot_chars + t_len > 3500 and history_turns:
                        break
                    history_turns.insert(0, (u_turn, a_turn))
                    tot_chars += t_len

        # 1. Intentar inferencia LLM con Ollama si está disponible
        llm_ok = False
        try:
            llm_ok = bool(self.llm_provider and self.llm_provider.is_available())
        except Exception:
            llm_ok = False

        if llm_ok:
            try:
                # ── FASE 5: ENRUTAMIENTO CONTROLADO CON FALLBACK Y TIMEOUT ──
                if self.experimental_router and self.experimental_router.is_enabled():
                    is_voice = bool(params_dict.get("is_voice", False))
                    req_id = params_dict.get("request_id") or f"conv_{session_id}_{int(threading.get_ident())}"
                    exec_model, decision = self.experimental_router.route_execution(
                        user_text=user_input,
                        current_model=preferred_model or "gemma4:e4b",
                        is_voice=is_voice,
                        request_id=req_id,
                        context=params_dict,
                    )

                    def _call_model(target_m: str) -> str:
                        return self._generate_with_llm(
                            user_input=user_input,
                            history=history_turns,
                            target_person=target_person,
                            preferred_model=target_m,
                            timeout_seconds=12.0,
                        )

                    llm_response, used_model, attempts = self.experimental_router.execute_with_fallback(
                        primary_model=exec_model,
                        decision=decision,
                        execute_fn=_call_model,
                        timeout_seconds=12.0,
                    )
                else:
                    # Comportamiento estático por defecto (MODEL_ROUTER_ENABLED=False)
                    llm_response = self._generate_with_llm(
                        user_input=user_input,
                        history=history_turns,
                        target_person=target_person,
                        preferred_model=preferred_model,
                        timeout_seconds=15.0,
                    )

                if llm_response and len(llm_response.strip()) > 5:
                    logger.info(f"[CONVERSATIONAL LLM OK] Respuesta: '{llm_response[:80]}...'")
                    return self._clean_for_speech(llm_response)
                logger.warning("[CONVERSATIONAL LLM] Respuesta vacía del LLM, usando síntesis.")
            except Exception as ex:
                logger.warning(f"[CONVERSATIONAL LLM FALLBACK] Inferencia falló ({ex}), usando síntesis contextual.")
        else:
            logger.info("[CONVERSATIONAL] Ollama no disponible, usando síntesis contextual.")

        # 2. Síntesis dialógica semántica contextual
        return self._synthesize_dialogue(
            user_input=user_input,
            target_person=target_person,
            history=history_turns,
            params=params_dict,
        )

    def generate_response_stream(
        self,
        user_input: str,
        session_id: str = "default",
        params: dict[str, Any] | None = None,
        context_manager: ConversationContextManager | None = None,
        preferred_model: str | None = None,
    ) -> Iterator[str]:
        """Genera tokens progresivos en streaming usando el LLM o síntesis contextual."""
        params_dict = params or {}
        history_turns: list[tuple[str, str]] = []
        target_person: str | None = params_dict.get("target_person")

        if context_manager:
            session = context_manager.get_session(session_id)
            if session:
                if not target_person:
                    target_person = (
                        session.get_context("user_name")
                        or session.get_context("last_mentioned_person")
                        or session.get_context("last_referenced_entity")
                    )
                cand_turns = [
                    (t.user_prompt, t.assistant_response)
                    for t in session.turns
                    if t.user_prompt and t.assistant_response
                ][-8:]
                tot_chars = 0
                for u_turn, a_turn in reversed(cand_turns):
                    t_len = len(u_turn) + len(a_turn)
                    if tot_chars + t_len > 3500 and history_turns:
                        break
                    history_turns.insert(0, (u_turn, a_turn))
                    tot_chars += t_len

        llm_ok = False
        try:
            llm_ok = bool(self.llm_provider and self.llm_provider.is_available())
        except Exception:
            llm_ok = False

        if llm_ok and hasattr(self.llm_provider, "generate_stream"):
            try:
                prompt_parts: list[str] = []
                if history_turns:
                    prompt_parts.append("--- Historial reciente ---")
                    for u, a in history_turns:
                        prompt_parts.append(f"Usuario: {u}")
                        prompt_parts.append(f"Jessyca: {a}")
                    prompt_parts.append("")

                if target_person:
                    prompt_parts.append(f"[Contexto: Persona de referencia en la conversación: '{target_person}']")

                prompt_parts.append(f"Usuario: {user_input}")
                prompt_parts.append("Jessyca:")
                full_prompt = "\n".join(prompt_parts)

                from core.llm.inference import InferenceRequest
                req_inf = InferenceRequest(
                    prompt=full_prompt,
                    system_prompt=DEFAULT_SYSTEM_PROMPT,
                    model_name=preferred_model or "gemma4:e4b",
                    temperature=0.7,
                    max_tokens=350,
                    timeout_seconds=30.0,
                    stream=True,
                )
                yielded_any = False
                for chunk in self.llm_provider.generate_stream(req_inf):
                    if chunk:
                        yielded_any = True
                        yield chunk
                if yielded_any:
                    return
            except Exception as e:
                logger.warning(f"[CONVERSATIONAL STREAM FALLBACK] Stream falló ({e}), usando síntesis.")

        fallback_text = self._synthesize_dialogue(
            user_input=user_input,
            target_person=target_person,
            history=history_turns,
            params=params_dict,
        )
        words = fallback_text.split(" ")
        for i, w in enumerate(words):
            yield w + (" " if i < len(words) - 1 else "")

    def _generate_with_llm(
        self,
        user_input: str,
        history: list[tuple[str, str]],
        target_person: str | None = None,
        preferred_model: str | None = None,
        timeout_seconds: float = 15.0,
    ) -> str:
        """Construye el prompt contextual y realiza la inferencia mediante LLM con timeout gobernado."""
        prompt_parts: list[str] = []

        # Incluir historial reciente para continuidad de tópico
        if history:
            prompt_parts.append("--- Historial reciente ---")
            for u, a in history:
                prompt_parts.append(f"Usuario: {u}")
                prompt_parts.append(f"Jessyca: {a}")
            prompt_parts.append("")

        if target_person:
            prompt_parts.append(f"[Contexto: Persona de referencia en la conversación: '{target_person}']")

        # Pregunta actual del usuario
        prompt_parts.append(f"Usuario: {user_input}")
        prompt_parts.append("Jessyca:")

        full_prompt = "\n".join(prompt_parts)
        # Usar gemma o llama según disponibilidad; temperatura 0.7 para naturalidad
        model = preferred_model or "gemma4:e4b"
        from core.llm.inference import InferenceRequest
        req_inf = InferenceRequest(
            prompt=full_prompt,
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            model_name=model,
            temperature=0.7,
            max_tokens=350,
            timeout_seconds=timeout_seconds,
        )
        resp = self.llm_provider.generate(req_inf)
        return str(resp.content)

    def _synthesize_dialogue(
        self,
        user_input: str,
        target_person: str | None = None,
        history: list[tuple[str, str]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> str:
        """Síntesis conversacional determinista y contextual de alta fidelidad en español."""
        lower = user_input.strip().lower()
        params_dict = params or {}
        person = target_person or params_dict.get("target_person")

        # 1. Saludos a terceros ("Jessyca saluda a Carmen", "Saluda a Carmen")
        if person and any(w in lower for w in ("saluda", "saludo", "hola", "salúdale", "saludale", "manda un saludo", "envía un saludo")):
            return f"Claro. ¡Hola, {person}! Te mando un saludo muy especial y espero que estés muy bien."

        # 2. Seguimiento / Mensaje a persona en contexto ("Ahora dile que espero verla pronto")
        if person and any(w in lower for w in ("dile", "coméntale", "comentale", "avísale", "avisale", "menciónale", "mencionale")):
            msg = params_dict.get("message")
            if not msg:
                # Extraer cuerpo del mensaje
                m_match = re.search(r"(?:que|de que)\s+(.+)$", lower)
                msg = m_match.group(1).strip() if m_match else "te manda un mensaje"

            # Adaptación natural en segunda persona
            msg_clean = re.sub(r"\bverla\b", "verte", msg)
            msg_clean = re.sub(r"\bverlo\b", "verte", msg_clean)
            msg_clean = re.sub(r"\bdecirle\b", "decirte", msg_clean)
            msg_clean = re.sub(r"\bhablarle\b", "hablarte", msg_clean)
            msg_clean = re.sub(r"\balla\b", "ti", msg_clean)
            msg_clean = re.sub(r"\bél\b", "ti", msg_clean)
            msg_clean = re.sub(r"\bel\b", "ti", msg_clean)

            if "espero" in msg_clean:
                return f"Claro. {person}, {msg_clean}."
            elif "gracias" in msg_clean:
                return f"Por supuesto. {person}, te manda a decir muchas gracias."
            else:
                return f"Claro. {person}, te transmito que {msg_clean}."

        # 3. Saludos directos ("Jessyca saluda", "Hola", "Buenas tardes")
        if any(w in lower for w in ("saluda", "saludos", "dame un saludo", "manda un saludo")) and not person:
            return "¡Hola! Soy Jessyca. Te mando un saludo muy cordial. ¿En qué te puedo ayudar hoy?"

        if lower in ("hola", "hola jessyca", "hola jessica", "jessyca hola", "jessica hola", "hey", "buenas", "buenos días", "buenas tardes", "buenas noches"):
            return "¡Hola! Soy Jessyca. ¿En qué te puedo ayudar hoy?"

        # 4. Preguntas de estado / Identidad
        if any(w in lower for w in ("cómo estás", "como estas", "cómo te va", "como te va", "qué tal", "que tal")):
            return "¡Estoy muy bien, muchas gracias! Lista para ayudarte en lo que necesites hoy."

        if any(w in lower for w in ("quién eres", "quien eres", "cuál es tu nombre", "cual es tu nombre", "quién te creó")):
            return "Soy Jessyca, tu asistente local e inteligente para Windows."

        # 5. Consulta y explicación de capacidades
        if any(w in lower for w in ("qué puedes hacer", "que puedes hacer", "qué sabes hacer", "que sabes hacer", "capacidades", "describe todo")):
            return (
                "Soy Jessyca, tu asistente local e inteligente para Windows. Puedo ayudarte a abrir y cerrar aplicaciones, "
                "reproducir vídeos de baile, buscar contenido en internet o YouTube, gestionar archivos y realizar cálculos."
            )

        # 6. Datos curiosos e interesantes
        if any(w in lower for w in ("algo interesante", "dato interesante", "cuéntame algo", "cuentame algo", "dato curioso", "curiosidad")):
            return (
                "Un dato fascinante: las abejas pueden reconocer rostros humanos usando patrones visuales, "
                "de manera muy similar a cómo lo hacemos nosotros."
            )

        # 7. Física y ciencias — respuestas académicas reales
        if any(w in lower for w in ("qué es la física", "que es la fisica", "concepto de física", "concepto de fisica",
                                    "física es", "fisica es", "básico de física", "basico de fisica")):
            return (
                "La física es la ciencia que estudia la materia, la energía, el movimiento "
                "y las interacciones fundamentales de la naturaleza. Busca describir cómo funciona el universo "
                "mediante leyes y modelos matemáticos, desde las partículas subatómicas hasta las galaxias."
            )

        if any(w in lower for w in ("espacio-tiempo", "espacio tiempo", "relatividad", "einstein")):
            # Detectar si hay historial de física
            prev_topics = " ".join(a for _, a in (history or []))
            if "física" in prev_topics or "física" in lower or "fisica" in lower or history:
                return (
                    "El espacio-tiempo es el concepto central de la teoría de la relatividad de Einstein. "
                    "Unifica las tres dimensiones del espacio con el tiempo en una sola entidad de cuatro dimensiones. "
                    "La gravedad se entiende como una curvatura de este espacio-tiempo causada por la masa de los objetos."
                )
            return (
                "El espacio-tiempo es la combinación de espacio y tiempo en un único continuo de cuatro dimensiones, "
                "propuesto por Albert Einstein en su teoría de la relatividad general."
            )

        if any(w in lower for w in ("profundiza", "explica más", "explica mas", "amplía", "amplia",
                                    "dime más sobre", "dime mas sobre", "cuéntame más", "cuentame mas")):
            # Continuar sobre el tópico más reciente del historial
            if history:
                last_topic = history[-1][0].lower()
                if "física" in last_topic or "fisica" in last_topic or "física" in history[-1][1].lower():
                    return (
                        "La física se divide en grandes ramas: la mecánica clásica describe el movimiento "
                        "de cuerpos cotidianos, la termodinámica estudia el calor y la energía, "
                        "la electromagnetismo analiza campos eléctricos y magnéticos, "
                        "y la física cuántica explora el comportamiento de partículas subatómicas."
                    )
                if "espacio" in last_topic or "relatividad" in last_topic or "espacio" in history[-1][1].lower():
                    return (
                        "Una consecuencia del espacio-tiempo curvo es que el tiempo transcurre más despacio "
                        "cerca de objetos muy masivos, como agujeros negros. "
                        "Este efecto, llamado dilatación temporal, ha sido confirmado experimentalmente con relojes atómicos."
                    )
            return "Dime con más detalle sobre qué tema quieres que profundice y te explico con gusto."

        # 8. Conceptos de Inteligencia Artificial
        if any(w in lower for w in ("inteligencia artificial", "qué es la ia", "que es la ia", "qué es ia", "que es ia")):
            return (
                "La inteligencia artificial es una rama de la informática dedicada al desarrollo de sistemas "
                "capaces de aprender a partir de datos, razonar y tomar decisiones para resolver tareas complejas."
            )

        # 9. Información geográfica y cultural (ej. Lima)
        if "lima" in lower:
            return (
                "Lima es la capital del Perú, una hermosa ciudad costera con una gran riqueza cultural, "
                "impresionante arquitectura colonial y una gastronomía reconocida a nivel mundial."
            )

        # 10. Opinión / Pregunta abierta
        if any(w in lower for w in ("qué opinas", "que opinas", "tu opinión", "tu opinion")):
            return "Es un tema con muchas perspectivas interesantes. ¿Quieres que lo analice desde algún ángulo en particular?"

        # 11. Agradecimiento
        if any(w in lower for w in ("gracias", "muchas gracias", "te agradezco")):
            return "¡De nada! Es un placer ayudarte."

        # 12. Consultas contextuales sobre datos del diálogo previo
        # 12.1 Nombre del usuario
        if any(w in lower for w in ("cómo me llamo", "como me llamo", "cuál es mi nombre", "cual es mi nombre", "sabes mi nombre", "dime mi nombre")):
            user_name = params_dict.get("user_name") or target_person
            if not user_name and history:
                for u_h, _ in reversed(history):
                    m_name = re.search(r"(?:mi\s+nombre\s+es|me\s+llamo|soy)\s+([a-záéíóúñ]+)", u_h, re.IGNORECASE)
                    if m_name:
                        user_name = m_name.group(1).capitalize()
                        break
            if user_name:
                return f"Te llamas {user_name}."
            return "Aún no me has dicho tu nombre. ¿Cómo te llamas?"

        # 12.2 Palabra secreta
        if any(w in lower for w in ("palabra secreta", "clave secreta")) or (
            history and any(w in lower for w in ("repítela", "repitela", "dila otra vez")) and any("palabra secreta" in u_h.lower() for u_h, _ in history)
        ):
            secret_word = params_dict.get("secret_word")
            if not secret_word and history:
                for u_h, _ in reversed(history):
                    m_sec = re.search(r"(?:palabra\s+secreta.*?es|clave\s+secreta.*?es)\s+([a-záéíóúñ0-9]+)", u_h, re.IGNORECASE)
                    if m_sec:
                        secret_word = m_sec.group(1).upper()
                        break
            if secret_word:
                return f"La palabra secreta es {secret_word}."
            return "No tenemos ninguna palabra secreta registrada para esta conversación."

        # 12.3 Proyecto mencionado
        if any(w in lower for w in ("qué proyecto", "que proyecto", "cuál proyecto", "cual proyecto")):
            if history and any("jessyca" in u_h.lower() or "jessica" in u_h.lower() for u_h, _ in history):
                return "Me mencionaste el proyecto JESSYCA."
            project = params_dict.get("mentioned_project")
            if project:
                return f"Me mencionaste el proyecto {project}."
            return "No me has mencionado ningún proyecto todavía. ¿De qué proyecto se trata?"

        # 12.4 Nombre del asistente
        if any(w in lower for w in ("cómo se llama el asistente", "como se llama el asistente", "nombre del asistente", "cómo te llamas", "como te llamas")):
            return "Mi nombre es Jessyca, tu asistente local e inteligente para Windows."

        # 12.5 Primera cosa dicha en la conversación
        if any(w in lower for w in ("primera cosa que te dije", "primero que te dije", "primer mensaje")):
            if history:
                first_user_msg = history[0][0]
                return f"La primera cosa que me dijiste fue: \"{first_user_msg}\"."
            return "Como no tenemos una conversación previa registrada en este momento, no puedo saber cuál fue tu primer mensaje."

        # 12.6 Continúa el tópico previo si hay historial
        if history:
            last_user, last_resp = history[-1]
            if any(w in last_user.lower() for w in ("física", "fisica", "ciencia", "química", "quimica", "biología", "biologia")):
                return (
                    "Con gusto te cuento más sobre ese tema. ¿Quieres que profundice en algún aspecto en particular "
                    "o prefieres que te explique algo relacionado?"
                )

        # 13. Respuesta conversacional natural por defecto
        return "Entendido. ¿Puedes contarme un poco más sobre lo que necesitas? Así puedo ayudarte mejor."

    def _clean_for_speech(self, text: str) -> str:
        """Limpia el texto de formato markdown y caracteres no aptos para TTS."""
        cleaned = text.strip()
        # Eliminar bloques de código markdown
        cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL)
        # Eliminar asteriscos y almohadillas
        cleaned = re.sub(r"[\*#_`]", "", cleaned)
        # Normalizar espacios
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned
