"""Controlled Tool Planner para JESSYCA 3.0 (Etapas 19.0, 19.1 y 19.2).

Garantiza la selección y ordenación determinista de herramientas sin otorgar autoridad de ejecución al planner.
Conocimiento integral de capacidades, riesgos, limitaciones y propuestas de alternativas seguras.
Integración con memoria semántica bajo el axioma: MEMORY = EVIDENCE, MEMORY ≠ AUTHORITY.

Componentes:
  - MemoryEvidence, PlanningContext, ToolCandidate, ProposedStep, ToolPlanProposal: Modelos inmutables.
  - ToolDiscoveryService: Descubrimiento de herramientas y consulta de salud.
  - ToolCandidateComparator: Comparación, ordenación y descarte con evidencia y alternativas seguras.
  - ControlledToolPlanner: Generador de planes declarativos con barrera estricta de autoridad.
  - MemoryEvidenceSanitizer, SemanticMemoryPlannerBridge: Sanitización anti-poisoning y filtrado de memoria obsoleta.
"""

from core.tool_planner.comparator import ToolCandidateComparator
from core.tool_planner.controlled_planner import (
    ControlledToolPlanner,
    PlannerAuthorityViolationError,
)
from core.tool_planner.discovery import ToolDiscoveryService
from core.tool_planner.memory_bridge import (
    POISONING_INJECTION_PATTERNS,
    MemoryEvidenceSanitizer,
    MemoryInspectionResult,
    SemanticMemoryPlannerBridge,
)
from core.tool_planner.models import (
    MemoryEvidence,
    PlanningContext,
    ProposedStep,
    ToolCandidate,
    ToolPlanProposal,
)

__all__ = [
    # Models
    "MemoryEvidence",
    "PlanningContext",
    "ToolCandidate",
    "ProposedStep",
    "ToolPlanProposal",
    # Core Planner & Discovery
    "ToolDiscoveryService",
    "ToolCandidateComparator",
    "ControlledToolPlanner",
    "PlannerAuthorityViolationError",
    # Memory Bridge (Etapa 19.2)
    "MemoryEvidenceSanitizer",
    "MemoryInspectionResult",
    "SemanticMemoryPlannerBridge",
    "POISONING_INJECTION_PATTERNS",
]
