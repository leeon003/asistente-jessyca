"""Jerarquía de excepciones tipadas para ARE (Action Reasoning Engine) y Planificación General.

Define excepciones específicas para resolución de herramientas, validación de planes (DAG, parámetros,
sandboxing, políticas), dependencias de flujo de datos y gobernanza de replanificación.
"""

from __future__ import annotations

from typing import Any
from core.exceptions import JessycaError


class AREPlanError(JessycaError):
    """Excepción base para fallos durante la planificación, validación o ejecución de ARE."""

    pass


class UnresolvableActionError(AREPlanError):
    """Excepción lanzada cuando una acción propuesta no resuelve a ninguna herramienta concreta ni implementable."""

    pass


class PlanValidationError(AREPlanError):
    """Excepción lanzada cuando una propuesta de plan falla validaciones estructurales (DAG, parámetros, capacidad)."""

    pass


class MissingOutputDependencyError(AREPlanError):
    """Excepción lanzada cuando un paso depende de una salida de un paso previo que no existe, es nula o falló."""

    pass


class PlanBudgetExceededError(AREPlanError):
    """Excepción lanzada cuando un plan excede el presupuesto máximo de pasos o tiempo de ejecución."""

    pass


class ReplanningDenialViolationError(AREPlanError):
    """Excepción lanzada cuando un intento de replanificación intenta borrar una denegación previa o ampliar permisos."""

    pass


class SandboxViolationError(AREPlanError):
    """Excepción lanzada cuando un paso intenta acceder o escribir rutas fuera de los límites del sandbox permitido."""

    pass


class PlanClarificationRequired(AREPlanError):
    """Excepción lanzada cuando un plan carece de destinos o recursos esenciales y requiere aclaración del usuario."""

    def __init__(self, message: str, missing_resource: str, prompt: str) -> None:
        super().__init__(message, code="PlanClarificationRequired", details={"missing_resource": missing_resource, "prompt": prompt})
        self.missing_resource = missing_resource
        self.prompt = prompt
