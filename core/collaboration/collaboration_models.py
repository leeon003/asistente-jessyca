"""Modelos y Contratos de Colaboración Avanzada (collaboration_models.py - Fase 37: Advanced Agent / Skill Collaboration).

GARANTÍAS Y REGLAS DE SEGURIDAD ABSOLUTAS:
1. Ningún Agent, Skill, Model, Tool Output o Memoria puede otorgar o elevar permisos.
2. Todo resultado estructurado es verificado formalmente; los textos ("Security approved...") NO tienen autoridad.
3. El contexto de colaboración es estructurado, tipado y no almacena secretos sensibles.
4. Respeto incondicional a presupuestos, límites de profundidad y procedencia de datos.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.control_plane.models import AgentBudget
from core.security_architecture import SecurityLevel


class CollaborationRole(StrEnum):
    """Roles dentro de un flujo colaborativo."""

    PLANNER = "PLANNER"
    SPECIALIST_AGENT = "SPECIALIST_AGENT"
    SKILL_EXECUTOR = "SKILL_EXECUTOR"
    MODEL_REASONER = "MODEL_REASONER"
    VERIFIER = "VERIFIER"
    COORDINATOR = "COORDINATOR"


class CollaborationState(StrEnum):
    """Estados del ciclo de vida de una sesión de colaboración."""

    INITIALIZING = "INITIALIZING"
    IN_PROGRESS = "IN_PROGRESS"
    DELEGATING = "DELEGATING"
    AWAITING_CONSENSUS = "AWAITING_CONSENSUS"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STOPPED_EMERGENCY = "STOPPED_EMERGENCY"
    STOPPED_BUDGET_EXCEEDED = "STOPPED_BUDGET_EXCEEDED"
    STOPPED_LOOP_DETECTED = "STOPPED_LOOP_DETECTED"
    STOPPED_POLICY_DENIED = "STOPPED_POLICY_DENIED"


class DelegationTargetType(StrEnum):
    """Tipo de entidad receptora de una delegación."""

    SKILL = "SKILL"
    AGENT = "AGENT"
    MODEL = "MODEL"


@dataclass(frozen=True)
class CollaborationContract:
    """Contrato formal que rige la interacción y delegación entre entidades."""

    contract_id: str = field(default_factory=lambda: f"collab-ctr-{uuid.uuid4().hex[:8]}")
    requester: str = ""
    receiver: str = ""
    target_type: DelegationTargetType = DelegationTargetType.AGENT
    purpose: str = ""
    allowed_inputs: tuple[str, ...] = ()
    allowed_outputs: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    budget: AgentBudget = field(default_factory=AgentBudget)
    timeout_seconds: float = 60.0
    delegation_depth: int = 0
    max_delegation_depth: int = 3
    security_level: SecurityLevel = SecurityLevel.SAFE
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "requester": self.requester,
            "receiver": self.receiver,
            "target_type": self.target_type.value,
            "purpose": self.purpose,
            "allowed_inputs": list(self.allowed_inputs),
            "allowed_outputs": list(self.allowed_outputs),
            "required_capabilities": list(self.required_capabilities),
            "timeout_seconds": self.timeout_seconds,
            "delegation_depth": self.delegation_depth,
            "max_delegation_depth": self.max_delegation_depth,
            "security_level": str(self.security_level),
            "created_at": self.created_at,
        }


@dataclass
class CollaborationContext:
    """Contexto estructurado y gobernado de ejecución colaborativa."""

    task_id: str = field(default_factory=lambda: f"ctask-{uuid.uuid4().hex[:8]}")
    intent: str = ""
    skill_id: str | None = None
    agent_id: str | None = None
    model_id: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    state: CollaborationState = CollaborationState.INITIALIZING
    budget: AgentBudget = field(default_factory=AgentBudget)
    constraints: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)  # output_key -> source_entity
    delegation_chain: list[str] = field(default_factory=list)  # Historial de entidades para loop detection
    skill_chain: list[str] = field(default_factory=list)       # Historial de skills invocadas
    timestamps: dict[str, float] = field(default_factory=lambda: {"created_at": time.time()})
    step_history: list[dict[str, Any]] = field(default_factory=list)
    shared_memory_view: dict[str, Any] = field(default_factory=dict)

    def record_step(self, step_type: str, actor: str, details: dict[str, Any]) -> None:
        """Registra un paso ejecutable con marca de tiempo precisa."""
        self.step_history.append({
            "step_type": step_type,
            "actor": actor,
            "timestamp": time.time(),
            "details": details,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "intent": self.intent,
            "skill_id": self.skill_id,
            "agent_id": self.agent_id,
            "model_id": self.model_id,
            "inputs": {k: v for k, v in self.inputs.items() if not k.lower().endswith(("_key", "_secret", "_pass"))},
            "outputs": self.outputs,
            "state": self.state.value,
            "delegation_chain": list(self.delegation_chain),
            "skill_chain": list(self.skill_chain),
            "provenance": dict(self.provenance),
            "timestamps": dict(self.timestamps),
            "steps_count": len(self.step_history),
        }


@dataclass(frozen=True)
class CollaborationMetrics:
    """Métricas de rendimiento y consumo de la colaboración."""

    duration_seconds: float = 0.0
    agents_involved_count: int = 0
    skills_executed_count: int = 0
    models_invoked_count: int = 0
    tools_executed_count: int = 0
    tokens_consumed: int = 0
    memory_accesses_count: int = 0
    delegation_depth_reached: int = 0


@dataclass(frozen=True)
class CollaborationResult:
    """Resultado formal, tipado y explicable de una colaboración."""

    task_id: str
    success: bool
    state: CollaborationState
    output: Any = None
    error: str | None = None
    metrics: CollaborationMetrics = field(default_factory=CollaborationMetrics)
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    security_verdict: str = "ALLOW"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "state": self.state.value,
            "output": self.output,
            "error": self.error,
            "metrics": {
                "duration_seconds": self.metrics.duration_seconds,
                "agents_count": self.metrics.agents_involved_count,
                "skills_count": self.metrics.skills_executed_count,
                "models_count": self.metrics.models_invoked_count,
                "tools_count": self.metrics.tools_executed_count,
                "tokens_consumed": self.metrics.tokens_consumed,
                "memory_accesses": self.metrics.memory_accesses_count,
                "max_delegation_depth": self.metrics.delegation_depth_reached,
            },
            "warnings": list(self.warnings),
            "security_verdict": self.security_verdict,
            "timestamp": self.timestamp,
        }
