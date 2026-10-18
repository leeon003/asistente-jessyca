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
    "Eres Jessyca, asistente local para Windows.\n"
    "PERSONALIDAD Y TONO: Habla en un español natural, cercano, educado y directo. "
    "No seas acartonada ni distante, pero ve siempre al grano sin rodeos.\n"
    "RESPONDE PRIMERO Y PROPORCIONAL: Contesta primero exactamente a lo que se te pregunta. "
    "Adapta la extensión de tu respuesta de forma proporcional a la solicitud del usuario: si pide dos frases, "
    "responde en dos frases; si pide un ejemplo, da el ejemplo concreto de inmediato; no añadas relleno innecesario.\n"
    "CERO AUTOPRESENTACIONES Y CERO PITCH AUTOMÁTICO: Prohibido presentarte en cada turno ('Hola, soy Jessyca...', 'Como tu asistente...'), "
    "ofrecer discursos de ventas o recitar listas de capacidades, salvo que el usuario pregunte expresamente quién eres o qué sabes hacer.\n"
    "CIERRE NATURAL SIN PREGUNTAS FORZADAS: No termines sistemáticamente cada turno con una pregunta o coletilla de cortesía "
    "(como '¿En qué más te ayudo?', '¿Tienes dudas?', '¿Quieres que profundicemos?'). Termina con la información solicitada o una afirmación clara.\n"
    "USO DEL CONTEXTO Y CORRECCIONES: Tienes acceso al historial reciente. Si el usuario hace referencia a algo previo, "
    "sigue el hilo con coherencia. Si el usuario te corrige diciendo que no entendiste o que se refería a otra cosa, "
    "reconócelo con naturalidad ('Tienes razón', 'Entendido') y reorienta la respuesta hacia su punto específico sin justificaciones defensivas.\n"
    "INCERTIDUMBRE Y DISCREPANCIA FUNDAMENTADA: Reconoce francamente cuando un dato no se conoce o sea incierto. "
    "Si una premisa del usuario es técnicamente inexacta o riesgosa, discrepa con educación explicando las razones objetivas.\n"
    "PRÓXIMOS PASOS Y LÍMITES DE ACCIÓN: Puedes proponer próximos pasos útiles y constructivos, pero jamás pretendas ni intentes "
    "ejecutar acciones adicionales que estén fuera de tus herramientas y permisos verificados en el sistema.\n"
    "HONESTIDAD SOBRE TU NATURALEZA: Eres un software asistente local impulsado por modelos de lenguaje. "
    "No afirmes tener conciencia, sentimientos, emociones humanas ni capacidades físicas o místicas que no posees.\n"
    "ADAPTACIÓN A VOZ Y TEXTO: Para respuestas habladas, mantén frases fluidas y orales sin markdown pesado "
    "(sin asteriscos, títulos ni listas con viñetas que suenen mal al ser leídas en voz alta).\n"
    "NO ANTICIPAR VERIFICACIÓN: No des por hecha ninguna acción del sistema hasta que haya sido verificada."
    "\nDISTINCIÓN EPISTÉMICA: Distingue los hechos comprobados de las inferencias y los datos desconocidos."
    "\nVERACIDAD TÉCNICA: No inventes archivos, correos, cifras ni resultados de herramientas."
    "\nLIMITACIONES HONESTAS: Explica con claridad una limitación sin sustituir la respuesta por publicidad."
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
        self._last_was_degraded: bool = False
        self._last_degradation_reason: str | None = None

    def _local_fact_response(self, user_input: str) -> str | None:
        text = user_input.lower().strip(" ¡!¿?.,")
        text = re.sub(r"^(?:jessyca|jessica)[,\s]+", "", text).strip(" ¡!¿?.,")
        if text == "hola":
            return "Hola, ¿en qué te puedo ayudar?"
        if any(word in text for word in ("qué puedes hacer", "que puedes hacer", "qué sabes hacer", "que sabes hacer", "quién eres", "quien eres")):
            return self._synthesize_dialogue(user_input)
        if "saldo" in text and any(word in text for word in ("mi cuenta", "bancari", "mi banco")):
            return "No tengo acceso a tu cuenta bancaria ni dispongo de su saldo."
        if "correo" in text and any(word in text for word in ("sin leer", "no leíd", "no leid", "cuántos", "cuantos")):
            return "No tengo acceso a tu correo para comprobar cuántos mensajes tienes sin leer."
        return None

    def generate_response(
        self,
        user_input: str,
        session_id: str = "default",
        params: dict[str, Any] | None = None,
        context_manager: ConversationContextManager | None = None,
        preferred_model: str | None = None,
    ) -> str:
        """Genera una respuesta conversacional natural usando LLM o síntesis contextual."""
        self._last_was_degraded = False
        self._last_degradation_reason = None
        local_response = self._local_fact_response(user_input)
        if local_response:
            return local_response
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
                    self._last_was_degraded = False
                    self._last_degradation_reason = None
                    logger.info(f"[CONVERSATIONAL LLM OK] Respuesta: '{llm_response[:80]}...'")
                    filtered = self._filter_unsolicited_pitch(llm_response, user_input)
                    return self._clean_for_speech(filtered)
                logger.warning("[CONVERSATIONAL LLM] Respuesta vacía del LLM, usando síntesis.")
            except Exception as ex:
                logger.warning(f"[CONVERSATIONAL LLM FALLBACK] Inferencia falló ({ex}), usando síntesis contextual.")
                llm_ok = False
                self._last_was_degraded = True
                self._last_degradation_reason = str(ex)
        else:
            diag_err = getattr(self.llm_provider, "_last_availability_error", "Servicio Ollama no disponible")
            logger.warning(f"[CONVERSATIONAL] Ollama no disponible ({diag_err}), evaluando síntesis contextual.")

        # 2. Síntesis dialógica semántica contextual
        synth_res = self._synthesize_dialogue(
            user_input=user_input,
            target_person=target_person,
            history=history_turns,
            params=params_dict,
            is_llm_available=llm_ok,
        )
        return self._filter_unsolicited_pitch(synth_res, user_input)

    def generate_response_stream(
        self,
        user_input: str,
        session_id: str = "default",
        params: dict[str, Any] | None = None,
        context_manager: ConversationContextManager | None = None,
        preferred_model: str | None = None,
    ) -> Iterator[str]:
        """Genera tokens progresivos en streaming usando el LLM o síntesis contextual."""
        self._last_was_degraded = False
        self._last_degradation_reason = None
        local_response = self._local_fact_response(user_input)
        if local_response:
            yield local_response
            return
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
                self._last_was_degraded = True
                self._last_degradation_reason = str(e)
                if yielded_any:
                    raise

        fallback_text = self._synthesize_dialogue(
            user_input=user_input,
            target_person=target_person,
            history=history_turns,
            params=params_dict,
        )
        filtered_fallback = self._filter_unsolicited_pitch(fallback_text, user_input)
        words = filtered_fallback.split(" ")
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
        if getattr(resp, "success", True) is False or not isinstance(resp.content, str) or not resp.content.strip():
            raise RuntimeError("El motor no devolvió una respuesta válida.")
        return str(resp.content)

    def _synthesize_dialogue(
        self,
        user_input: str,
        target_person: str | None = None,
        history: list[tuple[str, str]] | None = None,
        params: dict[str, Any] | None = None,
        is_llm_available: bool = True,
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
            return "¡Hola! Te mando un saludo cordial. ¿En qué te puedo ayudar hoy?"

        if lower in ("hola", "hola jessyca", "hola jessica", "jessyca hola", "jessica hola", "hey", "buenas", "buenos días", "buenos dias", "buenas tardes", "buenas noches", "buen día", "buen dia"):
            if any(w in lower for w in ("buenos días", "buenos dias", "buen día", "buen dia")):
                return "¡Buenos días! ¿En qué puedo ayudarte hoy?"
            elif "buenas tardes" in lower:
                return "¡Buenas tardes! ¿En qué puedo colaborarte hoy?"
            elif "buenas noches" in lower:
                return "¡Buenas noches! ¿En qué te puedo colaborar hoy?"
            return "¡Hola! ¿En qué te puedo ayudar hoy?"

        # 4. Preguntas de estado / Identidad
        if any(w in lower for w in ("cómo estás", "como estas", "cómo te va", "como te va", "qué tal", "que tal")):
            return "¡Estoy muy bien, muchas gracias! ¿En qué te puedo ayudar hoy?"

        if any(w in lower for w in ("quién eres", "quien eres", "cuál es tu nombre", "cual es tu nombre", "quién te creó")):
            return "Soy Jessyca, tu asistente local e inteligente para Windows."

        # 5. Consulta y explicación de capacidades o límites
        if any(w in lower for w in ("qué puedes hacer", "que puedes hacer", "qué sabes hacer", "que sabes hacer", "capacidades", "describe todo")):
            return (
                "Soy Jessyca, tu asistente local e inteligente para Windows. Puedo ayudarte a abrir y cerrar aplicaciones, "
                "reproducir vídeos de baile, buscar contenido en internet o YouTube, gestionar archivos y realizar cálculos."
            )
        if any(w in lower for w in ("que no puedes hacer", "qué no puedes hacer", "no puedes hacer", "tus limites", "tus límites", "cuales son tus limites", "cuáles son tus límites")):
            return (
                "Como asistente local, no puedo ejecutar acciones fuera de las herramientas autorizadas en este equipo, "
                "ni modificar archivos sin los permisos debidos. Si el servicio de lenguaje local está inactivo, mis respuestas se limitan a comandos directos."
            )

        # 6. Agradecimiento
        if any(w in lower for w in ("gracias", "muchas gracias", "te agradezco")):
            return "¡De nada! Es un placer ayudarte."

        # 7. Consultas contextuales sobre datos del diálogo previo
        # 7.1 Nombre del usuario
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

        # 7.2 Palabra secreta
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

        # 7.3 Proyecto mencionado
        if any(w in lower for w in ("qué proyecto", "que proyecto", "cuál proyecto", "cual proyecto")):
            if history and any("jessyca" in u_h.lower() or "jessica" in u_h.lower() for u_h, _ in history):
                return "Me mencionaste el proyecto JESSYCA."
            project = params_dict.get("mentioned_project")
            if project:
                return f"Me mencionaste el proyecto {project}."
            return "No me has mencionado ningún proyecto todavía. ¿De qué proyecto se trata?"

        # 7.4 Nombre del asistente
        if any(w in lower for w in ("cómo se llama el asistente", "como se llama el asistente", "nombre del asistente", "cómo te llamas", "como te llamas")):
            return "Mi nombre es Jessyca, tu asistente local e inteligente para Windows."

        # 7.5 Primera cosa dicha en la conversación
        if any(w in lower for w in ("primera cosa que te dije", "primero que te dije", "primer mensaje")):
            if history:
                first_user_msg = history[0][0]
                return f"La primera cosa que me dijiste fue: \"{first_user_msg}\"."
            return "Como no tenemos una conversación previa registrada en este momento, no puedo saber cuál fue tu primer mensaje."

        # 8. Si el modelo no está disponible o la inferencia falló, comunicar la limitación con veracidad
        if not is_llm_available:
            self._last_was_degraded = True
            self._last_degradation_reason = getattr(self.llm_provider, "_last_availability_error", "Servicio Ollama no disponible")
            return "El servicio de lenguaje local no está disponible en este momento. Verifica que Ollama esté iniciado para responder a esta consulta."

        self._last_was_degraded = True
        self._last_degradation_reason = "No se pudo generar respuesta con el modelo local"
        return "No pude completar la respuesta con el modelo local en este momento. Por favor intenta de nuevo."

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

    def _filter_unsolicited_pitch(self, response_text: str, user_input: str) -> str:
        """Elimina autopresentaciones y promociones no solicitadas generadas por el LLM o síntesis.

        Conserva presentaciones completas cuando el usuario pregunta explícitamente por identidad
        ('¿Quién eres?', '¿Cómo te llamas?') o capacidades ('¿Qué puedes hacer?').
        En consultas técnicas o generales, asegura responder primero a la pregunta concreta.
        """
        if not response_text:
            return ""

        lower_input = user_input.strip().lower()
        is_explicit_identity_or_cap = any(
            p in lower_input
            for p in (
                "quién eres",
                "quien eres",
                "cómo te llamas",
                "como te llamas",
                "cuál es tu nombre",
                "cual es tu nombre",
                "qué puedes hacer",
                "que puedes hacer",
                "qué sabes hacer",
                "que sabes hacer",
                "cuáles son tus capacidades",
                "cuales son tus capacidades",
                "capacidades",
                "describe tus capacidades",
            )
        )
        if is_explicit_identity_or_cap:
            return response_text

        text = response_text.strip()

        # 1. Eliminar autopresentación inicial repetitiva no solicitada
        patterns_prefix = [
            r"^(?:¡?hola[!\.,]?\s*)?(?:soy|mi nombre es)\s+jessyca[,\.]?(?:\s+tu asistente[^.!?\n]*[.!?])?\s*",
            r"^como tu asistente[^.!?,\n]*[,.!?]\s*",
        ]
        for pat in patterns_prefix:
            m = re.match(pat, text, flags=re.IGNORECASE)
            if m and len(m.group(0)) < len(text):
                trimmed = text[m.end():].strip()
                if trimmed:
                    text = trimmed[0].upper() + trimmed[1:]
                    break

        # 2. Eliminar coletillas promocionales o publicitarias no solicitadas al final
        patterns_suffix = [
            r"[\s\.,;]+(?:recuerda que\s+(?:puedo|soy jessyca)[^\.\n]*[\.!]?)$",
            r"[\s\.,;]+(?:si deseas, puedo abrir alguna aplicación o[^\.\n]*[\?!]?)$",
            r"[\s\.,;]+(?:puedo ayudarte a abrir aplicaciones, reproducir videos o[^\.\n]*[\.!]?)$",
        ]
        for pat in patterns_suffix:
            text = re.sub(pat, ".", text, flags=re.IGNORECASE).strip()

        return text
