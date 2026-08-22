"""Fluent Builder y Adaptador BaseSkill para el Skill Composition Engine (Fase 35).

Proporciona:
1. SkillComposer: Fluent Builder para construir composiciones de forma declarativa y tipada.
2. ComposedSkill: Adaptador que permite envolver cualquier SkillComposition como una BaseSkill de primera clase,
   habilitando su registro en SkillRegistry y enrutamiento en SkillRouter.
"""

from __future__ import annotations

from typing import Any

from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_composition_executor import SkillCompositionExecutor
from skills.skill_composition_models import (
    CompositionErrorPolicy,
    CompositionExecutionMode,
    SkillComposition,
    SkillCompositionContext,
    SkillCompositionResult,
    SkillCompositionStep,
)
from skills.skill_composition_validator import SkillCompositionValidator
from skills.skill_models import (
    SkillContext,
    SkillDefinition,
    SkillResult,
    SkillStatus,
)

logger = get_logger("jessyca.skills.composer")


class SkillComposer:
    """Fluent Builder para la creación de composiciones de Skills."""

    def __init__(self, composition_id: str, name: str, description: str = "") -> None:
        self.composition_id = composition_id
        self.name = name
        self.description = description
        self.version = "1.0.0"
        self._steps: list[SkillCompositionStep] = []
        self._execution_mode = CompositionExecutionMode.SEQUENTIAL
        self._error_policy = CompositionErrorPolicy.FAIL_FAST
        self._inputs_schema: dict[str, Any] = {}
        self._outputs_schema: dict[str, Any] = {}
        self._output_mapping: dict[str, Any] = {}
        self._timeout_seconds: float = 300.0
        self._max_steps: int = 50
        self._risk_ceiling: SecurityLevel | None = None
        self._author: str = "JESSYCA Composer"
        self._tags: list[str] = []
        self._metadata: dict[str, Any] = {}

    def set_version(self, version: str) -> SkillComposer:
        self.version = version
        return self

    def set_execution_mode(self, mode: CompositionExecutionMode) -> SkillComposer:
        self._execution_mode = mode
        return self

    def set_error_policy(self, policy: CompositionErrorPolicy) -> SkillComposer:
        self._error_policy = policy
        return self

    def set_timeout(self, timeout_seconds: float) -> SkillComposer:
        self._timeout_seconds = timeout_seconds
        return self

    def set_risk_ceiling(self, ceiling: SecurityLevel) -> SkillComposer:
        self._risk_ceiling = ceiling
        return self

    def set_author(self, author: str) -> SkillComposer:
        self._author = author
        return self

    def add_tag(self, tag: str) -> SkillComposer:
        self._tags.append(tag)
        return self

    def set_inputs_schema(self, schema: dict[str, Any]) -> SkillComposer:
        self._inputs_schema = schema
        return self

    def set_outputs_schema(self, schema: dict[str, Any]) -> SkillComposer:
        self._outputs_schema = schema
        return self

    def set_output_mapping(self, mapping: dict[str, Any]) -> SkillComposer:
        self._output_mapping = mapping
        return self

    def add_step(
        self,
        step_id: str,
        skill_id: str,
        input_mapping: dict[str, Any] | None = None,
        condition: str | dict[str, Any] | None = None,
        timeout_seconds: float = 60.0,
        error_policy: CompositionErrorPolicy = CompositionErrorPolicy.FAIL_FAST,
        requires_confirmation: bool = False,
        depends_on: tuple[str, ...] | list[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> SkillComposer:
        """Agrega un paso individual a la composición."""
        step = SkillCompositionStep(
            step_id=step_id,
            skill_id=skill_id,
            input_mapping=input_mapping or {},
            condition=condition,
            timeout_seconds=timeout_seconds,
            error_policy=error_policy,
            requires_confirmation=requires_confirmation,
            depends_on=tuple(depends_on),
            metadata=metadata or {},
        )
        self._steps.append(step)
        return self

    def build(self) -> SkillComposition:
        """Construye y retorna la instancia inmutable de SkillComposition."""
        return SkillComposition(
            id=self.composition_id,
            name=self.name,
            version=self.version,
            description=self.description,
            steps=tuple(self._steps),
            execution_mode=self._execution_mode,
            error_policy=self._error_policy,
            inputs_schema=self._inputs_schema,
            outputs_schema=self._outputs_schema,
            output_mapping=self._output_mapping,
            timeout_seconds=self._timeout_seconds,
            max_steps=self._max_steps,
            risk_ceiling=self._risk_ceiling,
            author=self._author,
            tags=tuple(self._tags),
            metadata=self._metadata,
        )


class ComposedSkill(BaseSkill):
    """Adaptador que encapsula una SkillComposition como una BaseSkill de primera clase."""

    def __init__(
        self,
        composition: SkillComposition,
        executor: SkillCompositionExecutor | None = None,
    ) -> None:
        self.composition = composition
        self.executor = executor or SkillCompositionExecutor()

        # Calcular riesgo agregado para inicializar el BaseSkill
        validator = SkillCompositionValidator()
        _valid, _errs, agg_risk = validator.validate_composition(composition)

        risk_to_num = {
            SecurityLevel.SAFE: 1,
            SecurityLevel.LOW: 2,
            SecurityLevel.HIGH: 3,
            SecurityLevel.CRITICAL: 3,
        }
        numeric_risk = risk_to_num.get(agg_risk, 1)

        definition = SkillDefinition(
            skill_id=composition.id,
            name=composition.name,
            version=composition.version,
            description=composition.description,
            risk_level=agg_risk,
            parameters_schema=composition.inputs_schema,
            tags=composition.tags,
            author=composition.author,
        )

        super().__init__(
            nombre=composition.id,
            nivel_riesgo=numeric_risk,
            definition=definition,
        )

    def descripcion(self) -> str:
        return self.composition.description

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        """Ejecución sincrónica clásica."""
        ctx = SkillCompositionContext(
            composition_id=self.composition.id,
            inputs=parametros,
        )
        res: SkillCompositionResult = self.executor.execute_composition(self.composition, ctx)
        return {
            "exito": res.success,
            "mensaje": f"Composición ejecutada ({res.status}): {res.error or 'OK'}",
            "resultado": res.output,
            "pasos_ejecutados": res.steps_executed,
            "duracion_ms": res.duration_ms,
        }

    def execute(self, context: SkillContext) -> SkillResult:
        """Ejecución moderna mediante SkillContext."""
        comp_ctx = SkillCompositionContext(
            composition_id=self.composition.id,
            execution_id=context.execution_id,
            inputs=context.parameters,
            session_id=context.session_id,
            user=context.user,
            cancellation_token=context.cancellation_token,
            metadata=context.metadata,
        )
        res: SkillCompositionResult = self.executor.execute_composition(self.composition, comp_ctx)

        return SkillResult(
            skill_id=self.composition.id,
            success=res.success,
            status=SkillStatus.COMPLETED if res.success else SkillStatus.FAILED,
            output=res.output,
            error=res.error,
            steps=tuple(r.to_dict() for r in res.step_results.values()),
            warnings=res.warnings,
            execution_id=context.execution_id,
            duration_ms=res.duration_ms,
        )
