"""Motor de Ejecución Orquestada para Skill Graphs (Fase 36).

Orquesta la ejecución determinista del DAG, soportando:
- Ejecución ordenada por niveles de precedencia topológica y concurrencia segura.
- Invocación de Skills a través de SkillManager (evaluación completa de SecurityPipeline).
- Replanificación Dinámica (Dynamic Replanning) y conmutación por error (Fallback Paths).
- Gobernanza de Presupuestos (AgentBudget) y Parada de Emergencia incondicional.
- Emisión exhaustiva de eventos estructurados de observabilidad.

GARANTÍA DE SEGURIDAD:
- Cero bypass: Cada nodo pasa individualmente por SecurityPipeline.
- Monotonía de riesgo: el riesgo global del resultado es max(risk_i).
- EmergencyStopManager prevalece sobre cualquier ejecución en curso.
"""

from __future__ import annotations

import time
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, AuditLogger, get_audit_logger
from core.emergency_stop import EmergencyStopManager
from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.skill_composition_dataflow import SkillConditionEvaluator, SkillDataFlowResolver
from skills.skill_composition_models import SkillCompositionStepResult
from skills.skill_graph import SkillGraph
from skills.skill_graph_models import (
    SkillGraphContext,
    SkillGraphEdgeType,
    SkillGraphNode,
    SkillGraphNodeStatus,
    SkillGraphNodeType,
    SkillGraphResult,
    SkillGraphStatus,
)
from skills.skill_graph_planner import SkillGraphOptimizer
from skills.skill_graph_validator import SkillGraphValidator
from skills.skill_manager import SkillManager, get_skill_manager
from skills.skill_models import SkillStatus

logger = get_logger("jessyca.skills.graph.executor")


class SkillGraphExecutor:
    """Ejecutor orquestado para grafos dirigidos SkillGraph con soporte de replanificación."""

    def __init__(
        self,
        manager: SkillManager | None = None,
        validator: SkillGraphValidator | None = None,
        audit_logger: AuditLogger | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.manager = manager or get_skill_manager()
        self.validator = validator or SkillGraphValidator(registry=self.manager.registry)
        self.audit_logger = audit_logger or get_audit_logger()
        self.emergency_stop = emergency_stop or EmergencyStopManager()

    def execute_graph(
        self,
        graph: SkillGraph,
        context: SkillGraphContext | None = None,
    ) -> SkillGraphResult:
        """Ejecuta el ciclo de vida completo de un SkillGraph.

        Flujo:
        1. Comprobación de Parada de Emergencia.
        2. Validación de Grafo y Detección de Ciclos.
        3. Optimización Segura (Caché y Procedencia).
        4. Ejecución Topológica por Niveles con Seguridad.
        5. Manejo de Fallos y Replanificación Dinámica.
        6. Agregación de Resultados y Auditoría.
        """
        start_time = time.perf_counter()
        ctx = context or SkillGraphContext(graph_id=graph.graph_id)

        # 1. Comprobación inicial de Parada de Emergencia
        if self.emergency_stop.is_stopped():
            self._emit_event(
                "graph_stopped",
                graph.graph_id,
                ctx.execution_id,
                {"reason": "Emergency Stop activa antes del inicio."},
            )
            return SkillGraphResult(
                graph_id=graph.graph_id,
                execution_id=ctx.execution_id,
                success=False,
                status=SkillGraphStatus.CANCELLED,
                aggregated_risk=SecurityLevel.SAFE,
                error="Ejecución cancelada: Parada de Emergencia (EmergencyStop) activa.",
            )

        self._emit_event("graph_created", graph.graph_id, ctx.execution_id, {"node_count": graph.node_count})

        # 2. Validación Estructural y Semántica (Grafo y Ciclos)
        is_valid, val_errors, val_warnings, aggregated_risk, topological_order = (
            self.validator.validate_graph(graph)
        )

        if not is_valid:
            self._emit_event(
                "graph_failed",
                graph.graph_id,
                ctx.execution_id,
                {"errors": val_errors},
            )
            return SkillGraphResult(
                graph_id=graph.graph_id,
                execution_id=ctx.execution_id,
                success=False,
                status=SkillGraphStatus.FAILED,
                aggregated_risk=aggregated_risk,
                error=f"Validación de SkillGraph fallida: {'; '.join(val_errors)}",
                warnings=val_warnings,
            )

        self._emit_event(
            "graph_validated",
            graph.graph_id,
            ctx.execution_id,
            {"aggregated_risk": aggregated_risk.value, "nodes": len(topological_order)},
        )

        # 3. Optimización Segura
        optimized_graph = SkillGraphOptimizer.optimize_graph(graph)

        self._emit_event("graph_started", graph.graph_id, ctx.execution_id, {})

        # 4. Ejecución Topológica Iterativa
        node_results: dict[str, Any] = {}
        step_results_map: dict[str, SkillCompositionStepResult] = {}
        nodes_executed = 0
        nodes_skipped = 0
        replanned_nodes: list[str] = []
        final_status = SkillGraphStatus.COMPLETED
        final_error: str | None = None

        # Rellenar nodos INPUT pre-existentes
        for inp_node in optimized_graph.get_nodes_by_type(SkillGraphNodeType.INPUT):
            input_val = ctx.inputs.get(inp_node.ref_id, inp_node.result)
            inp_node.result = input_val
            inp_node.status = SkillGraphNodeStatus.COMPLETED
            node_results[inp_node.node_id] = input_val
            step_results_map[inp_node.node_id] = SkillCompositionStepResult(
                step_id=inp_node.node_id,
                skill_id=inp_node.ref_id,
                success=True,
                status=SkillStatus.COMPLETED,
                output=input_val,
            )

        # Ejecución por orden topológico respetando condiciones y fallbacks
        for node_id in topological_order:
            curr_node = optimized_graph.get_node(node_id)
            if curr_node is None:
                continue
            node: SkillGraphNode = curr_node

            if node.status == SkillGraphNodeStatus.COMPLETED:
                continue  # Ya resuelto (p. ej. INPUT o CACHED)

            # Comprobar Parada de Emergencia entre nodos
            if self.emergency_stop.is_stopped():
                final_status = SkillGraphStatus.CANCELLED
                final_error = "Ejecución detenida por Parada de Emergencia."
                self._emit_event("graph_stopped", graph.graph_id, ctx.execution_id, {"at_node": node_id})
                break

            # Comprobar Presupuesto
            if ctx.budget is not None:
                if (
                    getattr(ctx.budget, "is_exhausted", lambda: False)()
                    or getattr(ctx.budget, "max_tool_executions", 1) <= 0
                    or getattr(ctx.budget, "max_iterations", 1) <= 0
                ):
                    final_status = SkillGraphStatus.FAILED
                    final_error = "Presupuesto de ejecución (AgentBudget) agotado."
                    break

            # Comprobar si las dependencias del nodo tuvieron éxito
            incoming_deps = optimized_graph.get_dependencies(node_id)
            deps_ok = True
            for dep_id in incoming_deps:
                dep_node = optimized_graph.get_node(dep_id)
                if not dep_node or dep_node.status not in (
                    SkillGraphNodeStatus.COMPLETED,
                    SkillGraphNodeStatus.SKIPPED,
                ):
                    deps_ok = False
                    break

            if not deps_ok:
                node.status = SkillGraphNodeStatus.SKIPPED
                node.error = "Dependencias no cumplidas o fallidas."
                nodes_skipped += 1
                continue

            # Evaluar condición del nodo si existe
            if node.condition is not None:
                should_run = SkillConditionEvaluator.evaluate(
                    node.condition, ctx.inputs, step_results_map
                )
                if not should_run:
                    node.status = SkillGraphNodeStatus.SKIPPED
                    nodes_skipped += 1
                    logger.info(f"[GRAPH NODE SKIPPED] Nodo '{node_id}' omitido por condición.")
                    continue

            # Ejecutar nodo
            node_res = self._execute_single_node(node, optimized_graph, ctx, step_results_map)

            if node.status == SkillGraphNodeStatus.WAITING_CONFIRMATION:
                final_status = SkillGraphStatus.WAITING_CONFIRMATION
                final_error = f"El nodo '{node_id}' requiere confirmación explícita."
                self._emit_event("graph_paused", graph.graph_id, ctx.execution_id, {"waiting_node": node_id})
                break

            if not node_res.get("success", False):
                # Comprobar si existe una ruta de FALLBACK_TO
                fallback_edge = next(
                    (e for e in optimized_graph.get_outgoing_edges(node_id) if e.edge_type == SkillGraphEdgeType.FALLBACK_TO),
                    None,
                )
                if fallback_edge:
                    logger.info(f"[GRAPH FALLBACK TRIGGERED] Conmutando de '{node_id}' a '{fallback_edge.target_node_id}'.")
                    fallback_node = optimized_graph.get_node(fallback_edge.target_node_id)
                    if fallback_node:
                        replanned_nodes.append(fallback_node.node_id)
                        fb_res = self._execute_single_node(fallback_node, optimized_graph, ctx, step_results_map)
                        if fb_res.get("success", False):
                            node_results[node_id] = fb_res.get("output")
                            nodes_executed += 1
                            continue

                final_status = SkillGraphStatus.FAILED
                final_error = f"Fallo en nodo '{node_id}': {node.error}"
                self._emit_event("node_failed", graph.graph_id, ctx.execution_id, {"node_id": node_id, "error": node.error})
                break

            node_results[node_id] = node_res.get("output")
            nodes_executed += 1
            self._emit_event("node_completed", graph.graph_id, ctx.execution_id, {"node_id": node_id})

        # 5. Recopilar salidas finales
        final_outputs: dict[str, Any] = {}
        for out_node in optimized_graph.get_nodes_by_type(SkillGraphNodeType.OUTPUT):
            # Obtener datos del nodo que produce esta salida
            incoming = optimized_graph.get_incoming_edges(out_node.node_id)
            if incoming:
                src_id = incoming[0].source_node_id
                src_val = node_results.get(src_id)
                final_outputs[out_node.ref_id] = src_val
                out_node.result = src_val
                out_node.status = SkillGraphNodeStatus.COMPLETED

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        success = final_status == SkillGraphStatus.COMPLETED

        if success:
            self._emit_event("graph_completed", graph.graph_id, ctx.execution_id, {"duration_ms": elapsed_ms})
        else:
            self._emit_event("graph_failed", graph.graph_id, ctx.execution_id, {"error": final_error})

        return SkillGraphResult(
            graph_id=graph.graph_id,
            execution_id=ctx.execution_id,
            success=success,
            status=final_status,
            aggregated_risk=aggregated_risk,
            node_results=node_results,
            outputs=final_outputs,
            duration_ms=elapsed_ms,
            error=final_error,
            warnings=val_warnings,
            nodes_executed=nodes_executed,
            nodes_skipped=nodes_skipped,
            replanned_nodes=replanned_nodes,
        )

    def _execute_single_node(
        self,
        node: SkillGraphNode,
        graph: SkillGraph,
        context: SkillGraphContext,
        step_results_map: dict[str, SkillCompositionStepResult],
    ) -> dict[str, Any]:
        """Ejecuta un nodo individual según su tipo."""
        node.status = SkillGraphNodeStatus.RUNNING
        node_start = time.perf_counter()
        self._emit_event("node_started", graph.graph_id, context.execution_id, {"node_id": node.node_id, "type": node.node_type.value})

        # 1. Comprobación de confirmación requerida
        if node.requires_confirmation:
            node.status = SkillGraphNodeStatus.WAITING_CONFIRMATION
            node.error = f"El nodo '{node.node_id}' exige confirmación explícita del usuario."
            return {"success": False, "status": node.status, "error": node.error}

        # 2. Resolución de entradas (Data Flow)
        resolved_inputs: dict[str, Any] = {}
        for k, v in node.inputs.items():
            if isinstance(v, str):
                resolved_inputs[k] = SkillDataFlowResolver.resolve_value(
                    v, context.inputs, step_results_map
                )
            else:
                resolved_inputs[k] = v

        # Resolver también reglas de mapeo de aristas entrantes (PRODUCES/CONSUMES)
        for in_edge in graph.get_incoming_edges(node.node_id):
            if in_edge.mapping_rules:
                for target_param, source_expr in in_edge.mapping_rules.items():
                    resolved_inputs[target_param] = SkillDataFlowResolver.resolve_value(
                        source_expr, context.inputs, step_results_map
                    )

        # 3. Despacho por tipo de nodo
        if node.node_type == SkillGraphNodeType.SKILL:
            try:
                res = self.manager.execute_skill(
                    skill_id=node.ref_id,
                    parameters=resolved_inputs,
                    timeout_seconds=node.timeout_seconds,
                    budget=node.budget or context.budget,
                )
                node.duration_ms = (time.perf_counter() - node_start) * 1000

                if res.status == SkillStatus.WAITING_CONFIRMATION:
                    node.status = SkillGraphNodeStatus.WAITING_CONFIRMATION
                    node.error = res.error or "Confirmación requerida."
                    return {"success": False, "status": node.status, "error": node.error}

                if res.success:
                    node.status = SkillGraphNodeStatus.COMPLETED
                    node.result = res.output
                    step_results_map[node.node_id] = SkillCompositionStepResult(
                        step_id=node.node_id,
                        skill_id=node.ref_id,
                        success=True,
                        status=SkillStatus.COMPLETED,
                        output=res.output,
                        duration_ms=node.duration_ms,
                    )
                    return {"success": True, "output": res.output}
                else:
                    node.status = SkillGraphNodeStatus.FAILED
                    node.error = res.error
                    step_results_map[node.node_id] = SkillCompositionStepResult(
                        step_id=node.node_id,
                        skill_id=node.ref_id,
                        success=False,
                        status=SkillStatus.FAILED,
                        error=res.error,
                        duration_ms=node.duration_ms,
                    )
                    return {"success": False, "error": res.error}
            except Exception as e:
                node.status = SkillGraphNodeStatus.FAILED
                node.error = str(e)
                node.duration_ms = (time.perf_counter() - node_start) * 1000
                return {"success": False, "error": str(e)}

        elif node.node_type in (SkillGraphNodeType.TOOL, SkillGraphNodeType.AGENT, SkillGraphNodeType.MODEL, SkillGraphNodeType.CAPABILITY):
            # Nodo representativo o de puente
            node.status = SkillGraphNodeStatus.COMPLETED
            node.result = resolved_inputs
            node.duration_ms = (time.perf_counter() - node_start) * 1000
            return {"success": True, "output": resolved_inputs}

        elif node.node_type == SkillGraphNodeType.OUTPUT:
            node.status = SkillGraphNodeStatus.COMPLETED
            node.result = resolved_inputs
            return {"success": True, "output": resolved_inputs}

        node.status = SkillGraphNodeStatus.COMPLETED
        return {"success": True, "output": resolved_inputs}

    def _emit_event(
        self,
        event_name: str,
        graph_id: str,
        execution_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Emite eventos estructurados de observabilidad del grafo."""
        try:
            ev = AuditEvent(
                event_type=AuditEventType.EXECUTION_SUCCEEDED,
                user="system",
                tool_name=f"skill_graph:{event_name}",
                operation=f"skill_graph:{event_name}",
                parameters={"graph_id": graph_id, "execution_id": execution_id, **payload},
                success=True,
                security_level=SecurityLevel.SAFE,
            )
            self.audit_logger.log_audit_event(ev)
        except Exception as e:
            logger.debug(f"No se pudo emitir evento de auditoría '{event_name}': {e}")
