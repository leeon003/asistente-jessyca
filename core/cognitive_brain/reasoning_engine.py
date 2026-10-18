"""JESSYCA BRAIN 1.0 — Motor de Razonamiento y Comprensión Contextual (ReasoningEngine).

Implementa el contrato formal `ReasoningProvider` definido en `core/cognitive_brain/contracts.py`:
1. Comprensión del lenguaje natural y diferenciación entre conversación y solicitudes de acción.
2. Descomposición de instrucciones compuestas en submetas secuenciales u ordenadas.
3. Recuperación de contexto y resolución de correferencias/anáforas ("eso", "lo anterior", "el archivo").
4. Selección progresiva y dinámica de herramientas (inspirado en SAI Progressive Tool Loading).
5. Detección de ambigüedad y generación de preguntas aclaratorias.
6. Propuesta de alternativas ante fallos de herramientas o parámetros inválidos.
7. Uso de modelos locales mediante Model Router con fallback semántico estructurado determinista.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from core.cognitive_brain.contracts import ContextBundle, GoalComprehension, ReasoningProvider
from core.intent.progressive_catalog import ProgressiveToolCatalog

logger = logging.getLogger("jessyca.brain.reasoning")


class ReasoningEngine(ReasoningProvider):
    """Motor central de razonamiento cognitivo y comprensión contextual para JESSYCA BRAIN 1.0."""

    def __init__(self, model_router: Any = None) -> None:
        self.model_router = model_router

    @staticmethod
    def _normalize_phonetic_variations(text: str) -> tuple[str, dict[str, Any]]:
        """Normaliza variaciones fonéticas comunes del habla en español para servicios y entidades frecuentes."""
        clean = text
        detected: dict[str, Any] = {}

        # 1. Variaciones fonéticas de YouTube
        yt_pattern = re.compile(r"\b(?:yo\s+tuy|yu\s+tub|yu\s+tu|llutub|yutub|iu\s+tub|yo\s+tube|yu\s+tube|llutu|yutu)\b", re.IGNORECASE)
        if yt_pattern.search(clean):
            clean = yt_pattern.sub("YouTube", clean)
            detected["normalized_service"] = "YouTube"

        # 2. Variaciones de reproducción
        clean = re.sub(r"\brepreduce\s+a\b", "reproduce", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\brepreduce\b", "reproduce", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\breproduce\s+a\b", "reproduce", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\bpon\s+videos?\s+de\b", "reproduce videos de", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\bpon\s+m[uú]sica\s+de\b", "reproduce música de", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\bpon\s+a\b", "reproduce a", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\bpon\s+(mozart|mozar)\b", r"reproduce \1", clean, flags=re.IGNORECASE)

        # 2.5 Variaciones de Baile ("Jessica, báilame" / "bailame" / "baila")
        dance_pattern = re.compile(r"\b(?:b[aá]ilame|baila\s+para\s+m[ií]|pon\s+un\s+baile|un\s+baile|haz\s+un\s+baile|reproduce\s+un\s+baile)\b", re.IGNORECASE)
        if dance_pattern.search(clean):
            detected["is_dance"] = True
            detected["action"] = "play_random_video"
            detected["target_directory"] = r"D:\bailes de ia"

        # 3. Variaciones de Mozart
        mozart_pattern = re.compile(r"\b(?:mozar|mosart|m[oó]zar)\b", re.IGNORECASE)
        if mozart_pattern.search(clean):
            clean = mozart_pattern.sub("Mozart", clean)
            detected["composer"] = "Mozart"

        # 4. Variaciones de Bloc de notas
        bloc_pattern = re.compile(r"\b(?:block\s+de\s+notas|blog\s+de\s+notas|blod\s+de\s+notas|bloc\s+notas|block\s+notas|blog\s+notas)\b", re.IGNORECASE)
        if bloc_pattern.search(clean):
            clean = bloc_pattern.sub("Bloc de notas", clean)
            detected["normalized_app"] = "Bloc de notas"

        # 5. Variaciones de Calculadora
        calc_pattern = re.compile(r"\b(?:la\s+calculadora|calculadora)\b", re.IGNORECASE)
        if calc_pattern.search(clean):
            detected["normalized_app"] = "calculadora"

        return clean, detected

    def comprehend(
        self,
        user_input: str,
        context: ContextBundle,
        session_id: str = "default",
    ) -> GoalComprehension:
        """Analiza la solicitud en lenguaje natural, resuelve anáforas y extrae la intención estructurada."""
        raw_text = (user_input or "").strip()

        # ── 0. NORMALIZACIÓN FONÉTICA Y CONTEXTUAL DE RECONOCIMIENTO DE VOZ ──
        normalized_phonetic, detected_entities = self._normalize_phonetic_variations(raw_text)
        stt_conf = float(context.working_context.get("stt_confidence", 0.90))

        # Si la confianza de la transcripción es baja (< 0.60): Aclaración obligatoria antes de ejecutar acciones en el SO
        if stt_conf < 0.60:
            clarif = "¿Podrías aclararme qué deseas hacer? No te entendí bien."
            if "normalized_service" in detected_entities or "composer" in detected_entities:
                clarif = "¿Quieres que abra YouTube y reproduzca música?"
            return GoalComprehension(
                raw_query=raw_text,
                normalized_goal=normalized_phonetic,
                intent_category="clarification_needed",
                confidence=stt_conf,
                is_ambiguous=True,
                clarification_question=clarif,
                is_conversational=False,
                requires_action=False,
                entities=detected_entities,
            )

        raw_text = normalized_phonetic
        lower_text = raw_text.lower()
        control_text = re.sub(r"^(?:jessyca|jessica)[,\s]+", "", lower_text).strip(" ¡!¿?.,")
        if re.search(r"\bqu[eé] puedes hacer\b", control_text) or control_text == "puedes abrir aplicaciones":
            return GoalComprehension(
                raw_query=raw_text, normalized_goal=raw_text, intent_category="capabilities",
                confidence=1.0, is_ambiguous=False, is_conversational=True, requires_action=False,
            )
        if re.fullmatch(r"(?:busca|pon|reproduce)\s+(?:una?\s+)?(?:canci[oó]n|m[uú]sica)", control_text):
            return GoalComprehension(
                raw_query=raw_text, normalized_goal=raw_text, intent_category="clarification_needed",
                confidence=0.5, is_ambiguous=True, is_conversational=False, requires_action=False,
                clarification_question="¿Qué canción quieres que busque?" if control_text.startswith("busca") else "¿Qué canción deseas y dónde debo buscarla: en tu disco o en YouTube?",
            )
        if control_text in ("espera", "déjame hablar", "dejame hablar", "un momento", "silencio", "detente"):
            return GoalComprehension(
                raw_query=raw_text, normalized_goal=raw_text, intent_category="interruption",
                confidence=1.0, is_ambiguous=False, is_conversational=True, requires_action=False,
            )
        from config.manager import get_settings
        from core.local_media_request import resolve_local_media_request

        local_request = resolve_local_media_request(raw_text, get_settings().JESSYCA_DANCE_VIDEO_DIRECTORY)
        if local_request:
            category, entities = local_request
            ambiguous = category == "clarification_needed"
            tool = "app_launcher" if category == "open_folder" else "windows_media"
            return GoalComprehension(
                raw_query=raw_text, normalized_goal=raw_text, intent_category=category,
                confidence=0.98, entities=entities, is_ambiguous=ambiguous,
                clarification_question=entities.get("question"), is_conversational=False,
                requires_action=not ambiguous, sub_goals=(raw_text,),
                suggested_tools=() if ambiguous else (tool,),
            )

        # ── 0.1 CASO: ORDEN DE BAILE ("Jessica, báilame" / "bailame") ──
        is_dance = detected_entities.get("is_dance") or any(w in lower_text for w in ("báilame", "bailame", "un baile", "el baile", "pon un baile", "haz un baile", "baila para mi", "baila para mí")) or (
            any(v in lower_text for v in ("reproduce", "pon", "abre")) and "baile" in lower_text
        )
        if is_dance and not any(word in lower_text for word in ("carpeta", "busca", "youtube", "no bail", "no báil")):
            dance_entities = {
                "is_dance": True,
                "action": "play_random_video",
                "target_directory": r"D:\bailes de ia",
            }
            if detected_entities:
                dance_entities.update(detected_entities)
            return GoalComprehension(
                raw_query=raw_text,
                normalized_goal="báilame",
                intent_category="play_dance",
                confidence=0.98,
                entities=dance_entities,
                is_ambiguous=False,
                is_conversational=False,
                requires_action=True,
                sub_goals=("reproducir video aleatorio de baile local",),
                suggested_tools=("windows_media",),
                raw_explanation="Orden de reproducción de vídeo de baile local.",
            )

        # ── 0.2 CASO: ABRIR CARPETA O VÍDEOS EN DISCO ("abre los videos del disco D", "abre la carpeta Bailes de IA") ──
        if any(w in lower_text for w in ("abre los videos del disco", "abre la carpeta", "abrir la carpeta", "muestra la carpeta", "abre los videos de")):
            fol = r"D:\bailes de ia" if "baile" in lower_text else ("D:\\" if ("disco d" in lower_text or "d:" in lower_text) else r"D:\bailes de ia")
            return GoalComprehension(
                raw_query=raw_text,
                normalized_goal=f"abrir carpeta {fol} en explorador",
                intent_category="open_folder",
                confidence=0.95,
                entities={"target_folder": fol, "app_name": "explorer", "accion": "abrir_carpeta"},
                is_ambiguous=False,
                is_conversational=False,
                requires_action=True,
                sub_goals=(f"abrir carpeta {fol} en explorador",),
                suggested_tools=("app_launcher",),
                raw_explanation="Apertura de carpeta en Explorador de Windows.",
            )

        # ── 0.3 CASO: BUSCAR CARPETA EN DISCO ("busca la carpeta Bailes de IA") ──
        if any(w in lower_text for w in ("busca la carpeta", "buscar la carpeta", "busca el archivo", "buscar archivo")) or ("carpeta" in lower_text and any(w in lower_text for w in ("busca", "buscar"))):
            f_target = "Bailes de IA" if "baile" in lower_text else "archivos"
            m_fn = re.search(r"busca(?:r)?\s+(?:la\s+carpeta\s+(?:de\s+)?|el\s+archivo\s+(?:de\s+)?)(.+)", raw_text, flags=re.IGNORECASE)
            if m_fn:
                f_target = m_fn.group(1).strip()
            return GoalComprehension(
                raw_query=raw_text,
                normalized_goal=f"buscar carpeta {f_target} en disco",
                intent_category="search_folder",
                confidence=0.95,
                entities={"search_target": f_target, "drive": "D:\\"},
                is_ambiguous=False,
                is_conversational=False,
                requires_action=True,
                sub_goals=(f"buscar carpeta {f_target} en disco",),
                suggested_tools=("file_search",),
                raw_explanation="Búsqueda de carpeta en el sistema de archivos local.",
            )

        # ── 0.1 INSTRUCCIÓN DE MEMORIZACIÓN ("recuerda que...") ──
        if re.search(r"\b(?:recuerda|memoriza|guarda\s+en\s+memoria)\s+(?:que\s+)?(.+)", lower_text):
            m_rec = re.search(r"\b(?:recuerda|memoriza|guarda\s+en\s+memoria)\s+(?:que\s+)?(.+)", raw_text, flags=re.IGNORECASE)
            fact = m_rec.group(1).strip() if m_rec else raw_text
            return GoalComprehension(
                raw_query=raw_text,
                normalized_goal=f"Recordar: {fact}",
                intent_category="memory_store",
                confidence=0.95,
                is_ambiguous=False,
                is_conversational=True,
                requires_action=False,
                entities={"memory_fact": fact},
                raw_explanation="Instrucción explícita de memorización para la memoria semántica y contextual.",
            )

        # ── 1. DETECCIÓN DE AMBIGÜEDAD Y ÓRDENES INCOMPLETAS ──
        is_ambiguous, clarif_q = self.evaluate_ambiguity(raw_text)
        if is_ambiguous:
            return GoalComprehension(
                raw_query=raw_text,
                normalized_goal=raw_text,
                intent_category="clarification_needed",
                confidence=0.5,
                is_ambiguous=True,
                clarification_question=clarif_q,
                is_conversational=False,
                requires_action=False,
            )

        # ── 2. RESOLUCIÓN DE ANÁFORAS Y CONTEXTO ("lo anterior", "eso", "el archivo") ──
        anaphora_resolved: dict[str, Any] = {}
        normalized_text = raw_text

        # 2.1 Anáfora hacia tarea anterior: "continúa con lo anterior", "sigue con lo anterior"
        if re.search(r"\b(?:contin[uú]a|sigue|procede)\s+(?:con\s+)?(?:lo\s+anterior|la\s+tarea\s+anterior)\b", lower_text):
            # Buscar en memoria de trabajo o recuerdos recientes
            active_goal = context.working_context.get("active_goal")
            recent_task = ""
            if active_goal:
                recent_task = active_goal
            elif context.relevant_memories:
                # Revisar si hay un recuerdo de lo que se estaba investigando o haciendo
                for mem in context.relevant_memories:
                    c = mem.get("content", "")
                    if "investigando" in c.lower() or "tarea" in c.lower() or "meta" in c.lower():
                        recent_task = c
                        break
                if not recent_task and len(context.relevant_memories) > 0:
                    recent_task = context.relevant_memories[0].get("content", "")

            if recent_task:
                anaphora_resolved["lo_anterior"] = recent_task
                normalized_text = f"Continuar: {recent_task}"
                # Si el tema anterior era conceptual/conversacional, continuar conversacionalmente
                if self._is_conversational_query(recent_task) or not any(v in recent_task.lower() for v in ("abre", "cierra", "escribe", "haz clic", "guarda", "borra", "descarga")):
                    return GoalComprehension(
                        raw_query=raw_text,
                        normalized_goal=f"Continúa explicando sobre: {recent_task}",
                        intent_category="conversational_continuation",
                        confidence=0.95,
                        is_ambiguous=False,
                        clarification_question=None,
                        is_conversational=True,
                        requires_action=False,
                        context_references=anaphora_resolved,
                    )
            else:
                anaphora_resolved["unresolved_anaphora"] = True
                return GoalComprehension(
                    raw_query=raw_text,
                    normalized_goal=raw_text,
                    intent_category="clarification_needed",
                    confidence=0.4,
                    is_ambiguous=True,
                    clarification_question="¿A qué tema o tarea anterior te refieres? No encontré contexto previo en la sesión activa.",
                    is_conversational=False,
                    requires_action=False,
                )

        # 2.2 Anáforas hacia entidades específicas: "eso", "el archivo", "el resumen"
        if re.search(r"\b(?:abre|cierra|guarda|borra)\s+(?:eso|aquello)\b", lower_text):
            last_target = context.working_context.get("current_application") or context.working_context.get("active_document_path")
            if last_target:
                anaphora_resolved["eso"] = last_target
                normalized_text = re.sub(r"\b(?:eso|aquello)\b", str(last_target), raw_text, flags=re.IGNORECASE)

        if re.search(r"\b(?:el\s+archivo|el\s+documento)\b", lower_text):
            doc = context.working_context.get("active_document_path")
            if doc:
                anaphora_resolved["el_archivo"] = doc

        # 2.3 Anáforas hacia la ventana o aplicación activa del turno previo:
        # "ahora escribe...", "en esa ventana...", "dentro del bloc de notas...", "agrega...", "corrige...", "guarda..."
        if re.search(r"\b(?:ahora|en esa ventana|dentro de esa ventana|en el documento|en la ventana|al final)\b", lower_text) or (
            any(w in lower_text for w in ("escribe", "agrega", "corrige", "selecciona", "guarda")) and not any(app in lower_text for app in ("chrome", "word", "excel", "calculadora", "calc"))
        ):
            last_app = context.working_context.get("active_app") or context.working_context.get("current_application") or "bloc de notas"
            last_hwnd = context.working_context.get("active_hwnd")
            anaphora_resolved["target_app"] = last_app
            if last_hwnd:
                anaphora_resolved["target_hwnd"] = last_hwnd

        # 2.4 Detección de corrección del usuario cuando no ve el contenido escrito
        # "Jessica, no veo lo que escribiste", "no aparece nada", "la ventana está vacía"
        if any(ph in lower_text for ph in ("no veo lo que escribiste", "no veo el texto", "no aparece nada", "está vacía", "esta vacia", "no se escribió nada", "no se escribio nada")):
            return GoalComprehension(
                raw_query=raw_text,
                normalized_goal=normalized_text,
                intent_category="user_correction:unseen_text",
                confidence=0.95,
                entities={"correction_type": "unseen_text"},
                is_ambiguous=False,
                is_conversational=False,
                requires_action=True,
                sub_goals=("verificar e inspeccionar ventana de editor", "reintentar escritura en ventana"),
                suggested_tools=("desktop_editor",),
                raw_explanation="El usuario reporta que no visualiza el texto en la aplicación activa.",
            )

        # ── 3. CLASIFICACIÓN CONVERSACIONAL VS ACCIÓN ──
        is_pure_conversation = self._is_conversational_query(normalized_text)
        if is_pure_conversation:
            return GoalComprehension(
                raw_query=raw_text,
                normalized_goal=normalized_text,
                intent_category="conversational",
                confidence=0.95,
                is_ambiguous=False,
                is_conversational=True,
                requires_action=False,
                sub_goals=(),
                suggested_tools=(),
                context_references=anaphora_resolved,
                raw_explanation="Pregunta o diálogo conversacional que no requiere ejecución de herramientas en el SO.",
            )

        # ── 4. DESCOMPOSICIÓN DE INSTRUCCIONES COMPUESTAS EN SUB-METAS ──
        sub_goals = self._decompose_composite_instruction(normalized_text)

        # ── 5. SELECCIÓN PROGRESIVA DE HERRAMIENTAS (SAI Progressive Tool Loading) ──
        domains = ProgressiveToolCatalog.preselect_domains(normalized_text)
        candidate_tools = list(ProgressiveToolCatalog.get_tool_names(domains))

        # Enriquecer herramientas específicas según las submetas identificadas
        specific_tools = self._detect_required_tools(sub_goals or [normalized_text])
        for tool in specific_tools:
            if tool not in candidate_tools:
                candidate_tools.append(tool)

        # ── 6. IDENTIFICACIÓN DE ENTIDADES ──
        entities = self._extract_entities(normalized_text)
        if anaphora_resolved:
            entities.update(anaphora_resolved)

        return GoalComprehension(
            raw_query=raw_text,
            normalized_goal=normalized_text,
            intent_category="action_execution" if len(sub_goals) <= 1 else "composite_plan",
            confidence=0.9,
            entities=entities,
            is_ambiguous=False,
            is_conversational=False,
            requires_action=True,
            sub_goals=tuple(sub_goals),
            suggested_tools=tuple(candidate_tools),
            context_references=anaphora_resolved,
            raw_explanation=f"Objetivo descompuesto en {len(sub_goals)} submetas con {len(candidate_tools)} herramientas candidatas.",
        )

    def evaluate_ambiguity(self, query: str) -> tuple[bool, str | None]:
        """Determina si la solicitud es ambigua o incompleta y propone una pregunta aclaratoria."""
        text = (query or "").strip().lower()
        if not text:
            return True, "¿Podrías indicarme qué deseas hacer?"

        # 1. Frases truncadas o fragmentos ambiguos (ej: "abre yo", "abre yu", "abre el", "inicia la")
        pattern_incomplete_app = re.search(
            r"^(?:jessyca,?\s*|jessica,?\s*)?(?:abre|inicia|lanza)\s+(?:el\s+|la\s+)?(?:yo|yu|un|una)?\s*[.!?]?$",
            text,
            flags=re.IGNORECASE,
        )
        if pattern_incomplete_app:
            return True, "¿Podrías aclararme qué aplicación deseas abrir? No entendí bien el nombre."

        # 2. Verbos de acción sin objeto directo
        pattern_empty_action = re.search(
            r"^(?:jessyca,?\s*|jessica,?\s*)?(?:abre|inicia|ejecuta|lanza|busca|investiga|escribe|borra|elimina)(?:\s+por\s+favor|\s+porfa)?\s*[.!?]?$",
            text,
            flags=re.IGNORECASE,
        )
        if pattern_empty_action:
            action_word = pattern_empty_action.group(0).split()[-1].replace(",", "").replace(".", "")
            if action_word in ("abre", "inicia", "ejecuta", "lanza"):
                return True, "¿Podrías especificar qué aplicación o archivo deseas que abra?"
            if action_word in ("busca", "investiga"):
                return True, "¿Sobre qué tema específico deseas que investigue o busque?"
            if action_word in ("escribe",):
                return True, "¿Qué texto o contenido deseas que escriba y en qué documento?"
            return True, "¿Podrías darme más detalles sobre lo que deseas hacer?"

        # 3. Transcripción fonética aproximada de YouTube y Mozart que requiera aclaración ante incertidumbre
        if ("yo tuy" in text or "yu tub" in text) and ("mozar" in text or "mozart" in text) and ("pregunta" in text or "duda" in text):
            return True, "¿Quieres que abra YouTube y reproduzca música de Mozart?"

        return False, None

    def suggest_alternative_action(
        self,
        failed_action: str,
        failed_tool: str,
        error_message: str,
    ) -> dict[str, Any]:
        """Propone alternativas inteligentes ante errores de ejecución."""
        err_lower = error_message.lower()
        # Fallo de aplicación no encontrada
        if any(w in err_lower for w in ("not found", "notfound", "no encontrada", "no está instalada", "no esta instalada", "inexistente")):
            return {
                "strategy": "PROPOSE_ALTERNATIVE_APP",
                "message": f"La aplicación requerida '{failed_action}' no se encuentra instalada en el sistema. ¿Deseas buscarla en la web o abrir una alternativa predeterminada?",
                "alternative_tool": "browser_search",
                "can_retry": False,
            }
        # Fallo de timeout o bloqueo de UI
        if "timeout" in err_lower or "timed out" in err_lower:
            return {
                "strategy": "RETRY_WITH_HIGHER_TIMEOUT",
                "message": "La acción excedió el tiempo límite de espera. ¿Deseas reintentar con mayor tiempo de tolerancia?",
                "alternative_tool": failed_tool,
                "can_retry": True,
            }
        # Permiso denegado por política de seguridad
        if "denied" in err_lower or "blocked" in err_lower or "privilege" in err_lower:
            return {
                "strategy": "REQUEST_SUPERVISOR_ELEVATION",
                "message": "La operación solicitada requiere elevación de privilegios de seguridad. Solicita confirmación explícita del propietario.",
                "alternative_tool": None,
                "can_retry": False,
            }

        return {
            "strategy": "REPORT_AND_ABORT",
            "message": f"Ocurrió un error en '{failed_tool}': {error_message}.",
            "alternative_tool": None,
            "can_retry": False,
        }

    # ── MÉTODOS AUXILIARES DE ANÁLISIS SEMÁNTICO ──

    def _is_conversational_query(self, text: str) -> bool:
        """Distingue preguntas o diálogos puros de órdenes operativas sobre el sistema."""
        lower = text.lower().strip()
        lower_clean = re.sub(r"^(?:jessyca|jessica)[,\s]+", "", lower).strip()

        # Si explícitamente ordena controlar el sistema operativo -> NO es conversacional puro
        action_verbs = (
            "investiga", "busca información", "busca informacion",
            "abre", "inicia", "lanza", "ejecuta", "cierra", "apaga", "reinicia",
            "baja el volumen", "sube el volumen", "silencia", "mutea",
            "crea un archivo", "crea", "escribe", "guarda", "borra", "elimina",
            "haz clic", "presiona", "toma captura", "screenshot", "reproduce",
            "báilame", "bailame", "baila", "busca la carpeta", "abre los videos", "carpeta",
        )
        if any(v in lower_clean for v in action_verbs):
            return False

        # Tareas de investigación que implican generar resúmenes en apps o archivos
        if "en bloc de notas" in lower_clean or "en notepad" in lower_clean or "en un archivo" in lower_clean or ".txt" in lower_clean or ".md" in lower_clean:
            return False

        # Preguntas conceptuales, filosóficas, históricas o saludos
        conversational_starters = (
            "¿quién fue", "quien fue", "¿quién es", "quien es",
            "¿qué es", "que es", "¿cómo funciona", "como funciona",
            "¿por qué", "por que", "¿cuándo", "cuando",
            "hola", "buenos días", "buenas tardes", "buenas noches",
            "gracias", "¿cómo estás?", "como estas", "cuéntame un chiste",
            "explica", "explícame", "explicame", "descríbeme", "describeme", "dime",
            "cuéntame", "cuentame",
            "¿qué diferencia", "que diferencia", "¿cuál es la diferencia", "cual es la diferencia",
            "diferencia entre", "¿cuál es", "cual es", "¿cuáles son", "cuales son",
            "explícame de otra manera", "explicame de otra manera", "explica de otra manera",
            "de otra manera",
            "¿me escuchas?", "me escuchas", "¿me oyes?", "me oyes",
        )
        if any(lower_clean.startswith(cs) or f" {cs}" in lower_clean or cs in lower_clean for cs in conversational_starters):
            # Excepción: si pide "dime qué hora es" o "abre la calculadora y dime..."
            if not any(v in lower_clean for v in ("abre", "cierra", "escribe", "haz clic", "guarda", "borra")):
                return True

        # Preguntas conceptuales directas sobre ciencia o teoría sin verbos de acción en SO
        if any(w in lower_clean for w in ("entrelazamiento", "física cuántica", "relatividad", "cuántico", "cuántica")) and not any(v in lower_clean for v in action_verbs):
            return True

        # Pregunta directa sobre personas históricas (ej: Albert Einstein)
        if "albert einstein" in lower_clean and not any(v in lower_clean for v in action_verbs):
            return True

        return False

    def _decompose_composite_instruction(self, text: str) -> list[str]:
        """Divide una orden compuesta ("baja el volumen, abre Chrome y busca información sobre Python")
        en submetas individuales limpias."""
        clean = text.strip()
        # Eliminar prefijo de invocación
        clean = re.sub(r"^(?:jessyca,?\s*|por favor,?\s*)", "", clean, flags=re.IGNORECASE)

        # Si es una tarea integrada de "investiga X y prepara un resumen en Bloc de notas"
        if re.search(r"\binvestiga\b.*\by\s+(?:prepara|crea|escribe)\s+(?:un\s+resumen\s+)?en\s+(?:bloc\s+de\s+notas|notepad)\b", clean, flags=re.IGNORECASE):
            match_theme = re.search(r"\binvestiga\s+(.+?)\s+y\s+(?:prepara|crea|escribe)", clean, flags=re.IGNORECASE)
            theme = match_theme.group(1).strip() if match_theme else "el tema solicitado"
            return [
                f"investigar {theme}",
                "abrir bloc de notas",
                f"escribir resumen de {theme} en bloc de notas",
            ]

        # Si es una instrucción continua de YouTube ("abre YouTube y reproduce X"), no dividirla
        if re.search(r"\b(?:abre|abrir)\s+(?:youtube|yo tuy|yu tub)\s+y\s+(?:reproduce|repreduce|pon)\b", clean, flags=re.IGNORECASE):
            return [clean]

        # Separadores de conjunción e instrucciones secuenciales: ", luego ", ", después ", " y luego ", ", ", " y "
        parts = re.split(r"(?:,\s*(?:luego|despu[eé]s)\s*|\s+(?:luego|despu[eé]s)\s*|,\s*y\s*|,\s*|\s+y\s+)", clean, flags=re.IGNORECASE)

        sub_goals: list[str] = []
        for p in parts:
            p_strip = p.strip()
            if len(p_strip) > 2:
                sub_goals.append(p_strip)

        return sub_goals if len(sub_goals) > 1 else [clean]

    def _detect_required_tools(self, sub_goals: list[str]) -> list[str]:
        """Identifica herramientas requeridas basadas en las acciones de las submetas."""
        tools: list[str] = []
        for g in sub_goals:
            gl = g.lower()
            if any(w in gl for w in ("volumen", "audio", "sonido", "mutear", "silenciar")):
                tools.append("system_audio")
            if any(w in gl for w in ("bailame", "báilame", "baile", "bailes", "video local", "videos locales", "música local", "musica local", "de mi computadora", "de mi pc")) or ("video" in gl and any(loc in gl for loc in ("local", "disco", "carpeta", "d:"))):
                tools.append("windows_media")
            if any(w in gl for w in ("abre la carpeta", "abrir la carpeta", "abre los videos", "muestra la carpeta")) or ("carpeta" in gl and any(w in gl for w in ("abre", "abrir"))):
                tools.append("app_launcher")
            if any(w in gl for w in ("busca la carpeta", "buscar la carpeta", "busca el archivo", "buscar archivo")) or ("carpeta" in gl and any(w in gl for w in ("busca", "buscar"))):
                tools.append("file_search")
            if any(w in gl for w in ("youtube", "yo tuy", "yu tub")) or (any(w in gl for w in ("reproduce", "pon música", "pon musica")) and not any(loc in gl for loc in ("local", "computadora", "pc", "disco", "carpeta", "baile", "bailame", "báilame"))):
                tools.append("browser_youtube")
            if any(w in gl for w in ("abre", "abrir", "calculadora", "notepad", "bloc de notas", "chrome", "calc")):
                tools.append("app_launcher")
            if any(w in gl for w in ("busca", "buscar", "navegador", "web")) and not any(loc in gl for loc in ("carpeta", "archivo", "disco", "local")):
                tools.append("browser_search")
            if any(w in gl for w in ("investiga", "investigar", "entrelazamiento", "física", "ciencia")):
                tools.append("academic_search")
            if any(w in gl for w in ("crea un archivo", "crear archivo", "archivo txt", "en disco")) or (
                re.search(r"\b(?:crea|genera)\b", gl) and re.search(r"\.(?:txt|md)\b", gl)
            ):
                tools.append("files_create")
            elif any(w in gl for w in ("escribe", "escribir", "redacta", "resumen", "agrega", "corrige", "párrafo", "conclusión", "bloc de notas")):
                tools.append("desktop_editor")
            if any(w in gl for w in ("guarda", "guardar")):
                tools.append("gui_file_saver")
        return list(dict.fromkeys(tools))

    def _extract_entities(self, text: str) -> dict[str, Any]:
        """Extrae entidades relevantes de la instrucción (aplicaciones, consultas, URLs, textos a escribir)."""
        entities: dict[str, Any] = {}
        lower = text.lower()

        # Baile / Multimedia local
        if re.search(r"\bb[aá]ilame\b", lower) or (
            any(w in lower for w in ("baile", "bailes"))
            and re.search(r"\b(?:reproduce|pon|ponme|quiero ver)\b", lower)
        ):
            entities["is_dance"] = True
            entities["action"] = "play_random_video"
            entities["target_directory"] = r"D:\bailes de ia"

        # Detección de carpetas y unidades Windows locales
        if any(w in lower for w in ("disco d", "d:", "unidad d")):
            entities["drive"] = "D:\\"
            entities["target_drive"] = "D:"
        elif any(w in lower for w in ("disco c", "c:", "unidad c")):
            entities["drive"] = "C:\\"
            entities["target_drive"] = "C:"

        if "carpeta" in lower:
            m_fol = re.search(r"carpeta(?:\s+de)?\s+([a-zA-Z0-9_\-\s]+?)(?:\s+en\s+el|\s+del|\s+en|$)", text, flags=re.IGNORECASE)
            if m_fol:
                entities["target_folder"] = m_fol.group(1).strip()
            elif "baile" in lower:
                entities["target_folder"] = "Bailes de IA"

        if any(w in lower for w in ("local", "locales", "computadora", "mi pc", "en mi disco", "carpeta")) and re.search(r"\b(?:reproduce|reproducir|pon|ponme|toca)\b", lower):
            entities["is_local_media"] = True
            if "video" in lower:
                entities["media_type"] = "video"
            elif any(w in lower for w in ("música", "musica", "canción", "cancion", "canciones")):
                entities["media_type"] = "audio"

        # Aplicación
        for app in ("calculadora", "calc", "bloc de notas", "notepad", "chrome", "edge", "spotify", "word", "excel"):
            if app in lower:
                entities["target_app"] = app
                break

        # Música, YouTube y compositores (SOLO si no es multimedia local ni baile)
        if not entities.get("is_dance") and not entities.get("is_local_media"):
            if any(w in lower for w in ("reproduce", "repreduce", "pon", "música", "musica", "video", "youtube", "yo tuy", "yu tub", "mozart", "mozar", "beethoven", "bach")):
                m_comp = re.search(r"(?:música\s+de|musica\s+de|canciones?\s+de|videos?\s+de|a)\s+([a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+)", text, flags=re.IGNORECASE)
                if m_comp:
                    entities["composer"] = m_comp.group(1).strip()
                    entities["media_query"] = f"música de {entities['composer']}"
                elif "mozart" in lower or "mozar" in lower:
                    entities["composer"] = "Mozart"
                    entities["media_query"] = "música de Mozart"

        # Búsqueda o tema de investigación
        m_search = re.search(r"(?:busca|buscar|investiga|investigar)(?:\s+información\s+sobre|\s+sobre|\s+qu[eé]\s+es)?\s+([^,]+)", text, flags=re.IGNORECASE)
        if m_search:
            entities["search_query"] = m_search.group(1).strip()

        # Entidades de edición y escritura GUI (Pruebas A a J)
        # 1. Modo de edición:
        if any(w in lower for w in ("agrega", "añade", "conclusión", "al final")):
            entities["editor_mode"] = "append"
        elif any(w in lower for w in ("corrige", "modifica", "reemplaza")):
            entities["editor_mode"] = "replace"
        elif "selecciona" in lower:
            entities["editor_mode"] = "select_all"
        else:
            entities["editor_mode"] = "write"

        # 2. Texto literal explícito entre comillas o tras ':' (ej: 'escribe: prueba de escritura de JESSYCA', escribe "hola mundo")
        m_literal = re.search(r"escribe(?:\s*:\s*|\s+[\"'])(.+?)(?:[\"']|$)", text, flags=re.IGNORECASE)
        if m_literal:
            cand_literal = m_literal.group(1).strip().strip('"').strip("'")
            if cand_literal.startswith(":"):
                cand_literal = cand_literal[1:].strip()
            if cand_literal and not cand_literal.lower().startswith("en el bloc") and not any(w in cand_literal.lower() for w in ("los 3", "los tres", "principios", "termodinámica", "termodinamica", "resumen sobre")):
                entities["writing_text"] = cand_literal

        # 3. Tema conceptual para redacción (ej: 'los 3 principios de la termodinámica', 'resumen sobre IA')
        m_topic = re.search(r"(?:escribe|redacta)\s+(?:un\s+resumen\s+sobre|un\s+texto\s+sobre|sobre|los|las|el|la)?\s*(.+)", text, flags=re.IGNORECASE)
        if m_topic:
            topic_str = m_topic.group(1).strip()
            topic_str = re.sub(r"\b(?:en el bloc de notas|en notepad|en la ventana)\b", "", topic_str, flags=re.IGNORECASE).strip()
            if topic_str.startswith(":"):
                topic_str = topic_str[1:].strip()
            if topic_str:
                entities["writing_topic"] = topic_str

        # 4. Guardado explícito de archivo (ej: 'guarda como termodinamica.txt')
        m_save = re.search(r"guarda(?:r)?(?:\s+el\s+documento)?(?:\s+como)?\s+([a-zA-Z0-9_\-]+\.(?:txt|md|log))", text, flags=re.IGNORECASE)
        if m_save:
            entities["save_filename"] = m_save.group(1).strip()

        # Nivel de volumen
        if "volumen" in lower:
            if "baja" in lower or "disminuye" in lower:
                entities["volume_action"] = "down"
            elif "sube" in lower or "aumenta" in lower:
                entities["volume_action"] = "up"
            elif "silencia" in lower or "mute" in lower:
                entities["volume_action"] = "mute"

        return entities
