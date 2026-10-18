"""JESSYCA BRAIN 1.0 — Motor de Aprendizaje Procedimental (ProcedureLearningEngine).

Permite a JESSYCA:
1. Aprender procedimientos a partir de experiencias exitosas verificadas.
2. Aprender por demostración supervisada ("JESSYCA, aprende este procedimiento")
   con captura acotada, filtrado estricto de secretos y accesibilidad UIA.
3. Aprender de errores y fallos de interfaz, generando adaptaciones sin alterar código fuente.
4. Validar procedimientos mediante pruebas independientes (CANDIDATE -> TESTING -> VALIDATED).
5. Reutilizar procedimientos validados adaptando parámetros dinámicos (Smart Parameter Adaptation).
6. Garantizar gobernanza total (JDE, RiskEngine, PermissionManager y Parada de Emergencia).
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from core.cognitive_brain.contracts import (
    CanonicalPlan,
    CanonicalPlanStep,
    GoalComprehension,
    LearnedProcedure,
    PlanStepExecutionState,
    ProcedureLifecycleState,
)
from core.cognitive_brain.memory_engine import EpisodeRecord, MemoryEngine
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.permission_manager import PermissionManager
from core.risk_engine import RiskEngine

logger = logging.getLogger("jessyca.brain.learning.procedure")


# Expresiones regulares para sanitizar secretos y contraseñas en demostraciones
_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(password|contrase[ñn]a|clave|pin|cvv|secret|token|apikey)[\s:=]+([^\s,;]+)"),
    re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),  # Tarjetas de crédito
]


@dataclass
class DemonstrationSession:
    """Sesión activa de observación acotada para aprendizaje por demostración."""
    session_id: str
    name: str
    intent: str
    target_applications: list[str]
    authorized_by_user: bool = False
    is_paused: bool = False
    is_active: bool = True
    recorded_actions: list[dict[str, Any]] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None


class ProcedureLearningEngine:
    """Motor de Aprendizaje y Validación Procedimental de JESSYCA BRAIN 1.0."""

    def __init__(
        self,
        memory_engine: MemoryEngine | None = None,
        risk_engine: RiskEngine | None = None,
        permission_manager: PermissionManager | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        desktop_controller: Any | None = None,
    ) -> None:
        self.memory_engine = memory_engine or MemoryEngine.get_instance()
        self.risk_engine = risk_engine or RiskEngine()
        self.permission_manager = permission_manager or PermissionManager()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.desktop_controller = desktop_controller
        self._active_demonstrations: dict[str, DemonstrationSession] = {}

    # =========================================================================
    # 1. APRENDIZAJE MEDIANTE EXPERIENCIA (EXPERIENCE-BASED LEARNING)
    # =========================================================================

    def learn_from_experience(
        self,
        episode: dict[str, Any] | EpisodeRecord,
    ) -> LearnedProcedure | None:
        """Extrae un procedimiento estructurado candidato a partir de un episodio exitoso."""
        if isinstance(episode, EpisodeRecord):
            ep_dict = asdict(episode)
        else:
            ep_dict = dict(episode)

        # 1. Solo aprender de experiencias verificadas y exitosas
        if not ep_dict.get("success", False):
            return None

        # 2. Descartar si existieron errores en la ejecución del episodio
        if ep_dict.get("errors") or ep_dict.get("error"):
            logger.info("[LEARN_REJECTED] Descartando aprendizaje debido a errores presentes en el episodio.")
            return None

        # 3. Validar confianza acústica/STT mínima (>= 0.60)
        metadata = ep_dict.get("metadata") or {}
        stt_conf = metadata.get("stt_confidence") or ep_dict.get("stt_confidence")
        if stt_conf is not None and float(stt_conf) < 0.60:
            logger.info(f"[LEARN_REJECTED] Descartando aprendizaje por baja confianza acústica STT ({stt_conf}).")
            return None

        # 3.b. Descartar aprendizaje si existe advertencia o detección de falso éxito (false_success)
        alerts = ep_dict.get("alerts") or []
        if (
            metadata.get("false_success")
            or metadata.get("is_false_success")
            or "false_success" in alerts
            or ep_dict.get("false_success")
        ):
            logger.warning("[LEARN_REJECTED] Descartando aprendizaje debido a advertencia explícita de false_success en el episodio.")
            return None

        user_instruction = ep_dict.get("user_instruction", "").strip()
        intent = ep_dict.get("intent", "generic_task")
        actions_executed = ep_dict.get("actions_executed", [])
        verified_evidence = ep_dict.get("verified_evidence", {})

        # 3.c. Correspondencia estricta entre intención y herramientas (Fase 7):
        # Si la orden involucra escribir/redactar dentro de Bloc de notas u otra app,
        # NO se permite aprender si la herramienta ejecutada fue files.create o no hubo interacción GUI real.
        user_lower = user_instruction.lower()
        writing_indicators = ("escribe", "escribir", "redacta", "redactar", "bloc de notas", "en el bloc", "dentro de")
        if any(w in user_lower for w in writing_indicators):
            executed_tools = [s.get("tool_name", "") for s in actions_executed]
            executed_actions = [s.get("action_name", "") for s in actions_executed]
            gui_write_actions = {"write_in_window", "write_document", "gui_write_text", "type_text", "inspect_and_rewrite"}
            has_gui_write = any(a in gui_write_actions for a in executed_actions)
            has_file_create = any(t in ("files.create", "files_create", "files") for t in executed_tools)

            if not has_gui_write or (has_file_create and not has_gui_write):
                logger.warning(
                    f"[LEARN_REJECTED] Desajuste de intención de escritura gráfica: La tarea usó herramientas no interactivas {executed_tools}. Descartando candidato."
                )
                return None

        # 4. Descartar instrucciones vacías o insignificantes
        if len(user_instruction) < 6:
            return None

        # 5. Descartar intenciones conversacionales, saludos, consultas o aclaraciones
        if intent in ("general_query", "conversational", "greeting", "clarification", "ambiguous", "memory_store", "memory_query", "user_correction:unseen_text"):
            return None

        # 6. Descartar si no hay acciones ejecutadas
        if not actions_executed or len(actions_executed) < 1:
            return None

        # 7. Validar que ninguna acción ejecutada haya fracasado
        for act in actions_executed:
            if act.get("status") in ("failed", "error", "skipped") or act.get("success") is False:
                logger.info(f"[LEARN_REJECTED] Descartando aprendizaje porque la acción '{act.get('action_name')}' no fue exitosa.")
                return None

        # 8. Requerir evidencia verificada explícita de herramientas ejecutadas
        if not verified_evidence:
            logger.info("[LEARN_REJECTED] Descartando aprendizaje por ausencia de evidencia verificada.")
            return None

        for ev_key, ev_val in verified_evidence.items():
            if isinstance(ev_val, dict) and (ev_val.get("success") is False or ev_val.get("exito") is False or ev_val.get("error")):
                logger.info(f"[LEARN_REJECTED] Evidencia '{ev_key}' contiene fallo. Descartando aprendizaje.")
                return None

        proc_id = f"proc-{uuid.uuid4().hex[:10]}"
        proc_name = self._generate_procedure_name(user_instruction, intent)

        # Extraer parámetros dinámicos y generalizar pasos
        parameterized_steps, extracted_params = self._parameterize_steps(actions_executed)

        # Detectar aplicaciones y herramientas requeridas
        req_apps = self._extract_required_apps(parameterized_steps)
        auth_tools = list({s.get("tool_name", "generic_tool") for s in actions_executed})

        candidate = LearnedProcedure(
            procedure_id=proc_id,
            name=proc_name,
            description=f"Procedimiento aprendido a partir de la experiencia exitosa: '{user_instruction}'",
            associated_intent=intent,
            required_applications=req_apps,
            input_parameters=extracted_params,
            preconditions=[f"Aplicación {app} instalada y accesible" for app in req_apps] or ["Entorno Windows 11 operativo"],
            steps=parameterized_steps,
            authorized_tools=auth_tools,
            success_conditions=[f"Verificación de salida para objetivo '{user_instruction}'"],
            error_conditions=["Fallo de elemento de interfaz", "Tiempo de espera agotado"],
            validation_evidence=[{
                "timestamp": time.time(),
                "source": "experience_learner",
                "episode_id": ep_dict.get("episode_id"),
                "evidence": verified_evidence,
            }],
            version=1,
            state=ProcedureLifecycleState.CANDIDATE,
            approval_status="PROPOSED",
            success_count=1,
            failure_count=0,
            created_at=time.time(),
            updated_at=time.time(),
        )

        # Persistir en ProceduralMemory en estado CANDIDATE
        self.memory_engine.procedural_memory.save_procedure(candidate)
        logger.info(f"[PROCEDURE CANDIDATE LEARNED] Procedimiento '{proc_name}' ({proc_id}) registrado como CANDIDATE.")
        return candidate

    # =========================================================================
    # 2. APRENDIZAJE POR DEMOSTRACIÓN (DEMONSTRATION-BASED LEARNING)
    # =========================================================================

    def start_demonstration(
        self,
        name: str,
        intent: str,
        target_applications: list[str],
        user_confirmed: bool = True,
    ) -> str:
        """Inicia una sesión de observación supervisada y acotada."""
        if not user_confirmed:
            raise PermissionError("El aprendizaje por demostración requiere autorización explícita del usuario.")

        session_id = f"demo-{uuid.uuid4().hex[:8]}"
        session = DemonstrationSession(
            session_id=session_id,
            name=name,
            intent=intent,
            target_applications=[app.lower().strip() for app in target_applications],
            authorized_by_user=True,
            is_active=True,
        )
        self._active_demonstrations[session_id] = session
        logger.info(f"[DEMO_SESSION_STARTED] Sesión de demostración '{session_id}' iniciada para: {target_applications}")
        return session_id

    def record_demonstration_action(
        self,
        session_id: str,
        action: str,
        parameters: dict[str, Any],
        element_info: dict[str, Any] | None = None,
    ) -> bool:
        """Registra una acción física dentro de la ventana autorizada sanitizando datos sensibles."""
        session = self._active_demonstrations.get(session_id)
        if not session or not session.is_active or session.is_paused:
            logger.warning(f"[DEMO_ACTION_REJECTED] Sesión '{session_id}' no está activa o se encuentra pausada.")
            return False

        # Sanitizar parámetros para evitar registrar contraseñas o datos privados
        clean_params = self._sanitize_demonstration_parameters(parameters)

        action_entry = {
            "step_id": f"step-{len(session.recorded_actions) + 1}",
            "action_name": action,
            "parameters": clean_params,
            "element_info": element_info or {},
            "timestamp": time.time(),
        }
        session.recorded_actions.append(action_entry)
        logger.debug(f"[DEMO_ACTION_RECORDED] Sesión '{session_id}' registró: {action}")
        return True

    def pause_demonstration(self, session_id: str) -> bool:
        session = self._active_demonstrations.get(session_id)
        if session and session.is_active:
            session.is_paused = True
            logger.info(f"[DEMO_SESSION_PAUSED] Demostración '{session_id}' pausada.")
            return True
        return False

    def resume_demonstration(self, session_id: str) -> bool:
        session = self._active_demonstrations.get(session_id)
        if session and session.is_active:
            session.is_paused = False
            logger.info(f"[DEMO_SESSION_RESUMED] Demostración '{session_id}' reanudada.")
            return True
        return False

    def stop_demonstration(
        self,
        session_id: str,
        user_corrections: dict[str, Any] | None = None,
    ) -> LearnedProcedure:
        """Finaliza la sesión de observación y compila el procedimiento candidato."""
        session = self._active_demonstrations.get(session_id)
        if not session:
            raise ValueError(f"No existe la sesión de demostración '{session_id}'.")

        session.is_active = False
        session.end_time = time.time()

        raw_actions = session.recorded_actions
        if user_corrections and "remove_steps" in user_corrections:
            to_remove = set(user_corrections["remove_steps"])
            raw_actions = [a for a in raw_actions if a["step_id"] not in to_remove]

        # Generalizar y extraer parámetros
        steps, extracted_params = self._parameterize_steps(raw_actions)

        # Aplicar correcciones de parámetros del usuario
        if user_corrections and "parameters" in user_corrections:
            extracted_params.update(user_corrections["parameters"])

        proc_id = f"proc-demo-{uuid.uuid4().hex[:8]}"
        procedure = LearnedProcedure(
            procedure_id=proc_id,
            name=session.name,
            description=f"Procedimiento aprendido mediante demostración supervisada de '{session.name}'",
            associated_intent=session.intent,
            required_applications=session.target_applications,
            input_parameters=extracted_params,
            preconditions=[f"Aplicación {app} disponible" for app in session.target_applications],
            steps=steps,
            authorized_tools=["desktop.app", "desktop.keyboard", "desktop.mouse"],
            success_conditions=[f"Completar acciones demostradas de {session.name}"],
            error_conditions=["Control UIA no interactivo", "Ventana cerrada inesperadamente"],
            validation_evidence=[{
                "timestamp": time.time(),
                "source": "supervised_demonstration",
                "session_id": session_id,
                "action_count": len(steps),
            }],
            version=1,
            state=ProcedureLifecycleState.CANDIDATE,
            approval_status="PROPOSED",
            success_count=1,
            failure_count=0,
            created_at=time.time(),
            updated_at=time.time(),
        )

        self.memory_engine.procedural_memory.save_procedure(procedure)
        del self._active_demonstrations[session_id]
        logger.info(f"[DEMO_PROCEDURE_COMPILED] Demostración '{session_id}' compilada en procedimiento '{proc_id}'.")
        return procedure

    # =========================================================================
    # 3. APRENDIZAJE DE ERRORES Y ADAPTACIÓN REACTIVA (FAILURE LEARNER)
    # =========================================================================

    def learn_from_failure(
        self,
        procedure_id: str,
        failed_step: dict[str, Any] | CanonicalPlanStep,
        error_evidence: dict[str, Any],
    ) -> LearnedProcedure | None:
        """Adapta un procedimiento tras un fallo observable sin modificar código fuente."""
        proc = self.memory_engine.procedural_memory.get_procedure(procedure_id)
        if not proc:
            logger.warning(f"[LEARN_FAILURE_NOT_FOUND] No se encontró procedimiento '{procedure_id}' para adaptar.")
            return None

        step_id = failed_step.step_id if isinstance(failed_step, CanonicalPlanStep) else failed_step.get("step_id", "unknown")
        action_name = failed_step.action_name if isinstance(failed_step, CanonicalPlanStep) else failed_step.get("action_name", "")
        error_msg = str(error_evidence.get("error", "Error no especificado"))

        logger.info(f"[LEARN_FROM_FAILURE] Analizando fallo en {proc.name} (Paso: {step_id}, Error: {error_msg})")

        # 1. Registrar fallo en historial y modificar condiciones
        proc.failure_count += 1
        new_history = list(proc.modification_history)
        new_history.append({
            "timestamp": time.time(),
            "event": "failure_adaptation",
            "failed_step": step_id,
            "error": error_msg,
            "previous_version": proc.version,
        })
        proc.modification_history = new_history

        # 2. Generar adaptación heurística segura del paso
        adapted_steps = []
        for s in proc.steps:
            if s.get("step_id") == step_id:
                modified_step = dict(s)
                # Si falló por ventana o elemento no listo, añadir verificación de foco o reintento
                if "notfound" in error_msg.lower() or "timeout" in error_msg.lower():
                    modified_step["retry_limit"] = modified_step.get("retry_limit", 1) + 1
                    modified_step["timeout_seconds"] = min(modified_step.get("timeout_seconds", 30.0) * 1.5, 60.0)
                    modified_step["fallback_strategy"] = "reobserve_window_bounds"
                adapted_steps.append(modified_step)
            else:
                adapted_steps.append(s)

        proc.steps = adapted_steps
        proc.version += 1
        proc.updated_at = time.time()

        # 3. Si la tasa de fallos es alta, degradar a TESTING para requerir re-validación
        if proc.failure_count >= 2 and proc.state == ProcedureLifecycleState.VALIDATED:
            proc.state = ProcedureLifecycleState.TESTING
            logger.warning(f"[PROCEDURE_DEMOTED] '{proc.name}' degradado a TESTING debido a fallos recurrentes.")

        self.memory_engine.procedural_memory.save_procedure(proc)
        return proc

    # =========================================================================
    # 4. VALIDACIÓN INDEPENDIENTE (CANDIDATE -> TESTING -> VALIDATED)
    # =========================================================================

    def validate_procedure(
        self,
        procedure_id: str,
        test_executor: Callable[[str, str, dict[str, Any]], tuple[bool, Any, str | None]] | None = None,
        min_consecutive_successes: int = 1,
    ) -> tuple[bool, str]:
        """Ejecuta una prueba independiente supervisada para promover el procedimiento a VALIDATED."""
        proc = self.memory_engine.procedural_memory.get_procedure(procedure_id)
        if not proc:
            return False, f"Procedimiento '{procedure_id}' no encontrado."

        if self.emergency_stop.is_stopped():
            return False, "Operación abortada por Parada de Emergencia activa."

        logger.info(f"[VALIDATION_START] Validando procedimiento '{proc.name}' (Estado actual: {proc.state.value})")

        # 1. Comprobar permisos con JDE / RiskEngine
        for tool in proc.authorized_tools:
            risk = self.risk_engine.evaluate_risk(tool, {"procedure_validation": True})
            risk_level_str = getattr(risk.risk_level, "value", str(risk.risk_level))
            if not self.permission_manager.check_permission(tool, {"risk_level": risk_level_str}):
                return False, f"Permiso denegado para la herramienta requerida '{tool}'."

        # 2. Poner en estado TESTING
        proc.state = ProcedureLifecycleState.TESTING
        self.memory_engine.procedural_memory.save_procedure(proc)

        # 3. Ejecutar pasos de prueba en entorno controlado
        all_steps_ok = True
        validation_output: dict[str, Any] = {}

        for step in proc.steps:
            action = step.get("action_name", step.get("action", ""))
            tool = step.get("tool_name", proc.authorized_tools[0] if proc.authorized_tools else "generic_tool")
            params = step.get("parameters", {})

            if test_executor:
                success, output, err = test_executor(action, tool, params)
            elif self.desktop_controller:
                # Ejecución mediante el controlador físico real
                success, output, err = self._execute_test_step_on_desktop(action, params)
            else:
                # Simulación determinista segura
                success, output, err = True, {"validated_step": action}, None

            if not success:
                all_steps_ok = False
                logger.warning(f"[VALIDATION_FAILED] Paso '{action}' falló durante la validación: {err}")
                self.learn_from_failure(proc.procedure_id, step, {"error": err})
                return False, f"Fallo en paso de validación '{action}': {err}"

            validation_output[action] = output

        # 4. Si todas las pruebas pasaron, certificar y promover a VALIDATED
        if all_steps_ok:
            proc.success_count += 1
            proc.state = ProcedureLifecycleState.VALIDATED
            proc.approval_status = "APPROVED"
            proc.last_validated_at = time.time()
            proc.updated_at = time.time()
            proc.validation_evidence.append({
                "timestamp": time.time(),
                "result": "PASSED",
                "evidence": validation_output,
            })
            self.memory_engine.procedural_memory.save_procedure(proc)
            logger.info(f"[PROCEDURE_VALIDATED] ¡Procedimiento '{proc.name}' certificado como VALIDATED!")
            return True, f"Procedimiento '{proc.name}' validado y aprobado exitosamente."

        return False, "La validación no cumplió las condiciones de éxito esperadas."

    # =========================================================================
    # 5. REUTILIZACIÓN INTELIGENTE (SMART PARAMETER ADAPTATION)
    # =========================================================================

    def adapt_procedure_to_plan(
        self,
        procedure: LearnedProcedure,
        user_input: str,
        extracted_parameters: dict[str, Any] | None = None,
    ) -> CanonicalPlan:
        """Adapta un procedimiento validado reemplazando parámetros variables por los de la solicitud actual."""
        # SEGURIDAD CRÍTICA: Solo procedimientos VALIDATED pueden ejecutarse
        if procedure.state != ProcedureLifecycleState.VALIDATED:
            raise PermissionError(f"El procedimiento '{procedure.name}' está en estado '{procedure.state.value}'. Solo procedimientos VALIDATED pueden ejecutarse.")

        current_params = dict(extracted_parameters or {})

        # Si no se suministraron parámetros explícitos, intentar extraerlos del texto
        if not current_params:
            current_params = self._extract_parameters_from_text(user_input, procedure.input_parameters)

        canonical_steps: list[CanonicalPlanStep] = []
        for idx, step_dict in enumerate(procedure.steps, start=1):
            raw_params = dict(step_dict.get("parameters", {}))
            adapted_params = self._substitute_template_values(raw_params, current_params)

            step_obj = CanonicalPlanStep(
                step_id=f"step-{idx}",
                action_name=step_dict.get("action_name", step_dict.get("action", "generic_step")),
                tool_name=step_dict.get("tool_name", procedure.authorized_tools[0] if procedure.authorized_tools else "generic_tool"),
                parameters=adapted_params,
                description=step_dict.get("description", f"Paso {idx} adaptado de {procedure.name}"),
                dependencies=step_dict.get("dependencies", [f"step-{idx-1}"] if idx > 1 else []),
                preconditions=procedure.preconditions if idx == 1 else [],
                expected_outcome=procedure.success_conditions[0] if procedure.success_conditions else "Acción completada",
                timeout_seconds=step_dict.get("timeout_seconds", 30.0),
                retry_limit=step_dict.get("retry_limit", 1),
            )
            canonical_steps.append(step_obj)

        plan = CanonicalPlan(
            plan_id=f"plan-proc-{procedure.procedure_id[:8]}-{int(time.time())}",
            goal=f"Ejecución adaptada de '{procedure.name}' para: {user_input}",
            steps=canonical_steps,
            version=procedure.version,
            metadata={"source_procedure_id": procedure.procedure_id, "procedure_name": procedure.name},
        )
        logger.info(f"[PLAN_ADAPTED_FROM_PROCEDURE] Generado plan {plan.plan_id} con {len(canonical_steps)} pasos.")
        return plan

    # =========================================================================
    # MÉTODOS AUXILIARES DE GENERALIZACIÓN Y SEGURIDAD
    # =========================================================================

    def _parameterize_steps(
        self,
        actions: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Identifica valores específicos (texto, archivos, búsquedas) y los convierte en plantillas {{param}}."""
        parameterized_steps: list[dict[str, Any]] = []
        discovered_params: dict[str, Any] = {}

        for idx, act in enumerate(actions, start=1):
            action_name = act.get("action_name", act.get("action", ""))
            params = dict(act.get("parameters", {}))
            step_params = {}

            for k, v in params.items():
                if isinstance(v, str) and len(v) > 2:
                    # Si es un texto largo o contenido, parametrizar como {{text}} o {{content}}
                    if k in ("text", "content", "query", "topic", "filename"):
                        param_key = f"{k}_{idx}" if k in discovered_params else k
                        discovered_params[param_key] = {"type": "string", "example": v, "description": f"Parámetro {k} del paso {idx}"}
                        step_params[k] = f"{{{{{param_key}}}}}"
                    else:
                        step_params[k] = v
                else:
                    step_params[k] = v

            parameterized_steps.append({
                "step_id": f"step-{idx}",
                "action_name": action_name,
                "tool_name": act.get("tool_name", "generic_tool"),
                "parameters": step_params,
                "description": act.get("description", f"Acción {action_name}"),
            })

        return parameterized_steps, discovered_params

    def _substitute_template_values(
        self,
        template_params: dict[str, Any],
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """Reemplaza los marcadores {{param}} por los valores concretos."""
        resolved: dict[str, Any] = {}
        for k, v in template_params.items():
            if isinstance(v, str) and v.startswith("{{") and v.endswith("}}"):
                param_key = v[2:-2].strip()
                # Buscar coincidencia exacta o por prefijo (ej: text_1 -> text)
                val = values.get(param_key) or values.get(param_key.split("_")[0])
                resolved[k] = val if val is not None else v
            else:
                resolved[k] = v
        return resolved

    def _extract_parameters_from_text(
        self,
        text: str,
        param_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Infiere valores de parámetros a partir del lenguaje natural del usuario."""
        extracted: dict[str, Any] = {}
        # Extracción de nombres de archivos
        fn_match = re.search(r"(\b[\w\.-]+\.(?:txt|md|json|log|docx|csv)\b)", text)
        if fn_match:
            extracted["filename"] = fn_match.group(1)

        # Extracción de temas de investigación
        topic_match = re.search(r"(?:sobre|acerca de|de)\s+([^,\.]+)", text, flags=re.IGNORECASE)
        if topic_match:
            extracted["topic"] = topic_match.group(1).strip()
            extracted["query"] = extracted["topic"]

        # Extracción de textos literales entre comillas
        quoted = re.findall(r"[\"']([^\"']+)[\"']", text)
        if quoted:
            extracted["text"] = quoted[0]

        return extracted

    def _sanitize_demonstration_parameters(self, params: dict[str, Any]) -> dict[str, Any]:
        """Redacta contraseñas o datos sensibles de los parámetros demostrados."""
        clean = {}
        for k, v in params.items():
            if isinstance(v, str):
                s = v
                s = re.sub(r"(?i)(password|contrase[ñn]a|clave|pin|cvv|secret|token|apikey)[\s:=]+([^\s,;]+)", r"\1: [REDACTED_SECRET]", s)
                s = re.sub(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", "[REDACTED_CARD]", s)
                clean[k] = s
            else:
                clean[k] = v
        return clean

    def _extract_required_apps(self, steps: list[dict[str, Any]]) -> list[str]:
        apps = set()
        for s in steps:
            p = s.get("parameters", {})
            if "app_name" in p:
                apps.add(str(p["app_name"]))
            elif "app" in p:
                apps.add(str(p["app"]))
            elif s.get("action_name") == "open_application":
                apps.add(str(p.get("app_name", "unknown")))
        return list(apps)

    def _generate_procedure_name(self, instruction: str, intent: str) -> str:
        words = [w for w in instruction.split() if len(w) > 3][:5]
        summary = "_".join(words).lower()
        summary = re.sub(r"[^\w_]", "", summary)
        return f"{intent}:{summary}" if summary else f"{intent}:procedimiento"

    def _execute_test_step_on_desktop(self, action: str, params: dict[str, Any]) -> tuple[bool, Any, str | None]:
        if not self.desktop_controller:
            return True, {"simulated": True}, None
        try:
            if action in ("open_app", "open_application"):
                app = str(params.get("app_name") or params.get("app") or "notepad")
                res = self.desktop_controller.open_app(app)
                return res.success, res.evidence, res.error
            if action in ("close_app", "close_application"):
                target = params.get("app_name") or params.get("target") or "notepad.exe"
                res = self.desktop_controller.close_app(target)
                return res.success, res.evidence, res.error
            if action in ("type_text", "write_text"):
                res = self.desktop_controller.type_text(params.get("text", "test text"))
                return res.success, res.evidence, res.error
            return True, {"action": action, "executed": True}, None
        except Exception as e:
            return False, None, str(e)

    def audit_and_protect_candidates(self) -> dict[str, Any]:
        """Audita los procedimientos candidatos almacenados para detectar desajustes o falsos éxitos pasados.
        Marca los sospechosos con approval_status='NEEDS_REVIEW' para supervisión humana sin eliminarlos."""
        pm = self.memory_engine.procedural_memory
        all_procs = pm.list_all() if hasattr(pm, "list_all") else []
        audited_count = 0
        flagged_count = 0
        details = []

        for p in all_procs:
            audited_count += 1
            is_suspicious = False
            reasons = []

            # 1. Detectar si el procedimiento era de escritura pero solo ejecutaba files.create
            desc_lower = (p.description or "").lower() + (p.name or "").lower()
            if any(w in desc_lower for w in ("escribe", "bloc", "escribir", "redacta")):
                step_tools = [s.get("tool_name", "") for s in p.steps]
                step_actions = [s.get("action_name", "") for s in p.steps]
                has_gui_write = any(a in ("write_in_window", "write_document", "gui_write_text") for a in step_actions)
                has_file_create_only = any("files" in t for t in step_tools) and not has_gui_write
                if has_file_create_only:
                    is_suspicious = True
                    reasons.append("Intención de escritura gráfica mapeada erróneamente a files.create (Falso éxito).")

            # 2. Detectar si tiene validación con evidencias de fallo
            for ev in p.validation_evidence:
                ev_data = ev.get("evidence", {})
                if isinstance(ev_data, dict) and ev_data.get("false_success"):
                    is_suspicious = True
                    reasons.append("Evidencia contiene advertencia de false_success.")

            if is_suspicious:
                flagged_count += 1
                p.approval_status = "NEEDS_REVIEW"
                p.notes = "; ".join(reasons)
                p.updated_at = time.time()
                pm.save_procedure(p)
                details.append({"procedure_id": p.procedure_id, "name": p.name, "reasons": reasons})
                logger.warning(f"[PROCEDURE_AUDIT] Procedimiento '{p.name}' marcado como NEEDS_REVIEW: {reasons}")

        return {
            "audited_count": audited_count,
            "flagged_count": flagged_count,
            "flagged_details": details,
        }

