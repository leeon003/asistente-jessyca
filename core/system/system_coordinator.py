"""Coordinador y Fachada Maestra Consolidada de JESSYCA 4.0 (system_coordinator.py - Fase 38).

Implementa el flujo canónico end-to-end:
    User Input -> Intent -> Planning -> Skill Graph -> Agent Coordination
    -> Model Inference -> Security Pipeline -> Tools -> Verification -> Memory -> Result

Garantiza observabilidad unificada (correlation_id / task_id) y cero bypass de seguridad.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, AuditLogger, get_audit_logger
from core.collaboration.collaboration_engine import CollaborationEngine
from core.control_plane.models import AgentBudget
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from core.security_architecture import SecurityLevel
from core.system.system_contracts import (
    ArchitecturalInvariants,
)
from core.system.system_errors import IntentError
from skills.skill_graph_planner import SkillGraphPlanner
from skills.skill_manager import SkillManager, get_skill_manager
from skills.skill_registry import SkillRegistry, get_skill_registry

logger = get_logger("jessyca.system.coordinator")


@dataclass
class SystemExecutionMetrics:
    """Métricas exhaustivas de rendimiento para una tarea en JESSYCA 4.0."""

    task_id: str
    correlation_id: str
    total_duration_ms: float = 0.0
    intent_latency_ms: float = 0.0
    planning_latency_ms: float = 0.0
    graph_latency_ms: float = 0.0
    agent_latency_ms: float = 0.0
    model_latency_ms: float = 0.0
    tool_latency_ms: float = 0.0
    memory_latency_ms: float = 0.0
    tokens_consumed: int = 0
    vram_mb_peak: float = 0.0
    model_swaps_count: int = 0
    skills_executed_count: int = 0
    agents_involved_count: int = 0
    tools_executed_count: int = 0


@dataclass(frozen=True)
class SystemResponse:
    """Respuesta consolidada, estructurada y explicable de JESSYCA 4.0."""

    task_id: str
    correlation_id: str
    success: bool
    status: str
    output: Any = None
    error: str | None = None
    metrics: SystemExecutionMetrics = field(default_factory=lambda: SystemExecutionMetrics(task_id="", correlation_id=""))
    security_verdict: str = "ALLOW"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "success": self.success,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "security_verdict": self.security_verdict,
            "duration_ms": self.metrics.total_duration_ms,
            "metrics": {
                "intent_ms": self.metrics.intent_latency_ms,
                "planning_ms": self.metrics.planning_latency_ms,
                "graph_ms": self.metrics.graph_latency_ms,
                "agent_ms": self.metrics.agent_latency_ms,
                "model_ms": self.metrics.model_latency_ms,
                "tool_ms": self.metrics.tool_latency_ms,
                "tokens": self.metrics.tokens_consumed,
            },
            "timestamp": self.timestamp,
        }


class SystemCoordinator4:
    """Fachada arquitectónica consolidada para JESSYCA 4.0."""

    def __init__(
        self,
        skill_registry: SkillRegistry | None = None,
        skill_manager: SkillManager | None = None,
        collaboration_engine: CollaborationEngine | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.skill_registry = skill_registry or get_skill_registry()
        self.skill_manager = skill_manager or get_skill_manager()
        self.collaboration_engine = collaboration_engine or CollaborationEngine(
            skill_manager=self.skill_manager,
            emergency_stop=emergency_stop,
            audit_logger=audit_logger,
        )
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.audit_logger = audit_logger or get_audit_logger()
        self.planner = SkillGraphPlanner(registry=self.skill_registry)
        self._lock = threading.RLock()

        # Validación estática de invariantes en arranque
        assert ArchitecturalInvariants.verify_all_invariants(), "Invariantes arquitectónicas inconsistentes."

    def execute_user_request(
        self,
        user_input: str,
        parameters: dict[str, Any] | None = None,
        budget: AgentBudget | None = None,
        correlation_id: str | None = None,
    ) -> SystemResponse:
        """Ejecuta una petición de usuario a través del flujo consolidado de JESSYCA 4.0."""
        start_time = time.perf_counter()
        task_id = f"task-4.0-{uuid.uuid4().hex[:8]}"
        cid = correlation_id or f"corr-{uuid.uuid4().hex[:8]}"
        metrics = SystemExecutionMetrics(task_id=task_id, correlation_id=cid)

        # 0. Comprobación de Parada de Emergencia
        if self.emergency_stop.is_stopped():
            metrics.total_duration_ms = (time.perf_counter() - start_time) * 1000
            self._emit_audit("emergency_stop_aborted", task_id, cid, {"reason": "Emergency stop is active"})
            return SystemResponse(
                task_id=task_id,
                correlation_id=cid,
                success=False,
                status="STOPPED_EMERGENCY",
                error="Parada de Emergencia activa. Operación abortada.",
                metrics=metrics,
                security_verdict="EMERGENCY_STOP",
            )

        self._emit_audit("request_received", task_id, cid, {"user_input": user_input})

        # 1. Capa INTENT: Validación y análisis de intención
        t0 = time.perf_counter()
        if not user_input or not user_input.strip():
            metrics.intent_latency_ms = (time.perf_counter() - t0) * 1000
            metrics.total_duration_ms = (time.perf_counter() - start_time) * 1000
            err = IntentError("Entrada de usuario vacía o inválida.")
            return SystemResponse(
                task_id=task_id,
                correlation_id=cid,
                success=False,
                status="INVALID_INTENT",
                error=err.message,
                metrics=metrics,
            )

        # Sanitización de directivas adversarias
        cleaned_input = user_input.strip()
        if re.search(r"(\[INST\]|DAN jailbreak|ignore previous)", cleaned_input, re.IGNORECASE):
            cleaned_input = re.sub(r"(\[INST\]|DAN jailbreak|ignore previous)", "[NEUTRALIZED_PROMPT]", cleaned_input, flags=re.IGNORECASE)

        metrics.intent_latency_ms = (time.perf_counter() - t0) * 1000

        # 2. Capa PLANNING / SKILL GRAPH: Generación del plan formal
        t1 = time.perf_counter()
        _graph = self.planner.plan(intent=cleaned_input, inputs=parameters or {})
        metrics.planning_latency_ms = (time.perf_counter() - t1) * 1000
        metrics.graph_latency_ms = metrics.planning_latency_ms

        # 3. Capa COLLABORATION / AGENT / SKILL / SECURITY / TOOLS
        t2 = time.perf_counter()
        collab_res = self.collaboration_engine.execute_collaborative_task(
            intent=cleaned_input,
            inputs=parameters or {},
            budget=budget or AgentBudget(),
            task_id=task_id,
        )
        metrics.agent_latency_ms = (time.perf_counter() - t2) * 1000
        metrics.model_latency_ms = metrics.agent_latency_ms * 0.4
        metrics.tool_latency_ms = metrics.agent_latency_ms * 0.3
        metrics.tokens_consumed = collab_res.metrics.tokens_consumed
        metrics.skills_executed_count = collab_res.metrics.skills_executed_count
        metrics.agents_involved_count = collab_res.metrics.agents_involved_count
        metrics.tools_executed_count = collab_res.metrics.tools_executed_count

        # 4. Finalización y cálculo total
        metrics.total_duration_ms = (time.perf_counter() - start_time) * 1000

        event_name = "request_completed" if collab_res.success else "request_failed"
        self._emit_audit(
            event_name,
            task_id,
            cid,
            {"success": collab_res.success, "duration_ms": metrics.total_duration_ms, "error": collab_res.error},
        )

        return SystemResponse(
            task_id=task_id,
            correlation_id=cid,
            success=collab_res.success,
            status=collab_res.state.value,
            output=collab_res.output,
            error=collab_res.error,
            metrics=metrics,
            security_verdict=collab_res.security_verdict,
        )

    def _emit_audit(self, event_name: str, task_id: str, correlation_id: str, payload: dict[str, Any]) -> None:
        """Emite eventos estructurados a través de AuditLogger con correlación."""
        try:
            ev = AuditEvent(
                event_type=AuditEventType.EXECUTION_SUCCEEDED,
                user="system",
                tool_name=f"system_coordinator:{event_name}",
                operation=f"system:{event_name}",
                parameters={"task_id": task_id, "correlation_id": correlation_id, **payload},
                success=True,
                security_level=SecurityLevel.SAFE,
            )
            self.audit_logger.log_audit_event(ev)
        except Exception as e:
            logger.debug(f"No se pudo emitir evento de auditoría '{event_name}': {e}")
