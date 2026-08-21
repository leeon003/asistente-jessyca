"""Coordinador de colaboración y delegación multi-agente (agent_coordinator.py - Fase 9).

Orquesta flujos de trabajo multi-agente y delegaciones autorizadas garantizando:
- Cumplimiento de DelegationPolicy (cero delegaciones arbitrarias).
- Preservación de budgets acotados y límites globales de ejecución.
- Detección de ciclos en grafos de tareas (TaskGraph).
- Inviolabilidad de techos de riesgo y aislamiento de herramientas.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from core.agents.agent_message import AgentMessage, AgentMessageType
from core.agents.base_agent import BaseSpecializedAgent
from core.agents.delegation_policy import DelegationPolicy
from core.agents.desktop_agent import DesktopAgent
from core.agents.file_agent import FileAgent
from core.agents.system_agent import SystemAgent
from core.agents.task_graph import TaskGraph
from core.control_plane.models import AgentBudget, AgentLoopResult, AgentLoopState
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger

logger = get_logger("jessyca.agents.coordinator")


class AgentCoordinator:
    """Coordinador central para colaboración y delegación controlada entre agentes."""

    def __init__(
        self,
        desktop_agent: DesktopAgent | None = None,
        system_agent: SystemAgent | None = None,
        file_agent: FileAgent | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.desktop_agent = desktop_agent or DesktopAgent()
        self.system_agent = system_agent or SystemAgent()
        self.file_agent = file_agent or FileAgent()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()

        self._agents_catalog: dict[str, BaseSpecializedAgent] = {
            self.desktop_agent.identity.agent_id: self.desktop_agent,
            self.system_agent.identity.agent_id: self.system_agent,
            self.file_agent.identity.agent_id: self.file_agent,
        }

    def execute_delegation(
        self,
        sender: BaseSpecializedAgent,
        target_agent_id: str,
        intent: str,
        scope: str,
        context: dict[str, Any] | None = None,
        sub_budget: AgentBudget | None = None,
        delegation_chain: tuple[str, ...] = (),
    ) -> AgentLoopResult:
        """Ejecuta una delegación autorizada desde un agente emisor hacia un agente receptor."""
        sender_id = sender.identity.agent_id

        # 1. Validar política de delegación formal
        verdict = DelegationPolicy.validate_delegation(
            sender_agent_id=sender_id,
            recipient_agent_id=target_agent_id,
            scope=scope,
            delegation_chain=delegation_chain,
        )

        if not verdict.is_allowed:
            return AgentLoopResult(
                task_id=f"del-{uuid.uuid4().hex[:8]}",
                intent=intent,
                final_state=AgentLoopState.STOPPED_PERMISSION_DENIED,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.0,
                stop_reason=verdict.reason,
                output_metadata={"sender_id": sender_id, "target_id": target_agent_id, "scope": scope},
            )

        # 2. Localizar agente destinatario
        target_agent = self._agents_catalog.get(target_agent_id)
        if target_agent is None:
            return AgentLoopResult(
                task_id=f"del-{uuid.uuid4().hex[:8]}",
                intent=intent,
                final_state=AgentLoopState.STOPPED_ERROR,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.0,
                stop_reason=f"Agente destinatario '{target_agent_id}' no encontrado en el catálogo.",
            )

        # 3. Registrar mensaje formal de delegación
        msg = AgentMessage(
            sender_agent_id=sender_id,
            recipient_agent_id=target_agent_id,
            message_type=AgentMessageType.TASK_DELEGATION,
            payload={"intent": intent, "scope": scope, "context": context or {}},
            delegation_depth=len(delegation_chain) + 1,
            delegation_chain=delegation_chain + (sender_id,),
        )
        logger.info(f"[AGENT COORDINATOR] Mensaje de delegación registrado: {msg.message_id}")

        # 4. Ejecutar tarea con el agente destinatario respetando su budget
        effective_context = dict(context or {})
        effective_context["delegation_msg_id"] = msg.message_id
        effective_context["delegated_by"] = sender_id
        effective_context["delegation_scope"] = scope

        return target_agent.run(
            intent=intent,
            context=effective_context,
            task_id=f"task-del-{msg.message_id}",
        )

    def execute_task_graph(
        self,
        graph: TaskGraph,
        global_budget: AgentBudget | None = None,
        initial_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ejecuta ordenadamente un flujo de trabajo definido por un TaskGraph (DAG)."""
        # 1. Comprobar ciclos
        if graph.detect_cycles():
            logger.error("[TASK GRAPH] El grafo contiene dependencias cíclicas. Ejecución cancelada.")
            return {
                "success": False,
                "error": "Ciclo de dependencias detectado en el TaskGraph.",
                "executed_nodes": 0,
                "nodes_results": {},
            }

        start_time = time.monotonic()
        nodes_order = graph.get_topological_order()
        accumulated_context = dict(initial_context or {})
        results: dict[str, Any] = {}
        timeout = global_budget.max_time if global_budget else 60.0

        for node in nodes_order:
            # Comprobar timeout global del grafo
            if (time.monotonic() - start_time) >= timeout:
                node.status = "TIMEOUT"
                node.error = f"Timeout global del grafo excedido ({timeout:.1f}s)."
                results[node.node_id] = {"status": "TIMEOUT", "error": node.error}
                break

            # Comprobar si las dependencias fueron exitosas
            deps_ok = all(
                results.get(dep, {}).get("is_success") is True for dep in node.dependencies
            )
            if not deps_ok and node.dependencies:
                node.status = "SKIPPED"
                node.error = "Dependencias no satisfechas o fallidas."
                results[node.node_id] = {"status": "SKIPPED", "error": node.error, "is_success": False}
                continue

            agent = self._agents_catalog.get(node.agent_id)
            if not agent:
                node.status = "FAILED"
                node.error = f"Agente '{node.agent_id}' no disponible."
                results[node.node_id] = {"status": "FAILED", "error": node.error, "is_success": False}
                break

            node.status = "RUNNING"
            loop_res = agent.run(
                intent=node.intent,
                context=accumulated_context,
                task_id=f"node-{node.node_id}",
            )

            if loop_res.is_success:
                node.status = "COMPLETED"
                node.result = loop_res.output_metadata
                accumulated_context.update(loop_res.output_metadata)
                results[node.node_id] = {
                    "status": "COMPLETED",
                    "is_success": True,
                    "duration_seconds": loop_res.duration_seconds,
                    "result": loop_res.output_metadata,
                }
            else:
                node.status = "FAILED"
                node.error = loop_res.stop_reason
                results[node.node_id] = {
                    "status": "FAILED",
                    "is_success": False,
                    "error": loop_res.stop_reason,
                    "final_state": str(loop_res.final_state),
                }
                # Parada segura ante fallo
                break

        duration = time.monotonic() - start_time
        all_completed = all(n.get("is_success") is True for n in results.values()) and len(results) == graph.node_count

        return {
            "success": all_completed,
            "duration_seconds": duration,
            "executed_nodes": len(results),
            "total_nodes": graph.node_count,
            "nodes_results": results,
            "final_context": accumulated_context,
        }
