"""JESSYCA BRAIN 1.0 — Núcleo Cognitivo Unificado (core/cognitive_brain).

Integra razonamiento, planificación, memoria estructurada de 4 niveles y
aprendizaje continuo de procedimientos bajo gobernanza estricta.
"""

from __future__ import annotations

from core.cognitive_brain.brain_orchestrator import BrainExecutionResult, BrainTaskCheckpoint, JessycaBrain
from core.cognitive_brain.memory_engine import EpisodeRecord, EpisodicMemory, MemoryEngine, ProceduralMemory, WorkingMemory
from core.cognitive_brain.planner_engine import PlannerEngine
from core.cognitive_brain.procedure_learning_engine import ProcedureLearningEngine
from core.cognitive_brain.reasoning_engine import ReasoningEngine

__version__ = "1.0.0-BRAIN"

__all__ = [
    "BrainExecutionResult",
    "BrainTaskCheckpoint",
    "EpisodeRecord",
    "EpisodicMemory",
    "JessycaBrain",
    "MemoryEngine",
    "PlannerEngine",
    "ProceduralMemory",
    "ProcedureLearningEngine",
    "ReasoningEngine",
    "WorkingMemory",
]
