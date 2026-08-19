"""Definición formal de Niveles de Autonomía para Jessyca 3.0 (Subetapa 16.2).

Proporciona la enumeración inmutable AutonomyLevel y reglas estrictas de ejecución por nivel.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Any


class TaskActionRisk(StrEnum):
    """Clasificación formal de nivel de riesgo para acciones y tareas autónomas."""

    READ_ONLY = "READ_ONLY"
    LOW_RISK = "LOW_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    DANGEROUS = "DANGEROUS"
    CRITICAL = "CRITICAL"


class AutonomyLevel(IntEnum):
    """Niveles formales de autonomía del sistema Jessyca 3.0.

    INVARIANTE DE SEGURIDAD:
    - Ningún nivel permite la ejecución de acciones CRITICAL sin confirmación interactiva humana.
    - El nivel de autonomía NUNCA puede ser modificado por el LLM, memoria, plugins o scheduler.
    """

    LEVEL_0_OBSERVE = 0
    LEVEL_1_SUGGEST = 1
    LEVEL_2_LOW_RISK_EXECUTION = 2
    LEVEL_3_CONFIRMATION_REQUIRED = 3
    LEVEL_4_CONTROLLED_AUTONOMY = 4

    @property
    def label(self) -> str:
        """Etiqueta legible por humanos."""
        return self.name

    @property
    def description(self) -> str:
        """Descripción formal del nivel de autonomía."""
        descriptions = {
            AutonomyLevel.LEVEL_0_OBSERVE: "Modo Observador: Consulta y diagnóstico únicamente. Cero ejecución de herramientas de modificación.",
            AutonomyLevel.LEVEL_1_SUGGEST: "Modo Sugerencia: Generación de propuestas y planes. Cero ejecución autónoma de acciones.",
            AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION: "Modo Ejecución de Bajo Riesgo: Ejecución autónoma de acciones READ_ONLY y LOW_RISK a través del SecureExecutionPipeline.",
            AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED: "Modo Confirmación Requerida: Preparación de acciones de cualquier nivel. Detención obligatoria antes de ejecutar MEDIUM_RISK, DANGEROUS o CRITICAL.",
            AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY: "Modo Autonomía Controlada: Ejecución autónoma de acciones autorizadas por política (hasta MEDIUM_RISK). CRITICAL siempre exige confirmación.",
        }
        return descriptions.get(self, "Nivel de autonomía desconocido.")

    def allows_tool_execution(self) -> bool:
        """Indica si el nivel de autonomía permite cualquier ejecución autónoma de herramientas."""
        return self in (
            AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
            AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
            AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY,
        )

    def is_risk_allowed_auto(self, risk: TaskActionRisk) -> bool:
        """Determina si un nivel de riesgo específico puede ejecutarse de forma automática (sin confirmación) en este nivel de autonomía."""
        if self in (AutonomyLevel.LEVEL_0_OBSERVE, AutonomyLevel.LEVEL_1_SUGGEST):
            return False

        if self == AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION:
            return risk in (TaskActionRisk.READ_ONLY, TaskActionRisk.LOW_RISK)

        if self == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED:
            return risk in (TaskActionRisk.READ_ONLY, TaskActionRisk.LOW_RISK)

        if self == AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY:
            # En LEVEL_4, READ_ONLY, LOW_RISK y MEDIUM_RISK pueden ejecutarse si la política lo aprueba.
            # DANGEROUS y CRITICAL NUNCA se ejecutan automáticamente.
            return risk in (TaskActionRisk.READ_ONLY, TaskActionRisk.LOW_RISK, TaskActionRisk.MEDIUM_RISK)

        return False

    def requires_confirmation_for_risk(self, risk: TaskActionRisk) -> bool:
        """Determina si un nivel de riesgo exige confirmación humana obligatoria en este nivel de autonomía."""
        if risk in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL):
            return True

        if self in (AutonomyLevel.LEVEL_0_OBSERVE, AutonomyLevel.LEVEL_1_SUGGEST):
            return True

        if self == AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION:
            return risk in (TaskActionRisk.MEDIUM_RISK, TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL)

        if self == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED:
            return risk in (TaskActionRisk.MEDIUM_RISK, TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL)

        if self == AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY:
            return risk in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL)

        return True

    def to_dict(self) -> dict[str, Any]:
        """Convierte el nivel a diccionario para auditoría."""
        return {
            "level": self.value,
            "label": self.label,
            "description": self.description,
            "allows_tool_execution": self.allows_tool_execution(),
        }
