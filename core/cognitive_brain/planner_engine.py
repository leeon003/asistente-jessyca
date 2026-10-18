"""JESSYCA BRAIN 1.0 — Motor de Planificación Jerárquica y Replanificación (PlannerEngine).

Implementa el contrato formal `PlanningProvider` definido en `core/cognitive_brain/contracts.py`:
1. Formulación de planes canónicos secuenciales o en grafo acíclico dirigido (DAG).
2. Identificación de herramientas autorizadas y asignación de parámetros estructurados.
3. Evaluación de riesgos y delimitación de pasos que requieren confirmación del usuario.
4. Validación formal del grafo de dependencias (detección estricta de ciclos y referencias rotas).
5. Replanificación inteligente ante fallos sin repetir acciones irreversibles ya completadas.
6. Límites estrictos de pasos, tiempo de ejecución y reintentos.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from core.cognitive_brain.contracts import (
    CanonicalPlan,
    CanonicalPlanStep,
    GoalComprehension,
    PlanningProvider,
    PlanStepExecutionState,
)

logger = logging.getLogger("jessyca.brain.planner")


class PlannerEngine(PlanningProvider):
    """Motor de formulación y adaptación de planes estructurados para JESSYCA BRAIN 1.0."""

    def __init__(self, max_steps: int = 15, default_step_timeout: float = 30.0) -> None:
        self.max_steps = max_steps
        self.default_step_timeout = default_step_timeout

    def create_plan(
        self,
        comprehension: GoalComprehension,
        available_tools: list[str],
        constraints: dict[str, Any] | None = None,
    ) -> CanonicalPlan:
        """Formula un plan de ejecución estructurado y acíclico a partir de la comprensión del objetivo."""
        plan_id = f"plan-{uuid.uuid4().hex[:10]}"
        sub_goals = list(comprehension.sub_goals) if comprehension.sub_goals else [comprehension.normalized_goal]
        steps: list[CanonicalPlanStep] = []

        # Construir pasos secuenciales o interdependientes para cada submeta
        for idx, sub_goal in enumerate(sub_goals, start=1):
            if len(steps) >= self.max_steps:
                logger.warning(f"[PLANNER LIMIT] Se alcanzó el límite máximo de {self.max_steps} pasos.")
                break

            step_id = f"step-{idx}"
            action_name, tool_name, params = self._map_subgoal_to_action(sub_goal, comprehension.entities)

            # Dependencia del paso inmediatamente anterior si es secuencial
            dependencies = [f"step-{idx - 1}"] if idx > 1 else []

            # Detección de operaciones de riesgo que requieren confirmación
            requires_approval = any(
                w in sub_goal.lower() or w in str(params).lower()
                for w in ("borra", "elimina", "delete", "format", "destruye", "terminar proceso", "kill")
            )

            # Precondiciones necesarias
            preconditions = []
            if tool_name in ("notepad_writer", "browser_search") and idx > 1:
                preconditions.append("previous_step_completed")

            step = CanonicalPlanStep(
                step_id=step_id,
                action_name=action_name,
                tool_name=tool_name,
                parameters=params,
                description=sub_goal,
                dependencies=dependencies,
                preconditions=preconditions,
                expected_outcome=f"Completar exitosamente '{sub_goal}'",
                state=PlanStepExecutionState.PENDING,
                timeout_seconds=self.default_step_timeout,
                retry_limit=1 if not requires_approval else 0,  # Acciones irreversibles no se reintentan en bucle
                requires_approval=requires_approval,
            )
            steps.append(step)

        plan = CanonicalPlan(
            plan_id=plan_id,
            goal=comprehension.normalized_goal,
            steps=steps,
            created_at=time.time(),
            version=1,
            is_recovering=False,
            metadata={"constraints": constraints or {}, "sub_goals_count": len(sub_goals)},
        )

        # Validar el DAG del plan antes de retornar
        self.validate_dag(plan)
        return plan

    def replan(
        self,
        failed_step: CanonicalPlanStep,
        current_plan: CanonicalPlan,
        error_evidence: dict[str, Any],
    ) -> CanonicalPlan:
        """Genera un plan correctivo a partir de un paso fallido sin repetir lo ya completado."""
        new_plan_id = f"replan-{uuid.uuid4().hex[:8]}"
        new_steps: list[CanonicalPlanStep] = []

        for step in current_plan.steps:
            if step.step_id == failed_step.step_id:
                # Marcar el paso fallido
                failed_copy = CanonicalPlanStep(
                    step_id=step.step_id,
                    action_name=step.action_name,
                    tool_name=step.tool_name,
                    parameters=step.parameters,
                    description=step.description,
                    dependencies=step.dependencies,
                    preconditions=step.preconditions,
                    expected_outcome=step.expected_outcome,
                    state=PlanStepExecutionState.FAILED,
                    error=str(error_evidence.get("error", "Fallo de ejecución verificado")),
                    evidence=error_evidence,
                )
                new_steps.append(failed_copy)

                # Si es posible una acción de recuperación o alternativa
                recovery_step = self._generate_recovery_step(failed_copy, error_evidence)
                if recovery_step:
                    new_steps.append(recovery_step)
            elif step.state == PlanStepExecutionState.COMPLETED:
                # Conservar pasos ya completados intactos (INVARIANTE: No repetir acciones completadas)
                new_steps.append(step)
            else:
                # Pasos pendientes posteriores
                new_steps.append(step)

        replan_obj = CanonicalPlan(
            plan_id=new_plan_id,
            goal=current_plan.goal,
            steps=new_steps,
            created_at=time.time(),
            version=current_plan.version + 1,
            is_recovering=True,
            metadata={
                "original_plan_id": current_plan.plan_id,
                "replan_reason": f"Fallo en paso {failed_step.step_id}: {error_evidence.get('error')}",
            },
        )
        return replan_obj

    def validate_dag(self, plan: CanonicalPlan) -> bool:
        """Verifica que el plan no contenga dependencias circulares ni referencias inexistentes."""
        step_ids = {s.step_id for s in plan.steps}

        # 1. Verificar unicidad de IDs
        if len(step_ids) != len(plan.steps):
            raise ValueError("El plan contiene step_id duplicados.")

        # 2. Verificar que todas las dependencias existen
        for step in plan.steps:
            for dep in step.dependencies:
                if dep not in step_ids:
                    raise ValueError(f"El paso '{step.step_id}' depende de '{dep}', que no existe en el plan.")

        # 3. Detección de ciclos mediante orden topológico / DFS
        adj: dict[str, list[str]] = {s.step_id: [] for s in plan.steps}
        in_degree: dict[str, int] = {s.step_id: 0 for s in plan.steps}

        for step in plan.steps:
            for dep in step.dependencies:
                adj[dep].append(step.step_id)
                in_degree[step.step_id] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        visited_count = 0

        while queue:
            curr = queue.pop(0)
            visited_count += 1
            for neighbor in adj[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited_count != len(plan.steps):
            raise ValueError("El plan contiene una dependencia circular (Ciclo detectado en el DAG).")

        return True

    # ── MÉTODOS AUXILIARES DE TRADUCCIÓN A ACCIONES ──

    def _map_subgoal_to_action(
        self,
        subgoal: str,
        entities: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        """Mapea una submeta en texto hacia una acción formal, herramienta y parámetros."""
        gl = subgoal.lower()
        if re.search(r"\b(?:presenta|presentar|dame|elabora)\s+(?:las\s+)?conclusiones\b", gl):
            return "summarize_results", "cognitive_synthesis", {}
        explicit_file = re.search(r"\b([\w.-]+\.(?:txt|md))\b", subgoal)
        if explicit_file and re.search(r"\b(?:crea|crear|genera|generar)\b", gl) and "bloc" not in gl:
            return "create_file", "files_create", {
                "filename": explicit_file.group(1), "content_topic": subgoal,
            }

        # Control de volumen
        if "volumen" in gl or "audio" in gl or "silencia" in gl or "mute" in gl:
            level = 30
            action = "set_volume"
            if "baja" in gl:
                level = 20
                action = "lower_volume"
            elif "sube" in gl:
                level = 80
                action = "raise_volume"
            elif "silencia" in gl or "mute" in gl:
                level = 0
                action = "mute"
            return action, "system_audio", {"level": level, "action": action}

        # Structured local paths take precedence over keyword heuristics.
        if entities.get("action") in ("play_local_music", "play_local_media"):
            action = entities["action"]
            params = {"accion": action, "target_dir": entities["target_directory"],
                      "media_type": entities.get("media_type", "video")}
            if entities.get("file_path"):
                params["file_path"] = entities["file_path"]
            return action, "windows_media", params
        if entities.get("accion") == "abrir_carpeta":
            return "open_folder", "app_launcher", dict(entities)

        # 1. Reproducción de vídeos de baile ("Jessica, báilame" / play_random_video)
        if any(w in gl for w in ("bailame", "báilame", "un baile", "el baile", "pon un baile", "haz un baile", "baila para mi", "baila para mí")) or entities.get("action") == "play_random_video" or entities.get("is_dance"):
            target_d = entities.get("target_directory") or entities.get("target_dir") or r"D:\bailes de ia"
            return "play_random_video", "windows_media", {"accion": "play_random_video", "target_dir": str(target_d)}

        # 2. Reproducción multimedia local (vídeos o música en PC/disco/carpeta)
        if (any(w in gl for w in ("local", "locales", "computadora", "mi pc", "disco d", "disco c", "carpeta")) and any(v in gl for v in ("reproduce", "repreduce", "pon", "toca"))) or entities.get("is_local_media"):
            target_d = entities.get("target_directory") or entities.get("target_dir")
            if not target_d and "baile" in gl:
                target_d = r"D:\bailes de ia"
            elif not target_d and ("disco d" in gl or "d:" in gl):
                target_d = "D:\\"
            return "play_local_media", "windows_media", {"accion": "play_random_video", "target_dir": str(target_d or r"D:\bailes de ia")}

        # 3. Búsqueda de carpetas o archivos locales en disco (Filesystem Search)
        if any(w in gl for w in ("busca la carpeta", "buscar la carpeta", "busca la carpeta de", "busca el archivo", "buscar archivo", "busca en el disco", "busca en disco")) or ("carpeta" in gl and any(w in gl for w in ("busca", "buscar"))):
            folder_cand = "Bailes de IA" if "baile" in gl else (entities.get("search_target") or entities.get("target_folder") or "archivos")
            m_f = re.search(r"busca(?:r)?\s+(?:la\s+carpeta\s+(?:de\s+)?|el\s+archivo\s+(?:de\s+)?)(.+)", subgoal, flags=re.IGNORECASE)
            if m_f:
                folder_cand = m_f.group(1).strip()
            return "search_folder", "file_search", {"query": folder_cand, "path": entities.get("drive") or "D:\\"}

        # 4. Apertura de carpetas en Explorador de Windows
        if any(w in gl for w in ("abre la carpeta", "abrir la carpeta", "abre los videos", "abre el directorio", "muestra la carpeta", "abre la carpeta de")) or ("carpeta" in gl and any(w in gl for w in ("abre", "abrir"))):
            folder_cand = r"D:\bailes de ia" if "baile" in gl else (entities.get("target_folder") or ("D:\\" if "disco d" in gl or "d:" in gl else r"D:\bailes de ia"))
            return "open_folder", "app_launcher", {"app_name": "explorer", "target_folder": str(folder_cand), "accion": "abrir_carpeta"}

        # 5. YouTube y reproducción web
        if any(yt in gl for yt in ("youtube", "yo tuy", "yu tub", "yutub")) or (
            any(w in gl for w in ("reproduce", "repreduce", "pon música", "pon musica", "pon cancion", "pon canciones"))
            and not any(loc in gl for loc in ("local", "locales", "computadora", "pc", "disco", "carpeta", "baile", "bailame", "báilame"))
        ):
            query = "Mozart" if ("mozart" in gl or "mozar" in gl) else "música clásica"
            m_yt = re.search(r"(?:reproduce|repreduce|pon|busca)(?:\s+música\s+de|\s+musica\s+de|\s+videos?\s+de|\s+canciones?\s+de|\s+a)?\s+(.+)", subgoal, flags=re.IGNORECASE)
            if m_yt:
                extracted = m_yt.group(1).strip()
                if extracted and extracted.lower() not in ("youtube", "yo tuy", "yu tub"):
                    query = extracted
            elif entities.get("composer"):
                query = entities["composer"]
            elif entities.get("media_query"):
                query = entities["media_query"]
            return "play_youtube", "browser_youtube", {"query": query, "app_name": "youtube", "operacion": "play"}

        if re.search(r"\b(?:cierra|cerrar)\b", gl):
            app = entities.get("target_app") or re.sub(r"^.*?\b(?:cierra|cerrar)\s+(?:(?:el|la)\s+)?", "", subgoal, flags=re.IGNORECASE).strip()
            return "close_application", "app_launcher", {"app_name": app}

        # Abrir aplicaciones
        if any(w in gl for w in ("abre", "abrir", "inicia", "iniciar", "lanza", "lanzar")):
            # Comprobar si pide abrir YouTube
            if any(yt in gl for yt in ("youtube", "yo tuy", "yu tub", "yutub")):
                query = entities.get("composer") or entities.get("media_query") or "música"
                return "play_youtube", "browser_youtube", {"query": query, "app_name": "youtube", "operacion": "play"}

            known_apps = (
                "calculadora", "calc", "bloc de notas", "notepad", "chrome", "edge",
                "spotify", "word", "excel", "paint", "cmd", "terminal", "powershell",
                "whatsapp", "explorer", "explorador"
            )
            app_name = "desconocido"
            for app in known_apps:
                if app in gl:
                    app_name = app
                    break
            if app_name == "desconocido" and entities.get("target_app"):
                cand = entities["target_app"].lower()
                if any(cand == a or cand in a for a in known_apps):
                    app_name = cand
            elif app_name == "desconocido" and entities.get("normalized_app"):
                cand = entities["normalized_app"].lower()
                if any(cand == a or cand in a for a in known_apps):
                    app_name = cand

            if app_name == "desconocido":
                raw_cand = None
                m_raw = re.search(r"\b(?:abre|abrir|inicia|iniciar|lanza|lanzar)\s+(?:la\s+|el\s+)?([a-zA-Z0-9_\-]+)", subgoal, flags=re.IGNORECASE)
                if m_raw:
                    raw_cand = m_raw.group(1).lower().strip()

                # Frases truncadas o fragmentos acústicos corruptos (<= 2 caracteres, 'yo', 'yu', 'el', 'la'): aclaración obligatoria
                if not raw_cand or len(raw_cand) <= 2 or raw_cand in ("yo", "yu", "el", "la", "un", "una", "lo"):
                    return "clarification_needed", "system_tool", {
                        "error": "UnknownApp",
                        "instruction": subgoal,
                        "clarification": f"¿Podrías aclararme qué aplicación deseas abrir? No reconozco el programa en '{subgoal}'."
                    }
                # Si es un nombre explícito largo, intentar abrirlo para que apps_skill lo verifique contra catálogo y whitelist
                return "open_application", "app_launcher", {"app_name": raw_cand}
            return "open_application", "app_launcher", {"app_name": app_name}

        # Búsqueda web / Navegador
        if any(w in gl for w in ("busca", "buscar", "navega")) and not any(loc in gl for loc in ("carpeta", "archivo", "disco", "local")):
            query = ""
            m = re.search(r"(?:busca|buscar)(?:\s+información\s+sobre|\s+sobre)?\s+(.+)", subgoal, flags=re.IGNORECASE)
            if m:
                query = m.group(1).strip()
            elif entities.get("search_query"):
                query = entities["search_query"]
            return "browser_search", "browser_search", {"query": query or "Python"}

        # Investigación científica
        if any(w in gl for w in ("investiga", "investigar")):
            m = re.search(r"(?:investiga|investigar)(?:\s+qu[eé]\s+es|\s+sobre)?\s+(.+)", subgoal, flags=re.IGNORECASE)
            query = m.group(1).strip() if m else entities.get("search_query", "tema científico")
            return "research_topic", "academic_search", {"topic": query}

        # Guardar documento activo
        if any(w in gl for w in ("guarda", "guardar")):
            m_fn = re.search(r"(\b[\w\.-]+\.(?:txt|md|json|log)\b)", subgoal)
            target_file = m_fn.group(1) if m_fn else entities.get("save_filename", "documento.txt")
            return "save_document", "desktop_editor", {
                "app_name": "bloc de notas",
                "filename": target_file,
                "hwnd": entities.get("target_hwnd"),
            }

        # Selección de texto
        if any(w in gl for w in ("selecciona el texto", "seleccionar todo", "selecciona todo")):
            return "hotkey", "desktop_editor", {
                "keys": "ctrl+e",
                "app_name": "bloc de notas",
                "hwnd": entities.get("target_hwnd"),
            }

        # Crear archivo explícito en disco (filesystem)
        if any(w in gl for w in ("crea un archivo", "crear archivo", "crea archivo")):
            m_fn = re.search(r"(\b[\w\.-]+\.(?:txt|md|json|log)\b)", subgoal)
            target_file = m_fn.group(1) if m_fn else "documento.txt"
            return "create_file", "files_create", {"filename": target_file, "content": "Documento creado en el sistema."}

        # Corrección del usuario cuando reporta no ver el contenido escrito
        if any(w in gl for w in ("inspeccionar ventana", "reintentar escritura", "no veo lo que escribiste", "verificar e inspeccionar")):
            return "inspect_and_rewrite", "desktop_editor", {
                "app_name": "bloc de notas",
                "hwnd": entities.get("target_hwnd"),
                "mode": "write",
            }

        # Escribir o editar contenido dentro de una ventana de aplicación gráfica (Bloc de notas, editor)
        if any(w in gl for w in ("escribe", "escribir", "redacta", "prepara un resumen", "resumen", "agrega", "añade", "corrige", "conclusión", "párrafo")):
            mode = entities.get("editor_mode", "write")
            if any(w in gl for w in ("agrega", "añade", "conclusión", "al final")):
                mode = "append"
            elif any(w in gl for w in ("corrige", "modifica", "reemplaza")):
                mode = "replace"

            # Detectar si hay texto literal directo (ej: 'escribe: prueba de escritura de JESSYCA')
            literal_text = entities.get("writing_text")
            m_lit = re.search(r"escribe(?:\s*:\s*|\s+[\"'])(.+?)(?:[\"']|$)", subgoal, flags=re.IGNORECASE)
            if m_lit and not literal_text:
                cand = m_lit.group(1).strip().strip('"').strip("'")
                if cand.startswith(":"):
                    cand = cand[1:].strip()
                if cand and not any(w in cand.lower() for w in ("en el bloc", "los 3", "los tres", "principios", "termodinámica", "termodinamica", "resumen")):
                    literal_text = cand

            if literal_text and any(w in literal_text.lower() for w in ("los 3", "los tres", "principios", "termodinámica", "termodinamica", "resumen sobre")):
                literal_text = None

            topic = entities.get("writing_topic") or subgoal
            return "write_in_window", "desktop_editor", {
                "app_name": "bloc de notas",
                "text": literal_text,
                "content_topic": topic,
                "mode": mode,
                "hwnd": entities.get("target_hwnd"),
            }

        # Acción por defecto
        return "generic_execution", "system_tool", {"instruction": subgoal}

    def _generate_recovery_step(
        self,
        failed_step: CanonicalPlanStep,
        error_evidence: dict[str, Any],
    ) -> CanonicalPlanStep | None:
        """Genera un paso de recuperación o fallback inteligente."""
        err = str(error_evidence.get("error", "")).lower()

        # Si falló al abrir una app no encontrada, intentar búsqueda web alternativa
        if failed_step.action_name == "open_application" and ("not found" in err or "inexistente" in err or "no encontrada" in err):
            app = failed_step.parameters.get("app_name", "aplicación")
            return CanonicalPlanStep(
                step_id=f"{failed_step.step_id}_fallback_search",
                action_name="browser_search",
                tool_name="browser_search",
                parameters={"query": f"alternativas o descarga de {app}"},
                description=f"Buscar alternativa en navegador para {app}",
                dependencies=[],
                expected_outcome=f"Alternativas encontradas para {app}",
            )

        return None
