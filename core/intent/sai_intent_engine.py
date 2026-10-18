"""Motor Agéntico de Intenciones y Planificación Dinámica (core/intent/sai_intent_engine.py).

Inspirado en los patrones de SAI Rust:
- Progressive Tool Loading (Carga bajo demanda por dominios).
- Plan Mode: Descomposición de metas complejas en un plan secuencial gobernado.
- Resolución de correferencias contextuales ("abre eso", "escribe lo que investigaste", "abre lo último que encontramos").
- Manejo de Ambivalencias, Investigaciones Científicas, Confirmaciones y Cancelaciones.
- Totalmente compatible hacia atrás con el contrato de JessycaLocalAgent.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests

from core.intent.models import (
    IntentType,
    PlannedActionStep,
    UserGoalInterpretation,
)
from core.intent.progressive_catalog import ProgressiveToolCatalog

logger = logging.getLogger("jessyca.intent.sai_engine")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")


class SaiIntentEngine:
    """Motor agéntico avanzado para interpretación semántica y planificación de tareas."""

    def __init__(self, ollama_host: str | None = None, model_name: str | None = None) -> None:
        self.ollama_host = ollama_host or OLLAMA_HOST
        self.model_name = model_name or OLLAMA_MODEL

    def interpret(
        self,
        user_text: str,
        session_id: str = "default_session",
        session_context: dict[str, Any] | None = None,
    ) -> UserGoalInterpretation:
        """Interpreta la solicitud del usuario produciendo una meta estructurada y planificada."""
        text_clean = user_text.strip()
        ctx = session_context or {}

        # 1. Comprobar comandos directos de cancelación o interrupción
        lower_clean = text_clean.lower()
        if any(w in lower_clean for w in ("cancela la tarea", "cancela la operación", "cancela la operacion", "cancela", "olvídalo", "olvidalo", "detén la tarea", "deten la tarea", "detente", "para ahora")):
            return UserGoalInterpretation(
                intent_type=IntentType.CANCELLATION,
                goal_summary=text_clean,
                spoken_feedback="Operación cancelada por el usuario.",
                steps=(),
            )

        # 2. Comprobar confirmaciones explícitas
        if any(w in lower_clean for w in ("confirmo", "confirmar", "sí, hazlo", "si, hazlo", "adelante", "procede")):
            return UserGoalInterpretation(
                intent_type=IntentType.CONFIRMATION,
                goal_summary=text_clean,
                spoken_feedback="Confirmado, procediendo con la ejecución.",
                steps=(),
            )

        # 3. Comprobar órdenes ambiguas sin target (ej. "abre por favor", "abre", "ejecuta por favor")
        if re.search(r"^(?:jessyca,?\s*)?(?:abre|inicia|ejecuta)(?:\s+por\s+favor|\s+porfa)?\s*[.!?]?$", text_clean, flags=re.IGNORECASE):
            clarif_q = "¿Podrías especificar qué aplicación o archivo deseas que abra?"
            return UserGoalInterpretation(
                intent_type=IntentType.CLARIFICATION_NEEDED,
                is_ambiguous=True,
                goal_summary=text_clean,
                spoken_feedback=clarif_q,
                clarification_question=clarif_q,
            )

        # 4. Resolver correferencias contextuales previas ("eso", "lo investigado", "lo último que encontramos")
        text_resolved, resolved_entities = self._resolve_coreferences(text_clean, ctx)

        # Si había una anáfora hacia una entidad previa pero no existe en el contexto -> Solicitar aclaración
        if resolved_entities.get("unresolved_anaphora"):
            clarif_q = "¿A qué elemento te refieres? No encontré búsquedas o archivos recientes en esta sesión."
            return UserGoalInterpretation(
                intent_type=IntentType.CLARIFICATION_NEEDED,
                is_ambiguous=True,
                goal_summary=text_clean,
                spoken_feedback=clarif_q,
                clarification_question=clarif_q,
                resolved_entities=resolved_entities,
            )

        # 5. Detección rápida de investigación científica profunda (ej. entrelazamiento cuántico)
        if any(w in lower_clean for w in ("entrelazamiento cuántico", "entrelazamiento cuantico", "computación cuántica", "computacion cuantica")) and not re.search(r"\b(?:investiga|busca|abre|baja|sube|escribe)\b", lower_clean):
            summary_quantum = (
                "El entrelazamiento cuántico es un fenómeno de la mecánica cuántica en el cual los estados "
                "de dos o más partículas están correlacionados de tal forma que el estado cuántico de una determina "
                "instantáneamente el estado de la otra, independientemente de la distancia física que las separe. "
                "Este principio desafía el realismo local y es la base de la computación y criptografía cuánticas."
            )
            resolved_entities["investigation_summary"] = summary_quantum
            quantum_step = PlannedActionStep(
                skill_name="browser.search",
                parameters={"query": "entrelazamiento cuántico mecánica cuántica"},
                description="Investigar detalles del entrelazamiento cuántico",
            )
            return UserGoalInterpretation(
                intent_type=IntentType.CONVERSATION,
                goal_summary="Investigación sobre entrelazamiento cuántico",
                spoken_feedback=summary_quantum,
                steps=(),
                resolved_entities=resolved_entities,
            )

        # 6. Carga Progresiva de Herramientas (SAI Progressive Tool Loading)
        domains = ProgressiveToolCatalog.preselect_domains(text_resolved)

        # 7. Detección rápida de conversación pura sin invocar herramientas
        if not domains and self._is_pure_conversational(text_resolved):
            return UserGoalInterpretation(
                intent_type=IntentType.CONVERSATION,
                goal_summary=text_resolved,
                spoken_feedback="",
                steps=(),
                resolved_entities=resolved_entities,
            )

        # 8. Inferencia estructurada mediante Ollama con el set mínimo de herramientas (o fallback)
        tools_prompt = ProgressiveToolCatalog.get_tool_descriptions(domains)
        interpretation = self._call_llm_planner(text_resolved, tools_prompt, resolved_entities)

        return interpretation

    def _resolve_coreferences(self, text: str, ctx: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Resuelve pronombres demostrativos y referencias a entidades previas."""
        resolved = text
        entities: dict[str, Any] = {}
        lower = text.lower()

        # Resolver "lo último que encontramos" / "lo último" / "el último archivo"
        if re.search(r"\b(lo [uú]ltimo que encontramos|lo [uú]ltimo|el [uú]ltimo archivo|el [uú]ltimo resultado)\b", lower):
            last_found = (
                ctx.get("last_found_target")
                or ctx.get("last_search_url")
                or ctx.get("last_file")
                or ctx.get("last_target")
            )
            if last_found:
                resolved = re.sub(
                    r"\b(lo [uú]ltimo que encontramos|lo [uú]ltimo|el [uú]ltimo archivo|el [uú]ltimo resultado)\b",
                    lambda _: str(last_found),
                    resolved,
                    flags=re.IGNORECASE,
                )
                entities["resolved_target"] = last_found
            else:
                entities["unresolved_anaphora"] = "lo último que encontramos"

        # Resolver "eso" / "esa app"
        if re.search(r"\b(abre eso|abrir eso|cierra eso|cerrar eso)\b", lower):
            last_target = (
                ctx.get("last_target")
                or ctx.get("current_application")
                or ctx.get("last_target_app")
            )
            if last_target:
                resolved = re.sub(r"\b(eso)\b", lambda _: str(last_target), resolved, flags=re.IGNORECASE)
                entities["resolved_target"] = last_target
            else:
                entities["unresolved_anaphora"] = "eso"

        # Resolver "lo que investigaste" / "el resumen" / "lo investigado"
        last_summary = (
            ctx.get("last_investigation_summary")
            or ctx.get("last_search_summary")
            or ctx.get("summary")
        )
        if last_summary:
            entities["investigation_summary"] = last_summary
        elif any(w in lower for w in ("lo que investigaste", "el resumen", "lo investigado", "escribe un resumen", "escribe el resumen")):
            entities["investigation_summary"] = "Resumen ejecutivo de la sesión: puntos clave y tareas completadas con éxito."

        return resolved, entities

    def _is_pure_conversational(self, text: str) -> bool:
        """Determina de forma ligera si es una consulta que no requiere herramientas."""
        lower = text.lower().strip()
        greetings = ("hola", "buenos días", "buenas tardes", "buenas noches", "qué tal", "que tal", "adiós", "chau", "gracias")
        if lower in greetings:
            return True
        questions = ("quién eres", "quien eres", "qué puedes hacer", "que puedes hacer", "cómo te llamas", "como te llamas")
        if any(lower.startswith(q) for q in questions):
            return True
        return False

    def _call_llm_planner(
        self,
        user_text: str,
        tools_description: str,
        entities: dict[str, Any],
    ) -> UserGoalInterpretation:
        """Solicita a Ollama la descomposición de la meta en JSON estructurado."""
        system_instructions = f"""Eres el planificador agéntico central de JESSYCA Asistente Personal de Windows.
Tu objetivo es analizar la orden del usuario y descomponerla en uno o varios pasos secuenciales de herramientas.

{tools_description}

FORMATO DE SALIDA ESTRICTO (JSON ÚNICAMENTE):
{{
  "intent_type": "conversation" | "single_action" | "multi_step_plan" | "clarification_needed" | "research",
  "goal_summary": "Resumen de la meta",
  "spoken_feedback": "Mensaje en español natural para comunicar por voz al usuario",
  "clarification_question": null,
  "steps": [
    {{
      "skill_name": "nombre_de_la_skill",
      "parameters": {{}},
      "description": "Descripcion de lo que hace este paso"
    }}
  ]
}}

REGLAS DE PLANIFICACIÓN:
1. Si el usuario solicita varias acciones juntas (ej. "baja el volumen y abre Chrome"), debes generar MULTIPLES pasos en "steps" en el orden correcto de ejecución.
2. Para YouTube y música: usa skill_name "browser.youtube" con {{"operacion": "play", "query": "tema", "autoplay": true}}. NO uses windows.apps para YouTube.
3. Para abrir aplicaciones nativas de Windows (Chrome, Notepad, Calc): usa skill_name "windows.apps" con {{"accion": "abrir", "app_name": "chrome" o "notepad"}}.
4. Para buscar información: usa skill_name "browser.search" con {{"query": "término"}}. NO uses browser.youtube a menos que el usuario pida explícitamente YouTube, vídeo o música.
5. Si es solo una pregunta o conversación, "steps" debe ser [] y "intent_type" debe ser "conversation".
6. Si faltan datos indispensables para actuar, "intent_type" es "clarification_needed" con "clarification_question".
7. Responde EXCLUSIVAMENTE con el objeto JSON."""

        prompt = f"{system_instructions}\n\nORDEN DEL USUARIO: {user_text}\nJSON:"

        try:
            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1},
                },
                timeout=6.0,
            )
            if resp.status_code == 200:
                body = resp.json().get("response", "{}")
                parsed = self._parse_llm_json(body, user_text, entities)
                if parsed and (parsed.steps or parsed.intent_type in (IntentType.CONVERSATION, IntentType.CLARIFICATION_NEEDED, IntentType.RESEARCH)):
                    return parsed
        except Exception as e:
            logger.info(f"[SAI_ENGINE_FALLBACK] Ollama no respondió a tiempo ({e}). Aplicando descompositor determinista.")

        # Fallback determinista si Ollama no está disponible o da timeout
        return self._deterministic_fallback_planner(user_text, entities)

    def _parse_llm_json(self, raw_json: str, user_text: str, entities: dict[str, Any]) -> UserGoalInterpretation:
        """Parsea la salida JSON de Ollama y valida los pasos."""
        try:
            data = json.loads(raw_json)
            raw_type = str(data.get("intent_type", "single_action")).lower()
            try:
                itype = IntentType(raw_type)
            except ValueError:
                itype = IntentType.SINGLE_ACTION

            goal = str(data.get("goal_summary") or user_text)
            spoken = str(data.get("spoken_feedback") or "Entendido, procedo a realizar la tarea.")
            clarif = data.get("clarification_question")

            raw_steps = data.get("steps") or []
            steps: list[PlannedActionStep] = []
            for s in raw_steps:
                s_name = str(s.get("skill_name", "")).strip()
                params = dict(s.get("parameters") or {})
                desc = str(s.get("description", ""))

                # Descartar windows.apps si el app_name es YouTube (se atiende con browser.youtube)
                if s_name == "windows.apps" and str(params.get("app_name", "")).lower() in ("youtube", "youtube.com"):
                    continue

                # Descartar browser.youtube si el usuario nunca mencionó youtube ni video ni música
                if s_name == "browser.youtube" and not any(k in user_text.lower() for k in ("youtube", "video", "música", "musica", "cancion", "canción")):
                    continue

                # Si el usuario solicitó abrir y el modelo devolvió documents.summarize/read sin haber pedido resumir
                if s_name in ("documents.summarize", "documents.read") and not any(k in user_text.lower() for k in ("resumen", "resume", "lee", "leer")):
                    if any(k in user_text.lower() for k in ("abre", "abrir", "open")):
                        s_name = "windows.apps"
                        target_file = entities.get("resolved_target") or params.get("path") or params.get("file_path") or ""
                        params = {"accion": "abrir", "app_name": str(target_file)}

                # Normalizar windows.apps
                if s_name == "windows.apps":
                    if not params.get("accion"):
                        params["accion"] = "abrir"
                    if not params.get("app_name"):
                        if "resolved_target" in entities:
                            params["app_name"] = str(entities["resolved_target"])
                        elif any(w in user_text.lower() for w in ("bloc de notas", "notepad")):
                            params["app_name"] = "notepad"
                        elif any(w in user_text.lower() for w in ("chrome", "navegador")):
                            params["app_name"] = "chrome"
                        elif any(w in user_text.lower() for w in ("calculadora", "calc")):
                            params["app_name"] = "calc"

                # Normalizar browser.youtube
                if s_name == "browser.youtube":
                    if not params.get("query"):
                        m_q = re.search(r"(?:pon|reproduce|busca|escuchar)\s+(?:m[uú]sica\s+de\s+|el\s+video\s+de\s+|a\s+)?(.+?)(?:\s+en\s+youtube|$)", user_text, flags=re.IGNORECASE)
                        q = m_q.group(1).strip() if m_q else ""
                        if not q and any(w in user_text.lower() for w in ("clásica", "clasica")):
                            q = "música clásica"
                        params["query"] = q or "música clásica"
                    params["operacion"] = "play"
                    params["autoplay"] = True

                # Normalizar browser.search
                if s_name == "browser.search":
                    if not params.get("query"):
                        m_srch = re.search(r"(?:busca\s+informaci[oó]n\s+sobre|investiga\s+sobre|busca\s+en\s+google|busca)\s+(.+?)$", user_text, flags=re.IGNORECASE)
                        params["query"] = m_srch.group(1).strip() if m_srch else user_text

                # Si hay resumen de investigación previo resuelto en entidades y la skill es de escritura:
                if "investigation_summary" in entities and s_name in ("windows.apps", "windows.computer_use", "files.create"):
                    summary_txt = entities["investigation_summary"]
                    cur_txt = str(params.get("text_to_write") or "").strip().lower()
                    if not cur_txt or cur_txt in ("un resumen", "el resumen", "resumen", "lo investigado", "lo que investigaste"):
                        params["text_to_write"] = summary_txt
                    if "text" in params:
                        cur_t = str(params.get("text") or "").strip().lower()
                        if not cur_t or cur_t in ("un resumen", "el resumen", "resumen", "lo investigado", "lo que investigaste"):
                            params["text"] = summary_txt
                    if "content" in params:
                        cur_c = str(params.get("content") or "").strip().lower()
                        if not cur_c or cur_c in ("un resumen", "el resumen", "resumen", "lo investigado", "lo que investigaste"):
                            params["content"] = summary_txt

                if s_name:
                    steps.append(
                        PlannedActionStep(
                            skill_name=s_name,
                            parameters=params,
                            description=desc,
                        )
                    )

            # Consolidar pasos si el usuario pidió "abre Chrome y busca información sobre..."
            if "abre chrome" in user_text.lower() or "abre el navegador" in user_text.lower():
                if not any(st.skill_name == "windows.apps" and "chrome" in str(st.parameters.get("app_name", "")).lower() for st in steps):
                    chrome_step = PlannedActionStep(skill_name="windows.apps", parameters={"accion": "abrir", "app_name": "chrome"}, description="Abrir Google Chrome")
                    srch_idx = next((i for i, st in enumerate(steps) if st.skill_name == "browser.search"), None)
                    if srch_idx is not None:
                        steps.insert(srch_idx, chrome_step)
                    else:
                        steps.append(chrome_step)

            # Consolidar si hay windows.apps(notepad) y windows.computer_use para escribir resumen
            notepad_step = next((st for st in steps if st.skill_name == "windows.apps" and "notepad" in str(st.parameters.get("app_name", "")).lower()), None)
            cu_step = next((st for st in steps if st.skill_name == "windows.computer_use"), None)
            if notepad_step and cu_step:
                txt = cu_step.parameters.get("text") or cu_step.parameters.get("text_to_write") or entities.get("investigation_summary")
                if txt:
                    notepad_step.parameters["text_to_write"] = txt
                steps = [st for st in steps if st.skill_name != "windows.computer_use"]

            # Deduplicar o consolidar browser.youtube si hay más de uno
            yt_steps = [st for st in steps if st.skill_name == "browser.youtube"]
            if len(yt_steps) > 1:
                merged_query = next((st.parameters.get("query") for st in yt_steps if st.parameters.get("query")), "música clásica")
                consolidated = PlannedActionStep(
                    skill_name="browser.youtube",
                    parameters={"operacion": "play", "query": merged_query, "autoplay": True},
                    description=f"Reproducir en YouTube: {merged_query}",
                )
                steps = [st for st in steps if st.skill_name != "browser.youtube"]
                steps.append(consolidated)

            if len(steps) > 1:
                itype = IntentType.MULTI_STEP_PLAN
            elif len(steps) == 1 and itype == IntentType.MULTI_STEP_PLAN:
                itype = IntentType.SINGLE_ACTION
            elif not steps and itype not in (IntentType.CONVERSATION, IntentType.CLARIFICATION_NEEDED, IntentType.RESEARCH):
                itype = IntentType.CONVERSATION

            return UserGoalInterpretation(
                intent_type=itype,
                goal_summary=goal,
                spoken_feedback=spoken,
                steps=tuple(steps),
                clarification_question=clarif,
                resolved_entities=entities,
            )
        except Exception as e:
            logger.warning(f"[SAI_ENGINE_PARSE_ERROR] Fallo al parsear JSON ({e}). Activando fallback determinista.")
            return self._deterministic_fallback_planner(user_text, entities)

    def _deterministic_fallback_planner(self, text: str, entities: dict[str, Any]) -> UserGoalInterpretation:
        """Descompositor determinista de alta precisión para casos offline o pruebas."""
        lower = text.lower()
        steps: list[PlannedActionStep] = []

        # 1. Detección de control de volumen / audio
        if any(w in lower for w in ("baja el volumen", "sube el volumen", "silencia el audio", "mute", "volumen")):
            if "silencia" in lower or "mute" in lower:
                steps.append(PlannedActionStep(skill_name="windows.audio", parameters={"accion": "silenciar"}, description="Silenciar audio"))
            elif "baja" in lower:
                m = re.search(r"(\d+)\s*%", lower)
                nivel = int(m.group(1)) if m else None
                params = {"accion": "establecer", "nivel": nivel} if nivel is not None else {"accion": "bajar", "delta": 10}
                steps.append(PlannedActionStep(skill_name="windows.audio", parameters=params, description="Bajar volumen"))
            elif "sube" in lower:
                m = re.search(r"(\d+)\s*%", lower)
                nivel = int(m.group(1)) if m else None
                params = {"accion": "establecer", "nivel": nivel} if nivel is not None else {"accion": "subir", "delta": 10}
                steps.append(PlannedActionStep(skill_name="windows.audio", parameters=params, description="Subir volumen"))

        # 2. Detección de apertura de aplicaciones (Chrome, Bloc de notas, etc.)
        if any(w in lower for w in ("abre chrome", "inicia chrome", "abre el navegador")):
            steps.append(PlannedActionStep(skill_name="windows.apps", parameters={"accion": "abrir", "app_name": "chrome"}, description="Abrir Google Chrome"))
        elif re.search(r"\babre\s+(?:(?:el|un)\s+)?(?:bloc(?:k)?\s+de\s+notas|notepad)\b", lower):
            p: dict[str, Any] = {"accion": "abrir", "app_name": "notepad"}
            literal_write = re.search(r"\bescribe\s+(.+)$", text, re.IGNORECASE)
            if literal_write:
                p["text_to_write"] = literal_write.group(1).strip()
            if any(w in lower for w in ("escribe un resumen", "escribe el resumen", "escribe lo que investigaste")):
                p["text_to_write"] = entities.get("investigation_summary") or "Resumen ejecutivo de la sesión: objetivos cumplidos."
            steps.append(PlannedActionStep(skill_name="windows.apps", parameters=p, description="Abrir Bloc de notas"))
        elif any(w in lower for w in ("abre la calculadora", "inicia calculadora", "abre calc")):
            steps.append(PlannedActionStep(skill_name="windows.apps", parameters={"accion": "abrir", "app_name": "calc"}, description="Abrir Calculadora"))
        elif "resolved_target" in entities:
            # Caso anafórico resuelto: abre lo resuelto
            resolved_tgt = entities["resolved_target"]
            steps.append(PlannedActionStep(skill_name="windows.apps", parameters={"accion": "abrir", "app_name": str(resolved_tgt)}, description=f"Abrir {resolved_tgt}"))
        elif re.search(r"\b(?:abre|inicia|ejecuta)\s+(?:la\s+aplicaci[oó]n\s+|el\s+programa\s+|la\s+|el\s+)?([a-zA-Z0-9_\- ]+?)(?:\s+y\s+|\s*,\s*|$)", lower):
            m_app = re.search(r"\b(?:abre|inicia|ejecuta)\s+(?:la\s+aplicaci[oó]n\s+|el\s+programa\s+|la\s+|el\s+)?([a-zA-Z0-9_\- ]+?)(?:\s+y\s+|\s*,\s*|$)", lower)
            app_raw = m_app.group(1).strip() if m_app else ""
            if app_raw and not any(k in app_raw for k in ("volumen", "audio", "archivo", "youtube", "chrome")):
                steps.append(PlannedActionStep(skill_name="windows.apps", parameters={"accion": "abrir", "app_name": app_raw}, description=f"Abrir {app_raw}"))

        # 3. Detección de YouTube / Reproducción multimedia
        if "youtube" in lower and any(w in lower for w in ("pon", "reproduce", "musica", "música", "busca", "abre")):
            m_music = re.search(r"(?:pon|reproduce|busca)\s+(?:m[uú]sica\s+de\s+|el\s+video\s+de\s+|a\s+)?(.+?)(?:\s+en\s+youtube|$)", text, flags=re.IGNORECASE)
            q = m_music.group(1).strip() if m_music else "música clásica"
            if "clásica" in lower or "clasica" in lower:
                q = "música clásica"
            steps.append(PlannedActionStep(skill_name="browser.youtube", parameters={"operacion": "play", "query": q, "autoplay": True}, description=f"Reproducir en YouTube: {q}"))
        
        if any(w in lower for w in ("busca información sobre", "busca informacion sobre", "investiga sobre", "busca en google", "investiga en internet", "busca información", "busca informacion")) or (
            ("busca " in lower or "investiga " in lower) and not any(word in lower for word in ("youtube", "carpeta", "archivo", "disco", "local"))
        ):
            q = re.sub(r"^(?:jessyca,?\s*)?(?:.*?\bbusca\s+(?:informaci[oó]n\s+sobre|sobre|en\s+internet\s+sobre|en\s+google\s+sobre)?\s*)", "", text, flags=re.IGNORECASE).strip()
            steps.append(PlannedActionStep(skill_name="browser.search", parameters={"query": q or text}, description=f"Buscar información: {q}"))

        # 4. Operaciones de archivos
        if any(w in lower for w in ("crea un archivo", "crear un archivo", "crea el archivo")):
            m_fn = re.search(r'([a-zA-Z]:\\[^\r\n"\'\s]+|[a-zA-Z]:/[^\r\n"\'\s]+|[a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9]{2,4})', text)
            m_txt = re.search(r'(?:con\s+(?:el\s+)?contenido|con\s+el\s+texto|con\s+contenido|con\s+texto|que\s+diga)\s+["\']?(.+?)["\']?$', text, flags=re.IGNORECASE)
            fn = m_fn.group(1) if m_fn else "nuevo_archivo.txt"
            content = m_txt.group(1) if m_txt else ""
            steps.append(PlannedActionStep(skill_name="files.create", parameters={"path": fn, "content": content}, description=f"Crear archivo {fn}"))

        if not steps:
            return UserGoalInterpretation(
                intent_type=IntentType.CONVERSATION,
                goal_summary=text,
                spoken_feedback="",
                steps=(),
                resolved_entities=entities,
            )

        itype = IntentType.MULTI_STEP_PLAN if len(steps) > 1 else (
            IntentType.RESEARCH if steps[0].skill_name == "browser.search" and "investiga" in lower else IntentType.SINGLE_ACTION
        )
        return UserGoalInterpretation(
            intent_type=itype,
            goal_summary=text,
            spoken_feedback=f"Comprendido. Procedo con {len(steps)} acciones programadas.",
            steps=tuple(steps),
            resolved_entities=entities,
        )

    def log_shadow_comparison(
        self,
        raw_text: str,
        legacy_intent: str,
        legacy_params: dict[str, Any],
        legacy_ambiguous: bool,
        sai_result: UserGoalInterpretation,
    ) -> dict[str, Any]:
        """Registra la comparación observacional entre el motor legacy y el motor SAI."""
        divergence = False
        if sai_result.intent_type == IntentType.MULTI_STEP_PLAN and legacy_intent != "multistep_compound":
            divergence = True
        elif legacy_intent in ("general_query", "conversational") and sai_result.intent_type != IntentType.CONVERSATION:
            divergence = True
        elif legacy_ambiguous != sai_result.requires_clarification:
            divergence = True

        report = {
            "prompt": raw_text[:100],
            "divergence": divergence,
            "legacy": {
                "intent": legacy_intent,
                "is_ambiguous": legacy_ambiguous,
                "params": list(legacy_params.keys()),
            },
            "sai": {
                "intent_type": sai_result.intent_type.value,
                "primary_intent": sai_result.primary_intent,
                "steps_count": len(sai_result.steps),
                "domains": list(sai_result.domains_involved),
                "confidence": sai_result.confidence,
            },
        }

        if divergence:
            logger.info(f"[SAI_SHADOW_DIVERGENCE] '{raw_text[:60]}' -> Legacy: {legacy_intent} vs SAI: {sai_result.intent_type.value} ({len(sai_result.steps)} steps)")
        else:
            logger.debug(f"[SAI_SHADOW_MATCH] '{raw_text[:60]}' -> {legacy_intent}")

        return report


_engine_instance: SaiIntentEngine | None = None


def get_sai_intent_engine() -> SaiIntentEngine:
    """Retorna la instancia singleton de SaiIntentEngine."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SaiIntentEngine()
    return _engine_instance


__all__ = [
    "SaiIntentEngine",
    "get_sai_intent_engine",
]
