"""Adapter de Integración de ARE (Autonomous / Action Reasoning Engine) para JESSYCA 4.0.

Implementa la integración controlada y selectiva de las capacidades de razonamiento agéntico,
descomposición de tareas en grafos dirigidos acíclicos (DAG), diagnóstico de fallos con análisis
de radio de impacto (*downstream impact*) y síntesis de estrategias de contingencia y replanificación.

Principios Obligatorios:
1. IDENTIDAD: ARE NO sustituye al Orchestrator de JESSYCA; es un proveedor de razonamiento agéntico y DAG.
2. SEGURIDAD: Toda capacidad es de solo lectura / segura (READ_ONLY / SAFE). Las ejecuciones reales en el SO
   son responsabilidad exclusiva del Core de JESSYCA a través de sus Skills y Security Pipeline.
3. EXECUTE -> VERIFY -> REPORT: El adapter nunca auto-certifica éxito comprobable (verified=False por defecto).
4. AISLAMIENTO: Dependencias puras, modularidad estricta y carga sin efectos secundarios globales.
5. FALLBACK: Si ARE falla o está deshabilitado, JESSYCA recurre a su planificador nativo lineal.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapter import IntegrationAdapter
from core.integration.models import (
    IntegrationCapability,
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationHealth,
    IntegrationStatus,
)
from core.logger import get_logger
from core.security import RiskLevel

logger = get_logger("jessyca.integration.adapters.are")


class TaskNodeStatus(StrEnum):
    """Estado de un nodo de tarea en el grafo de ejecución."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"


class RecoveryActionType(StrEnum):
    """Tipo de acción de recuperación recomendada ante fallos en el grafo."""

    ABORT = "ABORT"                        # Abortar el grafo completo si el nodo es crítico
    SKIP = "SKIP"                          # Omitir el nodo si no es crítico y continuar
    RETRY = "RETRY"                        # Reintentar el nodo con backoff o parámetros alternativos
    ALTERNATIVE_BRANCH = "ALTERNATIVE_BRANCH"  # Sustituir por una rama o acción alternativa
    ASK_USER = "ASK_USER"                  # Solicitar aclaración o confirmación al usuario


@dataclass
class TaskNode:
    """Nodo atómico dentro del grafo de tareas (DAG) de ARE."""

    id: str
    title: str
    action_type: str
    parameters: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    is_critical: bool = True
    status: TaskNodeStatus = TaskNodeStatus.PENDING
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "action_type": self.action_type,
            "parameters": self.parameters,
            "depends_on": self.depends_on,
            "is_critical": self.is_critical,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class TaskGraph:
    """Grafo de Tareas Dirigido Acíclico (DAG) generado o evaluado por ARE."""

    goal: str
    nodes: dict[str, TaskNode] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: TaskNode) -> None:
        self.nodes[node.id] = node

    def get_topological_order(self) -> list[str]:
        """Calcula el orden topológico de ejecución mediante el algoritmo de Kahn.

        Raises:
            ValueError: Si se detecta una dependencia circular (ciclo).
        """
        in_degree: dict[str, int] = {node_id: 0 for node_id in self.nodes}
        adj_list: dict[str, list[str]] = defaultdict(list)

        for node_id, node in self.nodes.items():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    raise ValueError(f"Dependencia desconocida '{dep}' en el nodo '{node_id}'")
                adj_list[dep].append(node_id)
                in_degree[node_id] += 1

        queue = deque([node_id for node_id, deg in in_degree.items() if deg == 0])
        ordered: list[str] = []

        while queue:
            curr = queue.popleft()
            ordered.append(curr)
            for neighbor in adj_list[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(ordered) != len(self.nodes):
            raise ValueError("El grafo de tareas contiene dependencias circulares (ciclo detectado).")

        return ordered

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
            "metadata": self.metadata,
        }


class AREAdapter(IntegrationAdapter):
    """Adapter oficial para la integración controlada de ARE (Autonomous/Action Reasoning Engine)."""

    def __init__(self) -> None:
        super().__init__(
            name="are",
            version="1.0.0",
            dependencies=[],  # No requiere dependencias binarias externas; tipos puros de Python
        )
        self._register_audited_capabilities()

    def _register_audited_capabilities(self) -> None:
        """Registra exclusivamente las capacidades de razonamiento agéntico y DAG auditadas."""
        # 1. Descomposición de Tareas (DAG Planning)
        self.register_capability(
            IntegrationCapability(
                name="are.decompose_task",
                description="Descompone un objetivo complejo en un grafo acíclico dirigido (DAG) de subtareas con dependencias",
                required_risk_level=RiskLevel.READ_ONLY,
                required_permissions=[],
                parameters_schema={
                    "goal": {"type": "str", "required": True, "description": "Objetivo principal a descomponer"},
                    "context": {"type": "dict", "required": False, "description": "Variables de entorno o contexto previo"},
                    "max_depth": {"type": "int", "required": False, "default": 5, "description": "Profundidad máxima del grafo"},
                },
            )
        )

        # 2. Evaluación y Validación Estructural del Plan
        self.register_capability(
            IntegrationCapability(
                name="are.evaluate_plan",
                description="Valida estructuralmente la viabilidad de un grafo de tareas (ciclos, dependencias y completitud)",
                required_risk_level=RiskLevel.READ_ONLY,
                required_permissions=[],
                parameters_schema={
                    "graph": {"type": "dict", "required": True, "description": "Definición del grafo de tareas a validar"},
                },
            )
        )

        # 3. Diagnóstico de Fallos y Análisis de Impacto Downstream
        self.register_capability(
            IntegrationCapability(
                name="are.diagnose_failure",
                description="Analiza la causa raíz de un fallo en un nodo y calcula el radio de impacto sobre nodos dependientes",
                required_risk_level=RiskLevel.READ_ONLY,
                required_permissions=[],
                parameters_schema={
                    "graph": {"type": "dict", "required": True, "description": "Estado actual del grafo de tareas"},
                    "failed_node_id": {"type": "str", "required": True, "description": "Identificador del nodo que falló"},
                    "error_message": {"type": "str", "required": True, "description": "Detalle técnico del error detectado"},
                },
            )
        )

        # 4. Estrategia de Replanificación y Recuperación
        self.register_capability(
            IntegrationCapability(
                name="are.recover_plan",
                description="Genera una estrategia de contingencia estructurada (reintento, rama alternativa, skip o solicitud de aclaración)",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=[],
                parameters_schema={
                    "graph": {"type": "dict", "required": True, "description": "Estado del grafo con nodo fallido"},
                    "failed_node_id": {"type": "str", "required": True, "description": "Identificador del nodo fallido"},
                    "diagnosis": {"type": "dict", "required": False, "description": "Diagnóstico previo de fallo si existe"},
                },
            )
        )

    async def initialize(self) -> bool:
        """Inicializa el AREAdapter de forma desacoplada."""
        try:
            deps_ok, missing = self.check_dependencies()
            if not deps_ok:
                self.status = IntegrationStatus.UNAVAILABLE
                logger.warning(f"AREAdapter no disponible: dependencias faltantes: {missing}")
                return False

            self.status = IntegrationStatus.READY
            logger.info("AREAdapter v1.0.0 inicializado exitosamente en estado READY.")
            return True
        except Exception as exc:
            self.status = IntegrationStatus.ERROR
            logger.error(f"Error crítico al inicializar AREAdapter: {exc}")
            return False

    async def health_check(self) -> IntegrationHealth:
        """Ejecuta una comprobación de salud y consistencia interna del motor ARE."""
        start = time.perf_counter()
        is_healthy = self.status in (IntegrationStatus.READY, IntegrationStatus.AVAILABLE)
        latency = (time.perf_counter() - start) * 1000

        details = {
            "version": self.version,
            "capabilities_count": len(self._capabilities),
            "status": self.status.value,
        }

        return IntegrationHealth(
            status=self.status,
            is_healthy=is_healthy,
            latency_ms=latency,
            message="AREAdapter operacional" if is_healthy else f"AREAdapter en estado {self.status.value}",
            details=details,
        )

    async def shutdown(self) -> None:
        """Libera recursos del adapter."""
        self.status = IntegrationStatus.AVAILABLE
        logger.info("AREAdapter apagado limpiamente.")

    async def execute(
        self,
        capability: str,
        context: IntegrationContext,
    ) -> IntegrationExecutionResult:
        """Ejecuta una de las 4 capacidades de razonamiento agéntico de ARE.

        Invariante EXECUTE -> VERIFY -> REPORT:
        Toda ejecución devuelve executed=True y verified=False por defecto.
        Nunca se auto-certifica éxito comprobable sin evidencia explícita de consistencia.
        """
        start_time = time.perf_counter()
        params = context.parameters or {}

        if self.status != IntegrationStatus.READY:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                verification_required=True,
                error=f"AREAdapter no está en estado READY (estado actual: {self.status.value})",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        if capability not in self._capabilities:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                verification_required=True,
                error=f"Capacidad '{capability}' no está registrada en AREAdapter",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        try:
            if capability == "are.decompose_task":
                return await self._handle_decompose_task(params, start_time)
            elif capability == "are.evaluate_plan":
                return await self._handle_evaluate_plan(params, start_time)
            elif capability == "are.diagnose_failure":
                return await self._handle_diagnose_failure(params, start_time)
            elif capability == "are.recover_plan":
                return await self._handle_recover_plan(params, start_time)
            else:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    verification_required=True,
                    error=f"Manejador no implementado para '{capability}'",
                    duration_ms=(time.perf_counter() - start_time) * 1000,
                )
        except Exception as exc:
            duration = (time.perf_counter() - start_time) * 1000
            logger.error(f"Error inesperado al ejecutar '{capability}': {exc}", exc_info=True)
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                verification_required=True,
                error=str(exc),
                duration_ms=duration,
            )

    # --- Manejadores Internos de Razonamiento ---

    async def _handle_decompose_task(
        self,
        params: dict[str, Any],
        start_time: float,
    ) -> IntegrationExecutionResult:
        """Descompone un objetivo de alto nivel en un grafo estructurado (DAG)."""
        goal = params.get("goal")
        if not goal or not isinstance(goal, str) or not goal.strip():
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error="El parámetro 'goal' es obligatorio y debe ser un texto no vacío",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        goal_clean = goal.strip()
        graph = TaskGraph(goal=goal_clean)

        # Reglas analíticas de descomposición basadas en patrones de intención
        goal_lower = goal_clean.lower()

        if "busca" in goal_lower and ("resume" in goal_lower or "guarda" in goal_lower):
            # Tarea multi-etapa: Búsqueda -> Extracción -> Síntesis/Guardado
            graph.add_node(
                TaskNode(
                    id="step_1_search",
                    title="Buscar información relevante",
                    action_type="browser.search",
                    parameters={"query": goal_clean},
                    depends_on=[],
                    is_critical=True,
                )
            )
            graph.add_node(
                TaskNode(
                    id="step_2_extract",
                    title="Extraer contenido relevante",
                    action_type="browser.read",
                    parameters={"source_step": "step_1_search"},
                    depends_on=["step_1_search"],
                    is_critical=True,
                )
            )
            graph.add_node(
                TaskNode(
                    id="step_3_synthesize",
                    title="Sintetizar o guardar resultado",
                    action_type="documents.create" if "guarda" in goal_lower else "core.assistant",
                    parameters={"source_step": "step_2_extract"},
                    depends_on=["step_2_extract"],
                    is_critical=False,
                )
            )
        elif "organiza" in goal_lower or "clasifica" in goal_lower:
            # Tarea de archivos/entorno: Inspección -> Análisis -> Movimiento
            graph.add_node(
                TaskNode(
                    id="step_1_scan",
                    title="Escanear elementos del directorio",
                    action_type="files.search",
                    parameters={},
                    depends_on=[],
                    is_critical=True,
                )
            )
            graph.add_node(
                TaskNode(
                    id="step_2_plan_moves",
                    title="Planificar asignación de carpetas",
                    action_type="core.assistant",
                    parameters={"source_step": "step_1_scan"},
                    depends_on=["step_1_scan"],
                    is_critical=True,
                )
            )
            graph.add_node(
                TaskNode(
                    id="step_3_execute_moves",
                    title="Reubicar archivos en destino",
                    action_type="files.move",
                    parameters={"source_step": "step_2_plan_moves"},
                    depends_on=["step_2_plan_moves"],
                    is_critical=True,
                )
            )
        else:
            # Descomposición estándar: Preparación -> Ejecución principal -> Verificación
            graph.add_node(
                TaskNode(
                    id="step_1_prep",
                    title=f"Validar precondiciones para: {goal_clean}",
                    action_type="system.check",
                    parameters={"target": goal_clean},
                    depends_on=[],
                    is_critical=True,
                )
            )
            graph.add_node(
                TaskNode(
                    id="step_2_act",
                    title=f"Ejecutar acción principal: {goal_clean}",
                    action_type="action.execute",
                    parameters={"goal": goal_clean},
                    depends_on=["step_1_prep"],
                    is_critical=True,
                )
            )
            graph.add_node(
                TaskNode(
                    id="step_3_verify",
                    title="Verificar resultado obtenido",
                    action_type="system.verify",
                    parameters={"target_step": "step_2_act"},
                    depends_on=["step_2_act"],
                    is_critical=False,
                )
            )

        execution_order = graph.get_topological_order()

        output_data = {
            "goal": goal_clean,
            "nodes_count": len(graph.nodes),
            "execution_order": execution_order,
            "graph": graph.to_dict(),
        }

        # Principio fundamental: executed=True, verified=False por defecto
        return IntegrationExecutionResult(
            executed=True,
            status=ExecutionStatus.SUCCEEDED,
            verified=False,
            verification_required=True,
            output=output_data,
            duration_ms=(time.perf_counter() - start_time) * 1000,
            metadata={"planner": "ARE.TaskDecomposer", "nodes_count": len(graph.nodes)},
        )

    async def _handle_evaluate_plan(
        self,
        params: dict[str, Any],
        start_time: float,
    ) -> IntegrationExecutionResult:
        """Valida estructuralmente la viabilidad de un grafo de tareas."""
        raw_graph = params.get("graph")
        if not raw_graph or not isinstance(raw_graph, dict):
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error="El parámetro 'graph' es obligatorio y debe ser un diccionario",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        raw_nodes = raw_graph.get("nodes", {})
        if not raw_nodes:
            return IntegrationExecutionResult(
                executed=True,
                status=ExecutionStatus.SUCCEEDED,
                verified=False,
                verification_required=True,
                output={
                    "is_valid": False,
                    "errors": ["El grafo no contiene nodos de ejecución."],
                    "topological_order": [],
                },
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        graph = TaskGraph(goal=raw_graph.get("goal", "Evaluar plan"))
        for node_id, node_data in raw_nodes.items():
            graph.add_node(
                TaskNode(
                    id=node_id,
                    title=node_data.get("title", node_id),
                    action_type=node_data.get("action_type", "unknown"),
                    parameters=node_data.get("parameters", {}),
                    depends_on=node_data.get("depends_on", []),
                    is_critical=node_data.get("is_critical", True),
                )
            )

        errors: list[str] = []
        topological_order: list[str] = []

        try:
            topological_order = graph.get_topological_order()
            is_valid = True
        except ValueError as val_err:
            is_valid = False
            errors.append(str(val_err))

        output_data = {
            "is_valid": is_valid,
            "errors": errors,
            "topological_order": topological_order,
            "total_nodes": len(graph.nodes),
        }

        return IntegrationExecutionResult(
            executed=True,
            status=ExecutionStatus.SUCCEEDED,
            verified=False,
            verification_required=True,
            output=output_data,
            duration_ms=(time.perf_counter() - start_time) * 1000,
            metadata={"planner": "ARE.PlanEvaluator", "is_valid": is_valid},
        )

    async def _handle_diagnose_failure(
        self,
        params: dict[str, Any],
        start_time: float,
    ) -> IntegrationExecutionResult:
        """Analiza la causa raíz de un fallo y calcula el radio de impacto downstream."""
        raw_graph = params.get("graph", {})
        failed_node_id = params.get("failed_node_id")
        error_msg = params.get("error_message", "Error no especificado")

        if not failed_node_id or not isinstance(failed_node_id, str):
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error="El parámetro 'failed_node_id' es obligatorio",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        raw_nodes = raw_graph.get("nodes", {}) if isinstance(raw_graph, dict) else {}
        if failed_node_id not in raw_nodes:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error=f"Nodo fallido '{failed_node_id}' no encontrado en el grafo provisto",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        failed_node_data = raw_nodes[failed_node_id]
        is_critical = failed_node_data.get("is_critical", True)

        # 1. Análisis de Radio de Impacto Downstream (BFS sobre dependencias)
        # Construir adyacencia inversa: dep -> [nodos que dependen de dep]
        dependents: dict[str, list[str]] = defaultdict(list)
        for nid, ndata in raw_nodes.items():
            for dep in ndata.get("depends_on", []):
                dependents[dep].append(nid)

        blocked_nodes: list[str] = []
        queue = deque([failed_node_id])
        visited = {failed_node_id}

        while queue:
            curr = queue.popleft()
            for dep_child in dependents.get(curr, []):
                if dep_child not in visited:
                    visited.add(dep_child)
                    blocked_nodes.append(dep_child)
                    queue.append(dep_child)

        # 2. Identificar nodos independientes que aún podrían ejecutarse
        independent_nodes = [
            nid for nid in raw_nodes
            if nid != failed_node_id and nid not in blocked_nodes
        ]

        # 3. Clasificación de causa de fallo
        err_lower = str(error_msg).lower()
        if "timeout" in err_lower or "timed out" in err_lower:
            root_cause = "NETWORK_OR_PROCESS_TIMEOUT"
            recoverable = True
        elif "not found" in err_lower or "no existe" in err_lower or "404" in err_lower:
            root_cause = "RESOURCE_NOT_FOUND"
            recoverable = False
        elif "permission" in err_lower or "access denied" in err_lower or "denegado" in err_lower:
            root_cause = "PERMISSION_OR_SECURITY_RESTRICTION"
            recoverable = False
        else:
            root_cause = "UNHANDLED_EXECUTION_EXCEPTION"
            recoverable = True

        diagnosis = {
            "failed_node_id": failed_node_id,
            "root_cause": root_cause,
            "is_critical": is_critical,
            "recoverable": recoverable,
            "blast_radius": {
                "blocked_nodes": blocked_nodes,
                "blocked_count": len(blocked_nodes),
                "independent_nodes": independent_nodes,
                "independent_count": len(independent_nodes),
            },
            "raw_error": error_msg,
        }

        return IntegrationExecutionResult(
            executed=True,
            status=ExecutionStatus.SUCCEEDED,
            verified=False,
            verification_required=True,
            output=diagnosis,
            duration_ms=(time.perf_counter() - start_time) * 1000,
            metadata={"planner": "ARE.FailureDiagnostician", "root_cause": root_cause},
        )

    async def _handle_recover_plan(
        self,
        params: dict[str, Any],
        start_time: float,
    ) -> IntegrationExecutionResult:
        """Sintetiza una estrategia de contingencia reflexiva para el grafo."""
        raw_graph = params.get("graph", {})
        failed_node_id = params.get("failed_node_id")
        diagnosis = params.get("diagnosis")

        if not failed_node_id:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                error="El parámetro 'failed_node_id' es obligatorio",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        raw_nodes = raw_graph.get("nodes", {}) if isinstance(raw_graph, dict) else {}
        failed_node = raw_nodes.get(failed_node_id, {})
        is_critical = failed_node.get("is_critical", True)

        root_cause = diagnosis.get("root_cause") if isinstance(diagnosis, dict) else "UNKNOWN"

        if not is_critical:
            recommended_action = RecoveryActionType.SKIP
            rationale = "El nodo que falló no está marcado como crítico; se puede omitir para continuar con las tareas restantes."
            recovery_plan_nodes = []
        elif root_cause == "NETWORK_OR_PROCESS_TIMEOUT":
            recommended_action = RecoveryActionType.RETRY
            rationale = "Fallo transitorio por tiempo de espera; se recomienda reintento con backoff y timeout extendido."
            recovery_plan_nodes = [
                {
                    "action": "retry_with_backoff",
                    "target_node_id": failed_node_id,
                    "backoff_seconds": 2.0,
                    "timeout_factor": 1.5,
                }
            ]
        elif root_cause in ("RESOURCE_NOT_FOUND", "PERMISSION_OR_SECURITY_RESTRICTION"):
            recommended_action = RecoveryActionType.ASK_USER
            rationale = f"Fallo estructural ({root_cause}); requiere intervención o decisión explícita del usuario."
            recovery_plan_nodes = []
        else:
            # Estrategia general: Ofrecer rama alternativa o detener
            recommended_action = RecoveryActionType.ALTERNATIVE_BRANCH
            rationale = "Se sugiere intentar una ruta alternativa o consultar al usuario para redefinir el paso."
            recovery_plan_nodes = [
                {
                    "action": "substitute_action",
                    "target_node_id": failed_node_id,
                    "alternative_action": "system.fallback_query",
                }
            ]

        output_data = {
            "failed_node_id": failed_node_id,
            "recommended_action": recommended_action.value,
            "rationale": rationale,
            "recovery_steps": recovery_plan_nodes,
        }

        return IntegrationExecutionResult(
            executed=True,
            status=ExecutionStatus.SUCCEEDED,
            verified=False,
            verification_required=True,
            output=output_data,
            duration_ms=(time.perf_counter() - start_time) * 1000,
            metadata={"planner": "ARE.RecoveryStrategist", "action": recommended_action.value},
        )
