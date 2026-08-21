"""Constructor de planes estructurados y verificables (plan_builder.py - Fase 23).

Convierte intenciones complejas del usuario en un ExecutionPlan con precondiciones,
dependencias, asignación de agentes, herramientas requeridas y criterios de éxito.

INVARIANTE DE SEGURIDAD:
PLANNER != AUTHORIZATION (El plan generado es una propuesta sujeta a validación y security checks).
"""

from __future__ import annotations

from typing import Any

from core.logger import get_logger
from core.planning.plan_models import ExecutionPlan, PlanStep
from core.security_architecture import SecurityLevel

logger = get_logger("jessyca.planning.builder")


class PlanBuilder:
    """Constructor y sintetizador de planes de ejecución formal."""

    @classmethod
    def create_custom_plan(
        cls,
        goal: str,
        steps: list[PlanStep],
        max_total_timeout_seconds: float = 120.0,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        """Crea un ExecutionPlan a partir de pasos definidos explícitamente."""
        return ExecutionPlan.create(
            goal=goal,
            steps=steps,
            max_total_timeout_seconds=max_total_timeout_seconds,
            metadata=metadata,
        )

    @classmethod
    def build_file_organization_plan(cls, target_dir: str = "sandbox/docs") -> ExecutionPlan:
        """Genera el plan estructurado del ejemplo formal: 'Organiza mis archivos de trabajo'."""
        steps = [
            PlanStep(
                step_id="step_1_identify",
                description=f"Identificar archivos en el directorio objetivo '{target_dir}'",
                required_agent="agent_file",
                required_tool="filesystem.list_directory",
                tool_parameters={"path": target_dir},
                dependencies=(),
                risk_level=SecurityLevel.SAFE,
                preconditions=("Directorio accesible en sandbox",),
                expected_outcome="Lista de archivos y metadatos",
                success_criteria="len(files) >= 0",
                timeout_seconds=10.0,
            ),
            PlanStep(
                step_id="step_2_analyze",
                description="Analizar categorías y extensiones de archivos encontrados",
                required_agent="agent_system",
                required_tool=None,
                tool_parameters={},
                dependencies=("step_1_identify",),
                risk_level=SecurityLevel.SAFE,
                preconditions=("Paso 1 completado exitosamente",),
                expected_outcome="Matriz de clasificación por tipo de archivo",
                success_criteria="Categorías determinadas",
                timeout_seconds=10.0,
            ),
            PlanStep(
                step_id="step_3_propose",
                description="Construir propuesta estructurada de reubicación de archivos",
                required_agent="agent_file",
                required_tool=None,
                tool_parameters={},
                dependencies=("step_2_analyze",),
                risk_level=SecurityLevel.SAFE,
                preconditions=("Categorías analizadas",),
                expected_outcome="Plan de movimientos propuestos",
                success_criteria="Propuesta generada",
                timeout_seconds=10.0,
            ),
            PlanStep(
                step_id="step_4_verify_ui",
                description="Mostrar cambios y verificar estado visual de la interfaz si aplica",
                required_agent="agent_desktop",
                required_tool="desktop.screenshot",
                tool_parameters={},
                dependencies=("step_3_propose",),
                risk_level=SecurityLevel.SAFE,
                preconditions=("Propuesta lista",),
                expected_outcome="Captura de verificación de interfaz",
                success_criteria="Screenshot capturado",
                timeout_seconds=15.0,
            ),
            PlanStep(
                step_id="step_5_execute_moves",
                description="Ejecutar reubicación de archivos clasificados",
                required_agent="agent_file",
                required_tool="filesystem.write_file",
                tool_parameters={"operation": "organize"},
                dependencies=("step_4_verify_ui",),
                risk_level=SecurityLevel.LOW,
                preconditions=("Propuesta validada",),
                expected_outcome="Archivos organizados en subcarpetas",
                success_criteria="Operación de escritura exitosa",
                timeout_seconds=20.0,
            ),
            PlanStep(
                step_id="step_6_verify_result",
                description="Verificar integridad de archivos tras la organización",
                required_agent="agent_file",
                required_tool="filesystem.list_directory",
                tool_parameters={"path": target_dir},
                dependencies=("step_5_execute_moves",),
                risk_level=SecurityLevel.SAFE,
                preconditions=("Movimientos ejecutados",),
                expected_outcome="Árbol de directorios organizado",
                success_criteria="Estructura confirmada",
                timeout_seconds=10.0,
            ),
            PlanStep(
                step_id="step_7_report",
                description="Generar informe final de resumen para el usuario",
                required_agent="agent_system",
                required_tool=None,
                tool_parameters={},
                dependencies=("step_6_verify_result",),
                risk_level=SecurityLevel.SAFE,
                preconditions=("Verificación completada",),
                expected_outcome="Resumen de archivos organizados",
                success_criteria="Reporte generado",
                timeout_seconds=10.0,
            ),
        ]
        return cls.create_custom_plan(
            goal=f"Organizar archivos de trabajo en '{target_dir}'",
            steps=steps,
            max_total_timeout_seconds=120.0,
            metadata={"template": "file_organization", "target_dir": target_dir},
        )
