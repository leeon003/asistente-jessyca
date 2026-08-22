"""Modelos y tipos de datos formales para el Skill Graph Engine (Fase 36).

Define los tipos de nodos, tipos de aristas, estados de ejecución, estructuras de datos
para el grafo, entradas de caché con procedencia y resultados de ejecución.

GARANTÍA DE SEGURIDAD:
- Tipado estricto e inmutable en representaciones de grafo.
- Monotonía en agregación de riesgos: max(risk_i).
- Sin código dinámico ejecutable en definiciones de aristas.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.control_plane.models import AgentBudget
from core.security_architecture import SecurityLevel


class SkillGraphNodeType(StrEnum):
    """Tipos de nodos admitidos en el Skill Graph."""

    SKILL = "SKILL"
    COMPOSITION = "COMPOSITION"
    TOOL = "TOOL"
    AGENT = "AGENT"
    MODEL = "MODEL"
    CAPABILITY = "CAPABILITY"
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    CONDITION = "CONDITION"


class SkillGraphEdgeType(StrEnum):
    """Tipos de relaciones dirigidas admitidas en el Skill Graph."""

    DEPENDS_ON = "DEPENDS_ON"
    PRODUCES = "PRODUCES"
    CONSUMES = "CONSUMES"
    REQUIRES = "REQUIRES"
    USES = "USES"
    DELEGATES_TO = "DELEGATES_TO"
    SELECTS = "SELECTS"
    CONDITION = "CONDITION"
    FALLBACK_TO = "FALLBACK_TO"


class SkillGraphNodeStatus(StrEnum):
    """Estados del ciclo de vida de un nodo durante la ejecución del grafo."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"


class SkillGraphStatus(StrEnum):
    """Estados globales de ejecución del Skill Graph."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STOPPED = "STOPPED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"


@dataclass
class SkillGraphNode:
    """Representación formal de un nodo en el Skill Graph."""

    node_id: str
    node_type: SkillGraphNodeType
    ref_id: str  # ID o nombre de la Skill, Tool, Agent, Model o Capability
    label: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    required_capabilities: list[str] = field(default_factory=list)
    risk_level: SecurityLevel = SecurityLevel.SAFE
    timeout_seconds: float = 60.0
    budget: AgentBudget | None = None
    condition: str | dict[str, Any] | None = None
    requires_confirmation: bool = False
    status: SkillGraphNodeStatus = SkillGraphNodeStatus.PENDING
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Exporta el nodo en formato estructurado para auditoría y visualización."""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "ref_id": self.ref_id,
            "label": self.label or self.node_id,
            "status": self.status.value,
            "risk_level": self.risk_level.value,
            "requires_confirmation": self.requires_confirmation,
            "duration_ms": self.duration_ms,
            "has_result": self.result is not None,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


@dataclass
class SkillGraphEdge:
    """Representación formal de una arista dirigida en el Skill Graph."""

    source_node_id: str
    target_node_id: str
    edge_type: SkillGraphEdgeType
    mapping_rules: dict[str, str] = field(default_factory=dict)  # target_param -> source_param / expr
    condition: str | dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Exporta la arista en formato estructurado."""
        return {
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "edge_type": self.edge_type.value,
            "mapping_rules": dict(self.mapping_rules),
            "condition": self.condition,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GraphCacheEntry:
    """Entrada de caché estructurada con validación de procedencia y vigencia."""

    source: str
    timestamp: float
    scope: str
    provenance: str
    ttl_seconds: float
    value: Any

    def is_valid(self, current_time: float | None = None) -> bool:
        """Determina si la entrada de caché sigue siendo válida en tiempo y ámbito."""
        now = current_time if current_time is not None else time.time()
        return (now - self.timestamp) <= self.ttl_seconds


@dataclass
class SkillGraphContext:
    """Contexto de ejecución para un Skill Graph."""

    graph_id: str
    execution_id: str = field(default_factory=lambda: f"gexec_{uuid.uuid4().hex[:8]}")
    inputs: dict[str, Any] = field(default_factory=dict)
    budget: AgentBudget | None = None
    max_nodes: int = 100
    max_depth: int = 20
    global_timeout_seconds: float = 300.0
    cancellation_token: Any = None
    cache_enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillGraphResult:
    """Resultado formal y completo de la ejecución de un Skill Graph."""

    graph_id: str
    execution_id: str
    success: bool
    status: SkillGraphStatus
    aggregated_risk: SecurityLevel
    node_results: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    nodes_executed: int = 0
    nodes_skipped: int = 0
    replanned_nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Exporta el resultado estructurado para auditoría y visualización."""
        return {
            "graph_id": self.graph_id,
            "execution_id": self.execution_id,
            "success": self.success,
            "status": self.status.value,
            "aggregated_risk": self.aggregated_risk.value,
            "node_results": self.node_results,
            "outputs": self.outputs,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "warnings": self.warnings,
            "nodes_executed": self.nodes_executed,
            "nodes_skipped": self.nodes_skipped,
            "replanned_nodes": self.replanned_nodes,
        }
