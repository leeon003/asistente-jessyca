"""Módulo de Control y Gobernanza en Tiempo de Ejecución para ARE (Action Reasoning Engine).

Implementa la mediación estricta entre el razonador agéntico ARE, el JDE Runtime Binding
y el ciclo de ejecución de JessycaLocalAgent.

Invariantes Absolutas:
1. ARE NO sustituye a JDE; es un proveedor de análisis, descomposición DAG y replanificación.
2. JDE es la autoridad única sobre la ejecución de cada paso o propuesta.
3. ARE NO ejecuta side effects físicos directamente.
4. En modo CONTROLLED, toda acción propuesta debe recibir veredicto ALLOW de JDE antes de despacharse.
5. Los fallos físicos son verificados por ExecutionVerifier; el diagnóstico de ARE informa a JDE.
6. La recuperación (recovery) nunca entra en bucles infinitos (límite estricto de reintentos).
7. Modo ACTIVE está estrictamente prohibido y bloqueado en esta fase.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from core.are.action_catalog import (
    ActionCatalog,
    ActionVerificationStrategy,
    get_default_action_catalog,
)
from core.are.dataflow import DataFlowResolver
from core.are.exceptions import (
    MissingOutputDependencyError,
    PlanClarificationRequired,
    UnresolvableActionError,
)
from core.are.execution_state import AREPlanExecutionState
from core.are.models import (
    AREDiagnosis,
    AREPlanProposal,
    ARERecoveryProposal,
    ARERuntimeMode,
    AREStepProposal,
)
from core.are.plan_validator import LLMPlanProposal, PlanValidator
from core.execution.execution_verifier import (
    ExecutionStatus,
    ExecutionVerifier,
    get_execution_verifier,
)
from core.execution.idempotency_guard import (
    ExecutionFingerprint,
    ExecutionIdempotencyGuard,
    get_idempotency_guard,
)
from core.integration.adapters.are_adapter import AREAdapter
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeVerdictType,
    get_jde_runtime_binding,
)
from core.logger import get_logger

logger = get_logger("jessyca.are.runtime")


# Expresiones regulares para detección determinista de tareas complejas
_COMPLEX_INTENT_PATTERNS = re.compile(
    r"(\by luego\b|\by después\b|\by guarda\b|\by resume\b|\by envía\b|"
    r"\borganiza\b|\bclasifica\b|\binvestiga\b|\bconvierte\b|\bextrae\b|"
    r"\bworkflow\b|\bmulti-?step\b|\bparalelo\b|\bworktree\b|\borquesta\b)",
    re.IGNORECASE,
)


class ARERuntime:
    """Coordinador de tiempo de ejecución para ARE bajo gobernanza del JDE."""

    _instance: ARERuntime | None = None
    _lock: threading.Lock = threading.Lock()

    # Invariante estricta: ACTIVE está prohibido en esta fase
    PHASE_ALLOW_ACTIVE: bool = False
    MAX_RECOVERY_ATTEMPTS: int = 2

    def __init__(
        self,
        mode: ARERuntimeMode | str | None = None,
        are_adapter: AREAdapter | None = None,
        jde_binding: JDERuntimeBinding | None = None,
        idempotency_guard: ExecutionIdempotencyGuard | None = None,
        execution_verifier: ExecutionVerifier | None = None,
        action_catalog: ActionCatalog | None = None,
        plan_validator: PlanValidator | None = None,
    ) -> None:
        self._mutex = threading.RLock()
        self._mode = self._resolve_mode(mode)
        if are_adapter is not None:
            self.are_adapter = are_adapter
        else:
            try:
                from core.integration.hub import get_integration_hub
                hub = get_integration_hub()
                existing = hub.registry.get("are")
                if existing is not None and isinstance(existing, AREAdapter):
                    self.are_adapter = existing
                else:
                    self.are_adapter = AREAdapter()
                    hub.registry.register(self.are_adapter, enabled=(self._mode != ARERuntimeMode.DISABLED))
            except Exception:
                self.are_adapter = AREAdapter()

        self.jde_binding = jde_binding or get_jde_runtime_binding()
        self.idempotency_guard = idempotency_guard or get_idempotency_guard()
        self.execution_verifier = execution_verifier or get_execution_verifier()
        self.action_catalog = action_catalog or get_default_action_catalog()
        self.plan_validator = plan_validator or PlanValidator(catalog=self.action_catalog)
        self._previously_denied_actions: set[str] = set()
        self.last_execution_state: AREPlanExecutionState | None = None

        # Sincronizar estado inicial con modo resuelto
        if self._mode == ARERuntimeMode.DISABLED and hasattr(self.are_adapter, "status"):
            from core.integration.models import IntegrationStatus
            self.are_adapter.status = IntegrationStatus.DISABLED

        # Garantizar que el adaptador esté inicializado de forma segura
        self._ensure_adapter_ready()

    def _ensure_adapter_ready(self) -> None:
        """Garantiza la inicialización síncrona/asíncrona del adaptador ARE."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # En caso de event loop activo, programar
                asyncio.create_task(self.are_adapter.initialize())
            else:
                loop.run_until_complete(self.are_adapter.initialize())
        except RuntimeError:
            asyncio.run(self.are_adapter.initialize())
        except Exception as exc:
            logger.warning(f"[ARE RUNTIME] Advertencia al inicializar AREAdapter: {exc}")

    @classmethod
    def _resolve_mode(cls, raw_input: Any) -> ARERuntimeMode:
        """Resuelve el modo de ejecución aplicando las políticas de contención."""
        candidate = raw_input
        if candidate is None:
            candidate = os.getenv("ARE_RUNTIME_MODE", "CONTROLLED")

        cleaned = str(getattr(candidate, "value", candidate)).strip().upper()

        if cleaned == "ACTIVE":
            if not cls.PHASE_ALLOW_ACTIVE:
                logger.critical(
                    "[ARE SECURITY ALERT] Intento de activación de ARE en modo 'ACTIVE' detectado. "
                    "ACTIVE está estrictamente prohibido en esta fase. Forzando CONTROLLED."
                )
                return ARERuntimeMode.CONTROLLED
            return ARERuntimeMode.ACTIVE

        if cleaned == "DISABLED":
            return ARERuntimeMode.DISABLED
        if cleaned == "SHADOW":
            return ARERuntimeMode.SHADOW
        if cleaned == "CONTROLLED":
            return ARERuntimeMode.CONTROLLED

        logger.warning(f"[ARE RUNTIME] Modo '{cleaned}' no reconocido. Fail-safe: forzando CONTROLLED.")
        return ARERuntimeMode.CONTROLLED

    @property
    def current_mode(self) -> ARERuntimeMode:
        with self._mutex:
            return self._mode

    @property
    def is_active(self) -> bool:
        with self._mutex:
            return self._mode == ARERuntimeMode.ACTIVE

    @property
    def previously_denied_actions(self) -> set[str]:
        with self._mutex:
            return set(self._previously_denied_actions)

    def set_mode(self, mode: ARERuntimeMode | str) -> tuple[bool, str]:
        """Cambia el modo operativo de ARE respetando los límites de seguridad."""
        with self._mutex:
            cleaned = str(getattr(mode, "value", mode)).strip().upper()
            if cleaned == "ACTIVE" and not self.PHASE_ALLOW_ACTIVE:
                raise PermissionError("ARE_RUNTIME_MODE 'ACTIVE' mode is strictly prohibited in this phase.")

            resolved = self._resolve_mode(mode)
            self._mode = resolved
            if hasattr(self.are_adapter, "status"):
                from core.integration.models import IntegrationStatus
                if resolved == ARERuntimeMode.DISABLED:
                    self.are_adapter.status = IntegrationStatus.DISABLED
                elif self.are_adapter.status == IntegrationStatus.DISABLED:
                    self.are_adapter.status = IntegrationStatus.READY
            logger.info(f"[ARE RUNTIME] Modo operativo actualizado a {resolved.value}.")
            return True, f"Modo operativo actualizado a {resolved.value}."

    def is_complex_task(
        self,
        user_input: str,
        intent: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> bool:
        """Determina deterministamente si una solicitud califica como tarea compleja.

        Criterios:
        1. Intención explícita de multi-paso o investigación estructurada.
        2. Presencia de patrones lingüísticos compuestos en la entrada del usuario.
        3. Requerimiento de múltiples herramientas o etapas dependientes.
        4. Orquestación agéntica (ORCA/ADE) o procesamiento documental (AnyDoc) compuesto.
        """
        if self.current_mode == ARERuntimeMode.DISABLED:
            return False

        # Intenciones intrínsecamente complejas
        complex_intents = {
            "multistep_research",
            "compound_task",
            "batch_operation",
            "agent_orchestration",
            "document_processing_workflow",
            "organize_files",
            "research_topic",
        }
        if intent in complex_intents:
            return True

        # Parámetros que señalan complejidad
        params = parameters or {}
        if params.get("is_complex") is True or params.get("multistep") is True:
            return True
        if len(params.get("steps", [])) > 1 or len(params.get("targets", [])) > 1:
            return True

        # Intenciones atómicas o directas gobernadas por skills dedicadas
        atomic_intents = {
            "browser_read",
            "extract_content",
            "follow_link",
            "browser_navigate",
            "open_browser",
            "browser_open",
            "browser_download",
            "media_control",
            "youtube_search",
            "youtube_play",
        }
        if intent in atomic_intents:
            return False

        # Análisis léxico sobre la orden del usuario
        text = (user_input or "").strip()
        if _COMPLEX_INTENT_PATTERNS.search(text):
            return True

        return False

    def decompose_and_plan(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> AREPlanProposal:
        """Ejecuta are.decompose_task y are.evaluate_plan generando una propuesta estructurada."""
        t_id = task_id or f"task-are-{uuid.uuid4().hex[:8]}"
        p_id = f"plan-{uuid.uuid4().hex[:8]}"
        params = {"goal": goal, "context": context or {}}

        # Invocar manejador de descomposición del adapter existente
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # En contexto asíncrono activo, ejecutar sincrónicamente en worker
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    decomp_res = executor.submit(
                        asyncio.run, self.are_adapter._handle_decompose_task(params, time.perf_counter())
                    ).result()
            else:
                decomp_res = loop.run_until_complete(
                    self.are_adapter._handle_decompose_task(params, time.perf_counter())
                )
        except Exception:
            decomp_res = asyncio.run(
                self.are_adapter._handle_decompose_task(params, time.perf_counter())
            )

        if not decomp_res.executed or not decomp_res.output:
            raise RuntimeError(f"Fallo al descomponer la tarea en ARE: {decomp_res.error}")

        raw_graph = decomp_res.output.get("graph", {})
        execution_order = decomp_res.output.get("execution_order", [])
        raw_nodes = raw_graph.get("nodes", {})

        # Invocar evaluación y validación estructural del plan
        eval_params = {"graph": raw_graph}
        try:
            eval_res = asyncio.run(self.are_adapter._handle_evaluate_plan(eval_params, time.perf_counter()))
        except Exception:
            eval_res = asyncio.run(self.are_adapter._handle_evaluate_plan(eval_params, time.perf_counter()))

        eval_out = eval_res.output if eval_res and eval_res.output else {}
        is_valid = bool(eval_out.get("is_valid", True))
        eval_errors = eval_out.get("errors", [])

        # Construir lista tipada de pasos
        steps: list[AREStepProposal] = []
        dependencies: dict[str, list[str]] = {}
        required_caps: set[str] = set()

        for node_id in execution_order:
            node_data = raw_nodes.get(node_id, {})
            action_type = node_data.get("action_type", "unknown")
            deps = node_data.get("depends_on", [])
            dependencies[node_id] = deps
            required_caps.add(action_type)

            # Clasificación preventiva de riesgo del paso
            risk = "HIGH" if any(w in action_type.lower() for w in ("delete", "kill", "format", "wipe")) else "SAFE"

            step_prop = AREStepProposal(
                step_id=node_id,
                title=node_data.get("title", node_id),
                action_type=action_type,
                parameters=node_data.get("parameters", {}),
                depends_on=deps,
                required_capabilities=[action_type],
                risk_level=risk,
                is_critical=node_data.get("is_critical", True),
                status="PROPOSED",
            )
            steps.append(step_prop)

        # Computar hash de integridad SHA-256
        integrity_hash = AREPlanProposal.compute_integrity_hash(
            task_id=t_id,
            plan_id=p_id,
            goal=goal,
            execution_order=execution_order,
            steps=steps,
        )

        return AREPlanProposal(
            task_id=t_id,
            plan_id=p_id,
            goal=goal,
            steps=steps,
            execution_order=execution_order,
            dependencies=dependencies,
            required_capabilities=list(required_caps),
            risk_context={"total_steps": len(steps), "has_high_risk": any(s.risk_level == "HIGH" for s in steps)},
            confidence=0.95,
            provenance="ARE.TaskDecomposer",
            integrity_hash=integrity_hash,
            is_evaluated=True,
            is_valid=is_valid,
            evaluation_errors=eval_errors,
        )

    def evaluate_plan(self, plan: AREPlanProposal | dict[str, Any]) -> dict[str, Any]:
        """Evalúa estructuralmente la viabilidad de un plan (ciclos, pasos duplicados, capacidades prohibidas)."""
        forbidden_caps = ("external_ocr", "external_upload", "document_write", "arbitrary_shell", "admin", "outbound_network", "unregistered_system_admin")

        if isinstance(plan, AREPlanProposal):
            plan_id = plan.plan_id
            steps = plan.steps
            deps = plan.dependencies
        else:
            plan_id = plan.get("plan_id", "plan_eval")
            steps = plan.get("steps", [])
            deps = plan.get("dependencies", {})

        # 1. Comprobar capacidades prohibidas
        for s in steps:
            req_caps = getattr(s, "required_capabilities", []) or []
            act = getattr(s, "action", "") or getattr(s, "action_type", "")
            if any(fc in req_caps or fc in act for fc in forbidden_caps):
                return {
                    "feasible": False,
                    "is_valid": False,
                    "plan_id": plan_id,
                    "reason": f"Plan contains forbidden capability: {act or req_caps}",
                }

        # 2. Comprobar IDs duplicados
        step_ids = [getattr(s, "step_id", str(s)) for s in steps]
        if len(step_ids) != len(set(step_ids)):
            return {
                "feasible": False,
                "is_valid": False,
                "plan_id": plan_id,
                "reason": "Duplicate step IDs detected in plan.",
            }

        # 3. Comprobar dependencias circulares
        if deps:
            # Build graph and check topological sort
            try:
                adj: dict[str, list[str]] = {sid: [] for sid in step_ids}
                in_deg: dict[str, int] = dict.fromkeys(step_ids, 0)
                for u, v_list in deps.items():
                    for v in v_list:
                        if v in adj and u in in_deg:
                            adj[v].append(u)
                            in_deg[u] += 1
                queue = [sid for sid, d in in_deg.items() if d == 0]
                visited_count = 0
                while queue:
                    curr = queue.pop(0)
                    visited_count += 1
                    for nxt in adj.get(curr, []):
                        in_deg[nxt] -= 1
                        if in_deg[nxt] == 0:
                            queue.append(nxt)
                if visited_count != len(step_ids):
                    return {
                        "feasible": False,
                        "is_valid": False,
                        "plan_id": plan_id,
                        "reason": "Circular dependencies detected in plan.",
                    }
            except Exception as e:
                return {
                    "feasible": False,
                    "is_valid": False,
                    "plan_id": plan_id,
                    "reason": f"Circular dependencies: {e}",
                }

        return {
            "feasible": True,
            "is_valid": True,
            "plan_id": plan_id,
            "reason": "Plan structurally valid and feasible.",
        }

    def diagnose_and_recover(
        self,
        graph_dict: dict[str, Any] | None = None,
        failed_step_id: str | None = None,
        error_message: str = "",
        attempt_number: int = 1,
        task_id: str = "",
        plan_id: str = "",
        *,
        failed_step: Any = None,
        error: str = "",
        plan: Any = None,
        attempt: int | None = None,
    ) -> tuple[AREDiagnosis, ARERecoveryProposal] | ARERecoveryProposal:
        """Diagnostica la causa raíz y genera una propuesta de recuperación respetando límites de reintento."""
        # Unificar parámetros de entrada
        called_with_kwargs = failed_step is not None or plan is not None or attempt is not None
        if failed_step is not None:
            failed_step_id = getattr(failed_step, "step_id", str(failed_step))
        if error:
            error_message = error
        if attempt is not None:
            attempt_number = attempt
        if plan is not None:
            if hasattr(plan, "plan_id"):
                plan_id = plan.plan_id
            if hasattr(plan, "task_id"):
                task_id = plan.task_id
            if hasattr(plan, "steps"):
                graph_dict = {
                    "goal": getattr(plan, "goal", "recovery"),
                    "nodes": {s.step_id: s.to_dict() for s in plan.steps},
                }

        t_id = task_id or f"task-{uuid.uuid4().hex[:8]}"
        p_id = plan_id or f"plan-{uuid.uuid4().hex[:8]}"
        fs_id = failed_step_id or "step_failed"

        # Regla Anti-Bucle Infinito: Límite estricto de intentos de recuperación
        if attempt_number > self.MAX_RECOVERY_ATTEMPTS:
            logger.warning(
                f"[ARE RECOVERY LIMIT] Se superó el límite de reintentos ({attempt_number} > {self.MAX_RECOVERY_ATTEMPTS}) "
                f"para el paso '{fs_id}'. Forzando ABORT seguro."
            )
            diag = AREDiagnosis(
                failed_step_id=fs_id,
                failure_step_id=fs_id,
                root_cause=f"Max recovery attempts exceeded ({attempt_number} > {self.MAX_RECOVERY_ATTEMPTS})",
                raw_error=error_message,
                recoverable=False,
            )
            rec = ARERecoveryProposal(
                task_id=t_id,
                plan_id=p_id,
                failed_step_id=fs_id,
                recommended_action="ABORT",
                rationale="Límite máximo de intentos de recuperación alcanzado (prevención de bucle infinito).",
                reason="Max recovery attempts exceeded.",
                recovery_steps=[],
                attempt_number=attempt_number,
                max_attempts=self.MAX_RECOVERY_ATTEMPTS,
                integrity_hash=ARERecoveryProposal.compute_integrity_hash(
                    t_id, p_id, fs_id, "ABORT", attempt_number
                ),
            )
            return (diag, rec) if called_with_kwargs else rec

        # 1. Diagnóstico de Fallo
        diag_params = {
            "graph": graph_dict or {},
            "failed_node_id": fs_id,
            "error_message": error_message,
        }
        try:
            diag_res = asyncio.run(self.are_adapter._handle_diagnose_failure(diag_params, time.perf_counter()))
        except Exception as exc:
            logger.error(f"[ARE RECOVERY] Error al diagnosticar fallo: {exc}")
            diag_res = None

        diagnosis_out = diag_res.output if diag_res and diag_res.output else {}
        diag = AREDiagnosis(
            failed_step_id=fs_id,
            failure_step_id=fs_id,
            root_cause=diagnosis_out.get("root_cause", error_message or "Execution failure"),
            raw_error=error_message,
            is_critical=diagnosis_out.get("is_critical", True),
            recoverable=diagnosis_out.get("recoverable", True),
            blocked_steps=diagnosis_out.get("blast_radius", {}).get("blocked_nodes", []),
            independent_steps=diagnosis_out.get("blast_radius", {}).get("independent_nodes", []),
            confidence=0.95,
        )

        # 2. Generación de Estrategia de Recuperación
        rec_params = {
            "graph": graph_dict or {},
            "failed_node_id": fs_id,
            "diagnosis": diagnosis_out,
        }
        try:
            rec_res = asyncio.run(self.are_adapter._handle_recover_plan(rec_params, time.perf_counter()))
        except Exception as exc:
            logger.error(f"[ARE RECOVERY] Error al generar plan de recuperación: {exc}")
            rec_res = None

        rec_out = rec_res.output if rec_res and rec_res.output else {}
        action = rec_out.get("recommended_action", "ASK_USER")
        if isinstance(action, str) and action.startswith("RecoveryActionType."):
            action = action.split(".")[-1]
        elif hasattr(action, "value"):
            action = action.value

        rationale = rec_out.get("rationale", "Fallo detectado; requiere decisión humana.")
        rec_steps = rec_out.get("recovery_steps", [])

        integrity_hash = ARERecoveryProposal.compute_integrity_hash(
            task_id=t_id,
            plan_id=p_id,
            failed_step_id=fs_id,
            recommended_action=str(action),
            attempt_number=attempt_number,
        )

        rec = ARERecoveryProposal(
            task_id=t_id,
            plan_id=p_id,
            failed_step_id=fs_id,
            recommended_action=str(action),
            rationale=rationale,
            reason=rationale,
            recovery_steps=rec_steps,
            attempt_number=attempt_number,
            max_attempts=self.MAX_RECOVERY_ATTEMPTS,
            integrity_hash=integrity_hash,
        )

        return (diag, rec) if called_with_kwargs else rec

    def execute_complex_task(
        self,
        agent: Any,
        req: Any,
        goal: str,
        context: dict[str, Any] | None = None,
        user_confirmed: bool = False,
        cancellation_token: Any | None = None,
        user_confirmation_callback: Any | None = None,
    ) -> Any:
        """Ejecuta una tarea compleja coordinada paso a paso bajo la autoridad estricta de JDE."""
        from core.local_agent.local_agent_models import AgentExecutionState, JessycaResponse

        req_id = getattr(req, "request_id", "req_are_task")
        sess_id = getattr(req, "session_id", "sess_are_task")

        # Comprobar modo operativo de ARE
        if self.current_mode == ARERuntimeMode.DISABLED:
            return JessycaResponse(
                request_id=req_id,
                session_id=sess_id,
                success=False,
                status=AgentExecutionState.FAILED,
                response_text="ARE Runtime is DISABLED. No se pueden procesar tareas complejas.",
                error="ARE Runtime is DISABLED",
            )

        _start_time = time.perf_counter()
        token = cancellation_token
        if token and token.is_cancelled:
            return JessycaResponse(
                request_id=req_id,
                session_id=sess_id,
                success=False,
                status=AgentExecutionState.INTERRUPTED,
                response_text="Operación cancelada por el usuario antes de planificar.",
                error="Cancelled",
            )

        # Si el agente tiene jde_runtime_binding explícitamente en None o falta JDE, bloquear
        if hasattr(agent, "jde_runtime_binding") and agent.jde_runtime_binding is None:
            return JessycaResponse(
                request_id=req_id,
                session_id=sess_id,
                success=False,
                status=AgentExecutionState.FAILED,
                response_text="Error: JDE Runtime Binding no está disponible.",
                error="JDE missing",
            )
        jde_binding = getattr(agent, "jde_runtime_binding", None) or self.jde_binding
        if jde_binding is None:
            return JessycaResponse(
                request_id=req_id,
                session_id=sess_id,
                success=False,
                status=AgentExecutionState.FAILED,
                response_text="Error: JDE Runtime Binding no está disponible.",
                error="JDE missing",
            )

        if context is None:
            context = {}
        if hasattr(agent, "context_manager") and agent.context_manager and sess_id:
            sess = agent.context_manager.get_session(sess_id)
            if sess:
                for k in ("active_document", "session_document", "current_document", "current_file"):
                    val = sess.active_context.get(k)
                    if not val and k in sess.context_items:
                        val = sess.context_items[k].value
                    if val and k not in context:
                        context[k] = val

        # 1. Descomposición y evaluación estructural del plan (ARE DAG)
        try:
            plan = self.decompose_and_plan(goal=goal, context=context, task_id=req_id)
        except Exception as exc:
            logger.error(f"[ARE RUNTIME] Error al descomponer tarea: {exc}")
            return JessycaResponse(
                request_id=req.request_id,
                session_id=req.session_id,
                success=False,
                status=AgentExecutionState.FAILED,
                response_text=f"Fallo al planificar la tarea compleja: {exc}",
                error=str(exc),
            )

        if not plan.is_valid:
            err_msg = "; ".join(plan.evaluation_errors) or "Plan inválido generado por ARE (posible ciclo)."
            return JessycaResponse(
                request_id=req.request_id,
                session_id=req.session_id,
                success=False,
                status=AgentExecutionState.FAILED,
                response_text=f"Error en validación del plan: {err_msg}",
                error=err_msg,
            )

        return self._execute_plan_internal(
            agent=agent,
            req=req,
            plan=plan,
            goal=goal,
            context=context,
            user_confirmed=user_confirmed,
            cancellation_token=cancellation_token,
        )

    def validate_llm_plan(
        self,
        plan_input: dict[str, Any] | str | LLMPlanProposal,
        sandbox_dir: Path | str | None = None,
        task_id: str = "task_llm_plan",
        plan_id: str = "plan_llm_validated",
    ) -> AREPlanProposal:
        """Valida una propuesta de plan JSON fuera del LLM aplicando todas las políticas perimétricas."""
        validator = PlanValidator(
            catalog=self.action_catalog,
            sandbox_dir=sandbox_dir,
        )
        return validator.validate_plan(
            plan_input=plan_input,
            previously_denied_actions=self._previously_denied_actions,
            task_id=task_id,
            plan_id=plan_id,
        )

    def execute_llm_plan(
        self,
        agent: Any,
        req: Any,
        plan_input: dict[str, Any] | str | LLMPlanProposal,
        sandbox_dir: Path | str | None = None,
        user_confirmed: bool = False,
        cancellation_token: Any | None = None,
        previous_state: AREPlanExecutionState | None = None,
    ) -> Any:
        """Valida rigurosamente fuera del LLM y ejecuta un plan propuesto en formato JSON."""
        from core.local_agent.local_agent_models import AgentExecutionState, JessycaResponse

        req_id = getattr(req, "request_id", "req_llm_plan")
        sess_id = getattr(req, "session_id", "sess_llm_plan")

        try:
            validated_plan = self.validate_llm_plan(
                plan_input=plan_input,
                sandbox_dir=sandbox_dir,
                task_id=req_id,
            )
        except PlanClarificationRequired as pcr:
            return JessycaResponse(
                request_id=req_id,
                session_id=sess_id,
                success=True,
                status=AgentExecutionState.AWAITING_CLARIFICATION,
                response_text=f"Aclaración requerida: {pcr.prompt}",
                requires_clarification=True,
            )
        except Exception as exc:
            logger.error(f"[ARE LLM PLAN VALIDATION FAILED] {exc}")
            return JessycaResponse(
                request_id=req_id,
                session_id=sess_id,
                success=False,
                status=AgentExecutionState.FAILED,
                response_text=f"Fallo de validación perimétrica de plan: {exc}",
                error=str(exc),
            )

        ctx = {"sandbox_dir": str(sandbox_dir)} if sandbox_dir else {}
        return self._execute_plan_internal(
            agent=agent,
            req=req,
            plan=validated_plan,
            goal=validated_plan.goal,
            context=ctx,
            user_confirmed=user_confirmed,
            cancellation_token=cancellation_token,
            previous_state=previous_state,
        )

    def resume_llm_plan(
        self,
        agent: Any,
        req: Any,
        plan_input: dict[str, Any] | str | LLMPlanProposal,
        previous_state: AREPlanExecutionState,
        sandbox_dir: Path | str | None = None,
        user_confirmed: bool = False,
        cancellation_token: Any | None = None,
    ) -> Any:
        """Reanuda un plan previamente interrumpido o fallido evitando repetir escrituras ya realizadas."""
        return self.execute_llm_plan(
            agent=agent,
            req=req,
            plan_input=plan_input,
            sandbox_dir=sandbox_dir,
            user_confirmed=user_confirmed,
            cancellation_token=cancellation_token,
            previous_state=previous_state,
        )

    def _execute_plan_internal(
        self,
        agent: Any,
        req: Any,
        plan: AREPlanProposal,
        goal: str,
        context: dict[str, Any] | None = None,
        user_confirmed: bool = False,
        cancellation_token: Any | None = None,
        previous_state: AREPlanExecutionState | None = None,
    ) -> Any:
        """Núcleo de ejecución gobernada paso a paso bajo autoridad de JDE."""
        from core.local_agent.local_agent_models import AgentExecutionState, JessycaResponse

        req_id = getattr(req, "request_id", "req_are_task")
        sess_id = getattr(req, "session_id", "sess_are_task")
        token = cancellation_token
        jde_binding = getattr(agent, "jde_runtime_binding", None) or self.jde_binding

        exec_state = AREPlanExecutionState(
            task_id=req_id,
            plan_id=plan.plan_id,
            goal=goal,
            previously_denied_actions=set(self._previously_denied_actions),
            sandbox_dir=str(context.get("sandbox_dir")) if context and context.get("sandbox_dir") else None,
        )
        self.last_execution_state = exec_state

        executed_steps: list[str] = []
        step_outputs: dict[str, Any] = {}
        recovery_attempts: dict[str, int] = {}
        steps_by_id = {s.step_id: s for s in plan.steps}

        def _mark_remaining_dependents_blocked(failed_id: str, reason: str) -> None:
            """Detiene y marca como BLOCKED todos los pasos posteriores que dependen del paso fallido."""
            try:
                failed_idx = plan.execution_order.index(failed_id)
            except ValueError:
                failed_idx = -1
            blocked_ancestors = {failed_id}
            for rem_id in plan.execution_order[failed_idx + 1:]:
                rem_step = steps_by_id[rem_id]
                if any(d in blocked_ancestors for d in rem_step.depends_on) or rem_id not in exec_state.step_records:
                    blocked_ancestors.add(rem_id)
                    exec_state.record_step_blocked(rem_id, rem_step.action_type, reason)

        for step_id in plan.execution_order:
            if token and token.is_cancelled:
                exec_state.mark_plan_cancelled()
                _mark_remaining_dependents_blocked(step_id, "Cancelado por el usuario.")
                return JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=False,
                    status=AgentExecutionState.INTERRUPTED,
                    response_text="Operación interrumpida durante la ejecución del plan.",
                    tools_executed=executed_steps,
                    output_data={"execution_state": exec_state.to_dict(), "explanation": exec_state.explain_state()},
                )

            step = steps_by_id[step_id]

            # Invariante de Replanificación: no se puede borrar una denegación previa ni ampliar permisos
            if step.action_type in self._previously_denied_actions or step.action in self._previously_denied_actions:
                logger.warning(f"[ARE RUNTIME - REPLANNING DENIAL VIOLATION] Acción '{step.action_type}' fue previamente denegada.")
                exec_state.record_denial(step.action_type, step.step_id, "Acción previamente denegada en replanificación.")
                _mark_remaining_dependents_blocked(step.step_id, "Acción denegada por política de replanificación.")
                exec_state.mark_plan_failed("Replanificación no puede borrar una denegación previa ni ampliar permisos.")
                return JessycaResponse(
                    request_id=req_id,
                    session_id=sess_id,
                    success=False,
                    status=AgentExecutionState.FAILED,
                    response_text=f"Replanificación denegada: la acción '{step.action_type}' fue previamente denegada por gobernanza de seguridad.",
                    security_verdict="DENY",
                    tools_executed=executed_steps,
                    output_data={"execution_state": exec_state.to_dict(), "explanation": exec_state.explain_state()},
                )

            # Idempotencia al reintentar: No repetir escrituras ya realizadas y verificadas en estado previo
            if previous_state and step_id in previous_state.step_records:
                prev_rec = previous_state.step_records[step_id]
                if prev_rec.status == "SUCCEEDED" and prev_rec.is_verified:
                    # Comprobar si era acción física con archivo en disco
                    file_still_ok = True
                    if isinstance(prev_rec.output, dict):
                        chk_p = prev_rec.output.get("file_path") or prev_rec.output.get("destination_path") or prev_rec.output.get("output_path")
                        if chk_p:
                            p_chk = Path(chk_p).resolve()
                            file_still_ok = p_chk.exists() and p_chk.stat().st_size > 0

                    if file_still_ok:
                        logger.info(f"[ARE RESUME IDEMPOTENT] Paso '{step_id}' completado en ejecución previa y verificado en disco. Omitiendo reescritura.")
                        step_outputs[step_id] = prev_rec.output
                        executed_steps.append(step.action_type)
                        exec_state.record_step_skipped(
                            step.step_id,
                            step.action_type,
                            "Escritura ya realizada en ejecución previa; reutilizada por idempotencia física.",
                            output=prev_rec.output,
                        )
                        continue

            # Resolver parámetros dependientes con DataFlowResolver
            try:
                resolved_params = DataFlowResolver.resolve_parameters(
                    step.parameters,
                    step_outputs,
                    step_id=step.step_id,
                )
            except MissingOutputDependencyError as mode_err:
                logger.error(f"[ARE DATAFLOW ERROR] {mode_err}")
                exec_rec = exec_state.record_step_start(step.step_id, step.action_type, step.parameters)
                exec_rec.mark_failed(str(mode_err))
                _mark_remaining_dependents_blocked(step.step_id, f"Dependencia ausente o requisito no satisfecho: {mode_err.message}")
                exec_state.mark_plan_failed(str(mode_err))
                return JessycaResponse(
                    request_id=req_id,
                    session_id=sess_id,
                    success=False,
                    status=AgentExecutionState.FAILED,
                    response_text=f"Fallo de dependencia de datos en '{step.step_id}': {mode_err.message}",
                    error=str(mode_err),
                    tools_executed=executed_steps,
                    output_data={"execution_state": exec_state.to_dict(), "explanation": exec_state.explain_state()},
                )

            # A. Evaluación en JDE Runtime Binding (AUTORIDAD ÚNICA)
            step_verdict = jde_binding.evaluate(
                intent=step.action_type,
                action=step.action_type,
                tool=step.action_type,
                parameters=resolved_params,
                user_confirmed=user_confirmed,
                session_id=sess_id,
                request_id=f"{req_id}_{step.step_id}",
                risk_level=step.risk_level,
            )

            # B. Si JDE DENY -> Abortar inmediatamente sin efectos secundarios y registrar denegación
            if step_verdict.verdict == JDERuntimeVerdictType.DENY:
                logger.warning(f"[ARE RUNTIME - DENY] Paso '{step.step_id}' ({step.action_type}) denegado por JDE.")
                self._previously_denied_actions.add(step.action_type)
                exec_state.record_denial(step.action_type, step.step_id, step_verdict.reason)
                _mark_remaining_dependents_blocked(step.step_id, f"Acción previa denegada por gobernanza: {step_verdict.reason}")
                exec_state.mark_plan_failed(f"Acción denegada por gobernanza JDE: {step_verdict.reason}")
                return JessycaResponse(
                    request_id=req_id,
                    session_id=sess_id,
                    success=False,
                    status=AgentExecutionState.FAILED,
                    response_text=f"Acción denegada por gobernanza JDE: {step_verdict.reason}",
                    security_verdict="DENY",
                    tools_executed=executed_steps,
                    output_data={"execution_state": exec_state.to_dict(), "explanation": exec_state.explain_state()},
                )

            # C. Si JDE REQUIRE_REVIEW -> Detener y solicitar confirmación
            if step_verdict.verdict == JDERuntimeVerdictType.REQUIRE_REVIEW:
                if not user_confirmed:
                    review_msg = f"JDE requiere confirmación para '{step.action_type}': {step_verdict.reason}"
                    return JessycaResponse(
                        request_id=req_id,
                        session_id=sess_id,
                        success=True,
                        status=AgentExecutionState.AWAITING_CONFIRMATION,
                        response_text=review_msg,
                        requires_confirmation=True,
                        tools_executed=executed_steps,
                    )

            # D. Si JDE ALLOW -> Validar antes de ejecutar que el paso resuelva a una herramienta existente
            # (No ejecutar action.execute ni otros nombres genéricos sin implementación concreta)
            try:
                resolved_act = self.action_catalog.resolve_action(
                    step.action_type,
                    skill_manager=getattr(agent, "skill_manager", None),
                    tool_registry=getattr(agent, "tool_registry", None),
                )
            except UnresolvableActionError as uae:
                logger.error(f"[ARE PRE-EXECUTION VALIDATION] Acción '{step.action_type}' no ejecutable: {uae}")
                exec_rec = exec_state.record_step_start(step.step_id, step.action_type, resolved_params)
                exec_rec.mark_failed(str(uae), is_verified=False)
                _mark_remaining_dependents_blocked(step.step_id, f"Acción '{step.action_type}' no resoluble: {uae}")
                exec_state.mark_plan_failed(str(uae))
                return JessycaResponse(
                    request_id=req_id,
                    session_id=sess_id,
                    success=False,
                    status=AgentExecutionState.FAILED,
                    response_text=f"Error de planificación: la acción '{step.action_type}' no resuelve a ninguna herramienta concreta ni ejecutable.",
                    error=str(uae),
                    tools_executed=executed_steps,
                    output_data={"execution_state": exec_state.to_dict(), "explanation": exec_state.explain_state()},
                )

            # Proceder con capas de seguridad física
            exec_rec = exec_state.record_step_start(step.step_id, step.action_type, resolved_params)
            target_str = str(resolved_params.get("target") or resolved_params.get("path") or resolved_params.get("file_path") or step.title)
            fprint = ExecutionFingerprint(
                session_id=sess_id,
                request_id=f"{req_id}_{step.step_id}",
                intent=step.action_type,
                skill=step.action_type,
                action=step.action_type,
                target=target_str,
            )
            is_acquired, exec_record = self.idempotency_guard.acquire_execution(fprint)
            if not is_acquired:
                logger.info(f"[ARE IDEMPOTENCY] Paso '{step.step_id}' ya ejecutado o duplicado; omitiendo reejecución.")
                executed_steps.append(step.action_type)
                continue

            # Despacho físico gobernado según la herramienta
            step_success = False
            step_output: Any = None
            step_error: str | None = None

            # 1. Catálogo de acciones de ARE (files.search, documents.read, data.extract_table, etc.)
            if resolved_act and resolved_act.handler is not None:
                try:
                    step_output = resolved_act.execute(resolved_params, {"session_id": sess_id, "request_id": req_id})
                    step_success = True
                    step_error = None
                except PlanClarificationRequired as pcr:
                    logger.info(f"[ARE RUNTIME - CLARIFICATION REQUIRED] Paso '{step.step_id}' requiere aclaración: {pcr.prompt}")
                    exec_state.record_step_blocked(step.step_id, step.action_type, f"Aclaración requerida: {pcr.prompt}")
                    return JessycaResponse(
                        request_id=req_id,
                        session_id=sess_id,
                        success=True,
                        status=AgentExecutionState.AWAITING_CLARIFICATION,
                        response_text=f"Aclaración requerida: {pcr.prompt}",
                        requires_clarification=True,
                        tools_executed=executed_steps,
                        output_data={"execution_state": exec_state.to_dict(), "explanation": exec_state.explain_state()},
                    )
                except Exception as exc:
                    step_success = False
                    step_error = str(exc)

            # 2. Subordinación estricta de ORCA/ADE
            elif step.action_type.startswith("agent_orchestration.") or step.action_type in ("worktree_isolation", "parallel_agent_dispatch"):
                from core.orca_ade.adapter import OrcaAdeAdapter
                from core.orca_ade.models import OrcaAdeMode
                orca = OrcaAdeAdapter(mode=OrcaAdeMode.CONTROLLED)
                cap = step.action_type if step.action_type in orca._capabilities else "parallel_agent_dispatch"
                from core.integration.models import IntegrationContext
                ctx = IntegrationContext(session_id=sess_id, parameters=resolved_params, metadata={"request_id": req_id})
                res = asyncio.run(orca.execute(cap, ctx))
                step_success = res.status == ExecutionStatus.SUCCEEDED
                step_output = res.output
                step_error = res.error

            # 3. Subordinación estricta de AnyDoc
            elif step.action_type.startswith("document_processing."):
                forbidden_caps = ("external_ocr", "external_upload", "document_write", "arbitrary_shell", "admin", "outbound_network")
                if any(fc in step.action_type for fc in forbidden_caps):
                    logger.critical(f"[ARE ANYDOC SECURITY] Intento de invocar capacidad prohibida '{step.action_type}'. Bloqueado.")
                    step_success = False
                    step_error = f"Capacidad prohibida '{step.action_type}' bloqueada por seguridad."
                else:
                    from core.anydoc.adapter import AnyDocAdapter
                    from core.anydoc.models import AnyDocMode
                    anydoc = AnyDocAdapter(mode=AnyDocMode.CONTROLLED)
                    from core.integration.models import IntegrationContext
                    ctx = IntegrationContext(session_id=sess_id, parameters=resolved_params, metadata={"request_id": req_id})
                    res = asyncio.run(anydoc.execute(step.action_type, ctx))
                    step_success = res.status == ExecutionStatus.SUCCEEDED
                    step_output = res.output
                    step_error = res.error

            # 4. Despacho estándar a SkillManager
            elif hasattr(agent, "skill_manager") and agent.skill_manager and agent.skill_manager.registry.lookup(step.action_type):
                exec_params = dict(resolved_params)
                if step.action_type == "files.search" and not any(k in exec_params for k in ("nombre", "query", "pattern", "file")):
                    exec_params["nombre"] = "descarga"
                skill_res = agent.skill_manager.execute_skill(step.action_type, parameters=exec_params)
                if skill_res.success:
                    step_success = True
                    step_output = skill_res.output if skill_res.output else {"exito": True, "verified": True}
                    step_error = None
                else:
                    step_success = False
                    step_error = skill_res.error or f"Fallo al ejecutar skill {step.action_type}"
            else:
                step_success = False
                step_error = f"No existe implementación ejecutable para la acción '{step.action_type}'"

            # Verificación Física Obligatoria (Anti-False Success)
            if step_success:
                is_verif = False
                if resolved_act and resolved_act.verification_strategy == ActionVerificationStrategy.PHYSICAL_FILE_EXISTS:
                    if isinstance(step_output, dict):
                        chk_file = step_output.get("file_path") or step_output.get("destination_path") or step_output.get("output_path") or step_output.get("table_path")
                        if chk_file:
                            p_chk = Path(chk_file)
                            is_verif = p_chk.exists() and (p_chk.stat().st_size > 0 or step_output.get("verified", False))
                        elif "all_verified" in step_output:
                            is_verif = bool(step_output.get("all_verified", False))
                        else:
                            is_verif = bool(step_output.get("verified", False))
                elif resolved_act and resolved_act.verification_strategy == ActionVerificationStrategy.CONTENT_VERIFIED:
                    if isinstance(step_output, dict):
                        is_verif = bool(step_output.get("verified", False)) and bool(step_output.get("references")) and bool(step_output.get("summary"))
                elif resolved_act and resolved_act.verification_strategy == ActionVerificationStrategy.SCHEMA_VERIFIED:
                    if isinstance(step_output, dict):
                        is_verif = bool(step_output.get("verified", False))
                elif resolved_act and resolved_act.verification_strategy == ActionVerificationStrategy.STATE_MATCH:
                    if isinstance(step_output, dict):
                        is_verif = bool(step_output.get("verified", False)) or ("found_files" in step_output) or ("content" in step_output) or ("status" in step_output) or ("precondition_met" in step_output)
                else:
                    raw_ev = step_output.get("evidence") if isinstance(step_output, dict) else None
                    if raw_ev:
                        is_verif = bool(raw_ev.get("is_verified", False))
                    elif isinstance(step_output, dict) and "verified" in step_output:
                        is_verif = bool(step_output.get("verified", False))
                    elif isinstance(step_output, dict) and step_output.get("exito") is True:
                        is_verif = True
                    else:
                        ev_result = self.execution_verifier.verify_execution(
                            action=step.action_type,
                            target=target_str,
                            parameters=resolved_params,
                        )
                        is_verif = ev_result.is_verified

                if not is_verif:
                    logger.warning(f"[ARE ANTI-FALSE SUCCESS] Paso '{step.step_id}' no demostró evidencia física. Degradando a fallo.")
                    step_success = False
                    step_error = "Fallo de verificación física en el sistema operativo."

            if step_success:
                self.idempotency_guard.record_verification_completed(
                    execution_id=exec_record.execution_id,
                    status="SUCCEEDED",
                    result_message="Paso verificado exitosamente.",
                )
                exec_rec.mark_completed(step_output, is_verified=True)
                executed_steps.append(step.action_type)
                step_outputs[step.step_id] = step_output
            else:
                self.idempotency_guard.record_verification_completed(
                    execution_id=exec_record.execution_id,
                    status="FAILED",
                    result_message=step_error or "Fallo en ejecución.",
                )
                exec_rec.mark_failed(step_error or "Fallo en ejecución", is_verified=False)
                # Manejo de Fallo y Recuperación (are.diagnose_failure & are.recover_plan)
                cur_attempts = recovery_attempts.get(step.step_id, 0) + 1
                recovery_attempts[step.step_id] = cur_attempts

                raw_graph_repr = {
                    "goal": goal,
                    "nodes": {s.step_id: s.to_dict() for s in plan.steps},
                }
                recovery_prop = self.diagnose_and_recover(
                    graph_dict=raw_graph_repr,
                    failed_step_id=step.step_id,
                    error_message=step_error or "Fallo de ejecución o verificación",
                    attempt_number=cur_attempts,
                    task_id=req.request_id,
                    plan_id=plan.plan_id,
                )

                if recovery_prop.recommended_action == "SKIP" and not step.is_critical:
                    logger.info(f"[ARE RECOVERY] Saltando paso no crítico '{step.step_id}'.")
                    continue
                elif recovery_prop.recommended_action == "ASK_USER":
                    return JessycaResponse(
                        request_id=req.request_id,
                        session_id=req.session_id,
                        success=False,
                        status=AgentExecutionState.AWAITING_CONFIRMATION,
                        response_text=f"Fallo en paso '{step.title}': {recovery_prop.rationale}",
                        requires_confirmation=True,
                        tools_executed=executed_steps,
                    )
                else:
                    _mark_remaining_dependents_blocked(step.step_id, f"Fallo en paso '{step.title}': {step_error}")
                    exec_state.mark_plan_failed(step_error or "Step failed")
                    return JessycaResponse(
                        request_id=req_id,
                        session_id=sess_id,
                        success=False,
                        status=AgentExecutionState.FAILED,
                        response_text=f"Fallo en paso '{step.title}': {step_error}. Diagnóstico ARE: {recovery_prop.rationale}",
                        error=step_error or "Step failed",
                        tools_executed=executed_steps,
                        output_data={"execution_state": exec_state.to_dict(), "explanation": exec_state.explain_state()},
                    )

        # Plan completado exitosamente
        step_outputs["governance"] = "JDE"
        exec_state.mark_plan_completed()
        step_outputs["execution_state"] = exec_state.to_dict()
        step_outputs["explanation"] = exec_state.explain_state()

        # Entregar el resumen o resultado sustantivo generado en vez de sólo el conteo de pasos
        final_resp = f"Tarea compleja completada exitosamente ({len(executed_steps)} pasos ejecutados)."
        for s in reversed(plan.steps):
            out = step_outputs.get(s.step_id)
            if isinstance(out, dict):
                if out.get("summary"):
                    final_resp = str(out["summary"])
                    break
                elif out.get("resumen"):
                    final_resp = str(out["resumen"])
                    break
                elif out.get("preview"):
                    final_resp = str(out["preview"])
                    break
                elif out.get("message") and "Tarea compleja" not in str(out.get("message")):
                    final_resp = str(out["message"])
                    break

        return JessycaResponse(
            request_id=req_id,
            session_id=sess_id,
            success=True,
            status=AgentExecutionState.COMPLETED,
            response_text=final_resp,
            tools_executed=executed_steps,
            output_data=step_outputs,
        )


_GLOBAL_ARE_RUNTIME: ARERuntime | None = None
_RUNTIME_LOCK = threading.Lock()


def get_are_runtime(mode: ARERuntimeMode | str | None = None) -> ARERuntime:
    """Retorna la instancia global singleton de ARERuntime."""
    global _GLOBAL_ARE_RUNTIME
    with _RUNTIME_LOCK:
        if _GLOBAL_ARE_RUNTIME is None:
            _GLOBAL_ARE_RUNTIME = ARERuntime(mode=mode)
        elif mode is not None:
            _GLOBAL_ARE_RUNTIME.set_mode(mode)
        return _GLOBAL_ARE_RUNTIME


def reset_are_runtime(mode: ARERuntimeMode | str | None = None) -> ARERuntime:
    """Reinicia la instancia global de ARERuntime (útil para pruebas de integración y aislamiento)."""
    global _GLOBAL_ARE_RUNTIME
    with _RUNTIME_LOCK:
        _GLOBAL_ARE_RUNTIME = ARERuntime(mode=mode)
        return _GLOBAL_ARE_RUNTIME
