"""Submódulo ARE (Action Reasoning Engine) gobernado para JESSYCA PC.

Exporta los contratos y el coordinador de tiempo de ejecución para la mediación
segura de descomposición de planes (DAG), evaluación estructural y recuperación.
"""

from core.are.models import (
    AREDiagnosis,
    AREPlanProposal,
    ARERecoveryProposal,
    ARERuntimeMode,
    AREStepProposal,
)
from core.are.runtime import (
    ARERuntime,
    get_are_runtime,
    reset_are_runtime,
)

__all__ = [
    "ARERuntimeMode",
    "AREStepProposal",
    "AREPlanProposal",
    "AREDiagnosis",
    "ARERecoveryProposal",
    "ARERuntime",
    "get_are_runtime",
    "reset_are_runtime",
]
