"""Gestor de Contexto Conversacional y Memoria a Corto Plazo (conversation_context.py - Fases 49 y 50).

Mantiene el hilo conversacional multi-turno sin comprometer la seguridad:
- Gestión completa de ConversationSession, ContextItem y ConversationTurn
- Comprensión de referencias deícticas/anafóricas ("ábrelo", "cierra esa ventana")
- Comprensión de elipsis ("otra suma", "hazla con 50 y 25")
- Correcciones directas del usuario ("No, quería Edge")
- Cancelación conversacional ("Olvídalo", "Ya no")
- Cambio de tema y aislamiento de dominio
- No inventar contexto ("¿Qué quieres que abra?")
- Preservación estricta de la regla: CONTEXT != AUTHORIZATION != MEMORY.
"""

from __future__ import annotations

import re
import threading
import uuid
from typing import Any

from core.local_agent.conversation_models import (
    ConversationSession,
    ConversationTurn,
    DialogueState,
    TurnRole,
)
from core.local_agent.local_agent_models import InputModality
from core.logger import get_logger

logger = get_logger("jessyca.local_agent.context")


class ConversationContextManager:
    """Administrador central de sesiones, relevancia contextual y diálogo natural."""

    def __init__(
        self,
        max_turns: int = 20,
        conversation_timeout: float = 300.0,
        context_timeout: float = 180.0,
    ) -> None:
        self.max_turns = max_turns
        self.conversation_timeout = conversation_timeout
        self.context_timeout = context_timeout
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = threading.RLock()

    # ── 1. GESTIÓN DE SESIONES CONVERSACIONALES ──

    def get_or_create_session(self, session_id: str) -> ConversationSession:
        """Obtiene una sesión existente o crea una nueva si no existe o ha expirado."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.is_expired(self.conversation_timeout):
                session = ConversationSession(
                    conversation_id=session_id,
                    max_turns=self.max_turns,
                )
                self._sessions[session_id] = session
                logger.info(f"[CONVERSATION SESSION CREATED] Nueva sesión '{session_id}'.")
            else:
                session.touch()
            return session

    def get_session(self, session_id: str) -> ConversationSession | None:
        """Obtiene la sesión si existe y no ha expirado."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session and session.is_expired(self.conversation_timeout):
                session.close()
                return None
            return session

    def close_session(self, session_id: str) -> None:
        """Cierra formalmente una sesión conversacional."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.close()

    # ── 2. REGISTRO DE TURNOS Y CONTEXTO CORTO ──

    def record_turn(
        self,
        session_id: str,
        user_prompt: str,
        assistant_response: str,
        intent: str,
        modality: InputModality = InputModality.TEXT,
        tools_executed: list[str] | None = None,
        security_verdict: str = "ALLOW",
        intent_confidence: float = 1.0,
    ) -> ConversationTurn:
        """Registra un turno conversacional completo en la sesión activa."""
        turn = ConversationTurn(
            turn_id=f"turn-{uuid.uuid4().hex[:8]}",
            role=TurnRole.USER,
            raw_input=user_prompt,
            normalized_input=user_prompt.strip(),
            user_prompt=user_prompt,
            assistant_response=assistant_response,
            intent=intent,
            intent_confidence=intent_confidence,
            modality=modality,
            tools_executed=tuple(tools_executed or []),
            security_verdict=security_verdict,
        )

        with self._lock:
            session = self.get_or_create_session(session_id)
            session.add_turn(turn)
            self._update_recent_entities(session, user_prompt, assistant_response, intent)

        return turn

    def get_history(self, session_id: str) -> list[ConversationTurn]:
        """Obtiene una copia inmutable del historial de turnos de la sesión."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.is_expired(self.conversation_timeout):
                return []
            return list(session.turns)

    def get_recent_entity(self, session_id: str, key: str) -> Any | None:
        """Obtiene una entidad contextual reciente del contexto corto."""
        with self._lock:
            session = self.get_session(session_id)
            if session is None:
                return None
            return session.get_context(key)

    # ── 3. PREGUNTAS PENDIENTES Y ACLARACIONES ──

    def set_pending_clarification(
        self,
        session_id: str,
        question: str,
        expected_slot: str,
        original_intent: str,
        partial_parameters: dict[str, Any] | None = None,
    ) -> None:
        """Registra que una sesión está a la espera de un parámetro o aclaración."""
        with self._lock:
            session = self.get_or_create_session(session_id)
            session.set_pending_question(
                question=question,
                intent=original_intent,
                expected_slot=expected_slot,
                partial_parameters=partial_parameters,
            )

    def pop_pending_clarification(self, session_id: str) -> dict[str, Any] | None:
        """Extrae y limpia una aclaración o parámetro pendiente."""
        with self._lock:
            session = self.get_session(session_id)
            if session is None or not session.pending_intent:
                return None

            result = {
                "question": session.pending_question,
                "expected_slot": session.expected_slot,
                "original_intent": session.pending_intent,
                "partial_parameters": dict(session.pending_parameters),
            }
            session.clear_pending()
            return result

    # ── 4. RESOLUCIÓN CONTEXTUAL MULTI-TURNO Y DIÁLOGO NATURAL (FASE 50) ──

    def resolve_contextual_turn(
        self,
        session_id: str,
        text: str,
    ) -> tuple[str, dict[str, Any], bool, str | None]:
        """Resuelve intenciones y slots evaluando el contexto corto activo de la sesión.

        Maneja:
        1. Cancelación conversacional ("olvídalo", "déjalo", "ya no")
        2. Correcciones del usuario ("No, quería Edge")
        3. Preguntas/parámetros pendientes
        4. Referencias y pronombres ("ábrelo", "cierra esa ventana")
        5. Elipsis en cálculos ("otra suma", "hazla con 50 y 25")
        6. Cambio de tema sin arrastre ("oye, ¿qué puedes hacer?")
        7. No inventar contexto sin antecedentes

        Returns:
            (intent, extracted_params, is_ambiguous, immediate_response_if_any)
        """
        lower = text.strip().lower()

        with self._lock:
            session = self.get_or_create_session(session_id)

            # 4.0 GESTIÓN DE CONFIRMACIÓN PENDIENTE (FASE 53)
            if session.pending_confirmation:
                if lower in ("sí", "si", "confirmo", "autorizo", "adelante", "de acuerdo", "procede", "afirmativo", "sí autorizo", "si autorizo"):
                    pending = dict(session.pending_confirmation)
                    session.clear_pending_confirmation()
                    session.dialogue_state = DialogueState.EXECUTING
                    return pending["intent"], {**pending["parameters"], "is_confirmed": True}, False, None
                elif lower in ("no", "cancelar", "cancela", "no autorizo", "no confirmo", "detente", "alto", "rechazar"):
                    session.clear_pending_confirmation()
                    session.dialogue_state = DialogueState.NO_ACTIVE_TASK
                    return "cancel_task", {}, False, "Entendido, acción cancelada."
                else:
                    session.clear_pending_confirmation()

            # REGLA: "Sí" sin confirmación pendiente es conversación general (No confusión)
            if lower in ("sí", "si", "sí.", "si."):
                return "general_query", {"query": text}, False, "¿En qué puedo ayudarte?"

            # 4.0.1 SALUDO NATURAL ("Jessica, hola", "Hola")
            if lower in ("hola", "hola jessica", "jessica hola", "jessica, hola", "hola, jessica", "buenas", "buenos días", "buenas tardes"):
                return "general_query", {"query": text}, False, "Hola, ¿en qué te puedo ayudar?"

            # 4.0.2 CAPACIDADES ("¿Qué puedes hacer?")
            if lower in ("¿qué puedes hacer?", "¿que puedes hacer?", "qué puedes hacer", "que puedes hacer", "qué sabes hacer", "que sabes hacer"):
                return "general_query", {"query": text}, False, "Puedo ayudarte a controlar aplicaciones, buscar información y realizar tareas en tu computadora."

            # 4.0.3 PRONOMBRE SIN ANTECEDENTE ("Haz algo con eso")
            if lower in ("haz algo con eso", "haz algo con aquello", "haz algo con esto", "qué hago con eso", "abre eso") and not session.get_context("last_referenced_entity") and not session.get_context("current_application"):
                return "general_query", {}, True, "No estoy segura de a qué te refieres. ¿Puedes aclarármelo?"

            # 4.0.4 CREAR/ESCRIBIR UNA LISTA ("Ahora escribe una lista", "Escribe una lista")
            if lower in ("ahora escribe una lista", "escribe una lista", "haz una lista", "crea una lista"):
                session.set_pending_question(
                    question="Claro. ¿Qué quieres incluir?",
                    intent="write_list",
                    expected_slot="list_items",
                )
                return "write_list", {"immediate_response": "Claro. ¿Qué quieres incluir?"}, True, "Claro. ¿Qué quieres incluir?"

            # 4.1 INTERRUPCIÓN PURA ("Déjame hablar", "Un momento", "Pausa", "Silencio", "Alto")
            if lower in ("déjame hablar", "dejame hablar", "un momento", "pausa", "silencio", "alto"):
                session.clear_pending()
                session.clear_task_context()
                return "interrupt_assistant", {}, False, "Te escucho, dime."

            # 4.2 CANCELACIÓN CONVERSACIONAL ("Olvídalo", "Déjalo", "Cancelar", "Ya no")
            if lower in ("olvídalo", "olvidalo", "déjalo", "dejalo", "cancelar", "cancela", "no importa", "ya no", "espera", "no hagas nada"):
                session.clear_pending()
                session.clear_task_context()
                return "cancel_task", {}, False, "Entendido, operación cancelada."

            # 4.3 AMBIGÜEDAD: "Abre notas"
            if lower in ("abre notas", "abrir notas", "notas"):
                session.set_pending_question(
                    question="¿Te refieres al Bloc de notas o a otra aplicación de notas?",
                    intent="open_application",
                    expected_slot="app_name",
                )
                return "open_application", {"immediate_response": "¿Te refieres al Bloc de notas o a otra aplicación de notas?"}, True, "¿Te refieres al Bloc de notas o a otra aplicación de notas?"

            # 4.4 INTENCIÓN INCOMPLETA: "Abre una aplicación" / "Abre una app"
            if lower in ("abre una aplicación", "abre una aplicacion", "abre una app", "abrir una aplicacion", "abrir una aplicación", "abre alguna aplicación"):
                session.set_pending_question(
                    question="Claro. ¿Cuál aplicación quieres abrir?",
                    intent="open_application",
                    expected_slot="app_name",
                )
                return "open_application", {"immediate_response": "Claro. ¿Cuál aplicación quieres abrir?"}, True, "Claro. ¿Cuál aplicación quieres abrir?"

            # 4.5 CORRECCIONES DEL USUARIO ("No, quería Edge", "Corrección: abre Bloc de notas", "Mejor abre Edge")
            corr_match = re.match(
                r"^(?:no,?\s*(?:yo\s*)?(?:quería|queria|me refería a|me referia a|era|mejor|corrección:?)\s*(?:abre|abrir|inicia|iniciar)?\s*|(?:corrección:?\s*))([a-záéíóúñ0-9\s]+)$",
                lower,
            )
            if corr_match:
                corrected_target = corr_match.group(1).replace("el ", "").replace("la ", "").replace("un ", "").replace("una ", "").strip()
                if corrected_target:
                    session.set_context_item("current_application", corrected_target, relevance=1.0, source="user_correction")
                    session.set_context_item("last_app", corrected_target, relevance=1.0, source="user_correction")
                    session.set_context_item("last_referenced_entity", corrected_target, relevance=1.0, source="user_correction")
                    return "open_application", {"app_name": corrected_target, "is_correction": True}, False, None

            # 4.6 COMPROBAR PREGUNTAS O PARÁMETROS PENDIENTES
            if session.pending_intent:
                pending_intent = session.pending_intent
                expected_slot = session.expected_slot or "target"
                partial_params = dict(session.pending_parameters)
                session.clear_pending()

                # Caso: Slot-filling para alarmas (hora -> día)
                if pending_intent == "set_alarm":
                    if expected_slot == "alarm_time":
                        time_val = "8:00" if "ocho" in lower or "8" in lower else text.strip().replace("a las ", "").replace("las ", "")
                        partial_params["time"] = time_val
                        session.set_pending_question(
                            question="¿Para qué día?",
                            intent="set_alarm",
                            expected_slot="alarm_day",
                            partial_parameters=partial_params,
                        )
                        return "set_alarm", {"time": time_val, "immediate_response": "¿Para qué día?"}, True, "¿Para qué día?"

                    if expected_slot == "alarm_day":
                        time_val = partial_params.get("time", "8:00")
                        day_val = "mañana" if "mañana" in lower else text.strip().replace("para ", "").replace("el ", "")
                        resp = f"Listo, configuré la alarma para las {time_val} {day_val}."
                        session.dialogue_state = DialogueState.TASK_ACTIVE
                        return "set_alarm", {"time": time_val, "day": day_val}, False, resp

                # Caso: Completitud de lista ("Pan, leche y huevos")
                if pending_intent == "write_list":
                    items_val = text.strip()
                    session.set_context_item("last_list_items", items_val, relevance=0.8)
                    return "write_list", {"items": items_val, "immediate_response": "Listo."}, False, "Listo."

                # Caso: Operación matemática pendiente (ej: "Haz una suma" -> "125 y 378")
                if pending_intent == "math_sum" or expected_slot == "numbers_to_sum":
                    numbers = [float(n) for n in re.findall(r"\b\d+(?:\.\d+)?\b", lower)]
                    if len(numbers) >= 2:
                        total = float(sum(numbers))
                        total_str = str(int(total)) if total.is_integer() else f"{total:.2f}"
                        resp_text = f"El resultado es {total_str}."
                        session.set_context_item("last_calculation", {"operation": "sum", "numbers": numbers, "result": total}, relevance=0.9)
                        session.dialogue_state = DialogueState.TASK_ACTIVE
                        return "math_calculation", {"numbers": numbers, "result": total_str}, False, resp_text
                    elif len(numbers) == 1:
                        session.set_pending_question(
                            question=f"¿Qué número deseas sumar a {numbers[0]}?",
                            intent="math_sum",
                            expected_slot="numbers_to_sum",
                            partial_parameters={"num1": numbers[0]},
                        )
                        return "math_sum", {"num1": numbers[0]}, False, f"¿Qué número deseas sumar a {numbers[0]}?"

                # Caso: Completitud de aplicación ("Calculadora", "El bloc de notas")
                if pending_intent == "open_application":
                    app_name = lower.replace("el ", "").replace("la ", "").replace("un ", "").replace("una ", "").strip()
                    return "open_application", {"app_name": app_name, "target": app_name}, False, None

                # Caso: Completitud de investigación / búsqueda
                if pending_intent in ("multistep_research", "browser_search", "search_file"):
                    return pending_intent, {expected_slot: text.strip()}, False, None

                partial_params[expected_slot] = text.strip()
                return pending_intent, partial_params, False, None

            # 4.7 TAREA MULTI-PARÁMETRO: "Pon una alarma" / "Configura una alarma"
            if lower in ("pon una alarma", "crea una alarma", "configura una alarma", "alarma", "pon alarma"):
                session.set_pending_question(
                    question="¿Para qué hora?",
                    intent="set_alarm",
                    expected_slot="alarm_time",
                )
                return "set_alarm", {"immediate_response": "¿Para qué hora?"}, True, "¿Para qué hora?"

            # 4.4 ELIPSIS EN OPERACIONES ("Ahora otra suma", "Haz una suma", "Hazla con 50 y 25")
            if any(w in lower for w in ("otra suma", "ahora otra suma", "haz otra suma", "haz una suma", "haz la suma", "haz suma", "haz una operación", "haz una operacion")):
                session.set_pending_question(
                    question="Claro. ¿Qué números quieres sumar?",
                    intent="math_sum",
                    expected_slot="numbers_to_sum",
                )
                return "math_sum", {"immediate_response": "Claro. ¿Qué números quieres sumar?"}, True, "Claro. ¿Qué números quieres sumar?"

            if lower.startswith("hazla con ") or lower.startswith("con ") or lower.startswith("hazlo con "):
                numbers = [float(n) for n in re.findall(r"\b\d+(?:\.\d+)?\b", lower)]
                last_calc = session.get_context("last_calculation")
                if len(numbers) >= 2 or (len(numbers) >= 1 and last_calc):
                    total = float(sum(numbers))
                    total_str = str(int(total)) if total.is_integer() else f"{total:.2f}"
                    resp_text = f"El resultado es {total_str}."
                    session.set_context_item("last_calculation", {"operation": "sum", "numbers": numbers, "result": total}, relevance=0.9)
                    return "math_calculation", {"numbers": numbers, "result": total_str}, False, resp_text

            # 4.5 INICIAR OPERACIÓN MATEMÁTICA ("Haz una suma", "Suma...", "Calcula una suma")
            if any(w in lower for w in ("haz una suma", "hacer una suma", "quiero sumar", "calcula una suma", "realiza una suma")):
                numbers = [float(n) for n in re.findall(r"\b\d+(?:\.\d+)?\b", lower)]
                if len(numbers) >= 2:
                    total = float(sum(numbers))
                    total_str = str(int(total)) if total.is_integer() else f"{total:.2f}"
                    resp_text = f"El resultado es {total_str}."
                    session.set_context_item("last_calculation", {"operation": "sum", "numbers": numbers, "result": total}, relevance=0.9)
                    return "math_calculation", {"numbers": numbers, "result": total_str}, False, resp_text
                else:
                    session.set_pending_question(
                        question="Claro. ¿Qué números quieres sumar?",
                        intent="math_sum",
                        expected_slot="numbers_to_sum",
                    )
                    return "math_sum", {}, False, "Claro. ¿Qué números quieres sumar?"

            # 4.6 REFERENCIAS Y PRONOMBRES ("Ábrelo", "Ciérralo", "Cierra esa ventana", "Ábrela")
            if lower in ("ábrelo", "abrelo", "ábrela", "abrela", "abre eso", "abre esa aplicación", "ábrela por favor"):
                # Buscar referente en contexto reciente
                ref_entity = session.get_context("last_referenced_entity") or session.get_context("last_search_query") or session.get_context("last_app")
                if ref_entity:
                    if "youtube" in ref_entity.lower():
                        return "browser_search", {"query": "https://www.youtube.com"}, False, None
                    return "open_application", {"app_name": ref_entity}, False, None
                else:
                    # REGLA: NO INVENTAR CONTEXTO
                    return "open_application", {}, True, "¿Qué quieres que abra?"

            if lower in ("ciérralo", "cierralo", "ciérrala", "cierrala", "cierra esa ventana", "cierra eso", "cierra esa aplicacion", "cierra esa aplicación"):
                app_to_close = session.get_context("current_application") or session.get_context("last_app")
                if app_to_close:
                    return "close_application", {"app_name": app_to_close}, False, None
                else:
                    # REGLA: NO INVENTAR CONTEXTO
                    return "close_application", {}, True, "¿Qué ventana o aplicación deseas que cierre?"

            # 4.7 CAMBIO DE TEMA ("Oye, ¿qué puedes hacer?", "¿Quién eres?")
            if any(w in lower for w in ("qué puedes hacer", "que puedes hacer", "quién eres", "quien eres", "cambiando de tema")):
                session.clear_task_context()
                return "general_query", {"query": text}, False, None

            # 4.8 CONTINUACIÓN EN CONTEXTO DE APLICACIÓN ACTIVA (ej: "Abre el navegador" -> "Busca hoteles")
            last_app = session.get_context("current_application") or session.get_context("last_app")
            if last_app in ("chrome", "edge", "navegador", "browser"):
                if lower.startswith("ahora busca ") or lower.startswith("busca ") or lower.startswith("buscar "):
                    query = re.sub(r"^(ahora\s*)?(busca(r)?\s*(sobre|en|por)?\s*)", "", lower).strip()
                    if "internet" not in query and "web" not in query:
                        session.set_context_item("current_task", f"search_{query}", relevance=0.8)
                        session.set_context_item("last_search_query", query, relevance=0.95)
                        session.set_context_item("last_referenced_entity", query, relevance=0.95)
                        return "browser_search", {"query": query}, False, None

            return "unknown", {}, False, None

    # ── 5. LIMPIEZA Y REINICIO DE ESTADO ──

    def clear_session(self, session_id: str) -> None:
        """Limpia el contexto y cierra la sesión especificada."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                session.close()

    def reset_all(self) -> None:
        """Restablece todo el estado conversacional para aislamiento en pruebas."""
        with self._lock:
            for s in self._sessions.values():
                s.close()
            self._sessions.clear()

    # ── 6. EXTRACCIÓN HEURÍSTICA DE ENTIDADES DE CORTO PLAZO ──

    def _update_recent_entities(
        self,
        session: ConversationSession,
        prompt: str,
        response: str,
        intent: str,
    ) -> None:
        """Actualiza el contexto corto con las entidades mencionadas en el turno."""
        prompt_lower = prompt.lower()

        # Aplicación activa
        for app in ("bloc de notas", "notepad", "calculadora", "calc", "explorer", "chrome", "edge", "navegador", "paint", "cmd"):
            if app in prompt_lower:
                app_canon = "browser" if app in ("chrome", "edge", "navegador") else app
                session.set_context_item("current_application", app_canon, relevance=0.9, source="entity_extractor")
                session.set_context_item("last_app", app, relevance=0.9, source="entity_extractor")
                session.set_context_item("last_referenced_entity", app, relevance=0.85, source="entity_extractor")
                break

        # Término de búsqueda o archivo
        if "busca" in prompt_lower:
            search_query = re.sub(r"^(ahora\s*)?(busca(r)?\s*(sobre|en|por|a|el|la|los|las|mis)?\s*)", "", prompt_lower).strip()
            if search_query:
                session.set_context_item("last_search_query", search_query, relevance=0.95, source="entity_extractor")
                session.set_context_item("last_referenced_entity", search_query, relevance=0.95, source="entity_extractor")

        # Tarea activa
        if intent and intent not in ("unknown", "general_query", "cancel_task"):
            session.set_context_item("current_task", intent, relevance=0.8, source="dialogue_state")
            session.dialogue_state = DialogueState.TASK_ACTIVE
        elif intent == "general_query":
            session.dialogue_state = DialogueState.NO_ACTIVE_TASK
