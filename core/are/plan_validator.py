"""Validador Estricto de Planes Fuera del LLM para ARE (Action Reasoning Engine).

Permite que un modelo de lenguaje o planificador proponga planes JSON bajo un contrato
estricto, y valida de forma determinista y perimétrica FUERA del LLM:
1. Grafo Acíclico Dirigido (DAG): sin ciclos, referencias válidas, orden topológico.
2. Catálogo y Capacidad: toda acción debe resolver a una herramienta existente; prohíbe 'action.execute'.
3. Parámetros: conformidad con el esquema de entrada y coherencia de flujo de datos.
4. Privacidad y Sandboxing: prohíbe path traversal y accesos fuera del sandbox permitido.
5. Presupuesto: límites de pasos y tiempo máximo.
6. Políticas de Seguridad: capacidades prohibidas y persistencia de denegaciones previas (invariante de replanificación).
7. Aclaración: detecta recursos o destinos esenciales ausentes antes de la ejecución física.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.are.action_catalog import ActionCatalog, get_default_action_catalog
from core.are.dataflow import DataFlowResolver
from core.are.exceptions import (
    PlanBudgetExceededError,
    PlanClarificationRequired,
    PlanValidationError,
    ReplanningDenialViolationError,
    SandboxViolationError,
    UnresolvableActionError,
)
from core.are.models import AREPlanProposal, AREStepProposal
from core.dag import topological_sort
from core.logger import get_logger

logger = get_logger("jessyca.are.plan_validator")

# Capacidades prohibidas perimétricamente
_FORBIDDEN_CAPABILITIES = frozenset({
    "external_ocr",
    "external_upload",
    "document_write",
    "arbitrary_shell",
    "admin",
    "outbound_network",
    "unregistered_system_admin",
})


class LLMStepProposal(BaseModel):
    """Contrato formal para un paso propuesto dentro de un plan JSON."""

    model_config = ConfigDict(extra="ignore")

    step_id: str
    action: str = ""
    action_type: str = ""
    title: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    is_critical: bool = True
    risk_level: str = "SAFE"

    def model_post_init(self, __context: Any) -> None:
        act = self.action or self.action_type
        if not self.action and act:
            object.__setattr__(self, "action", act)
        if not self.action_type and act:
            object.__setattr__(self, "action_type", act)
        if not self.title:
            object.__setattr__(self, "title", self.step_id)


class LLMPlanProposal(BaseModel):
    """Contrato formal para un plan JSON completo propuesto por un LLM."""

    model_config = ConfigDict(extra="ignore")

    goal: str
    steps: list[LLMStepProposal] = Field(default_factory=list)
    budget_max_steps: int = 10
    budget_timeout_seconds: float = 120.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanValidator:
    """Validador perimétrico de planes generados por LLM o descomposiciones algorítmicas."""

    def __init__(
        self,
        catalog: ActionCatalog | None = None,
        sandbox_dir: Path | str | None = None,
        max_budget_steps: int = 10,
        max_budget_timeout: float = 180.0,
    ) -> None:
        self.catalog = catalog or get_default_action_catalog()
        self.sandbox_dir = Path(sandbox_dir).resolve() if sandbox_dir else None
        self.max_budget_steps = max_budget_steps
        self.max_budget_timeout = max_budget_timeout

    def validate_plan(
        self,
        plan_input: dict[str, Any] | str | LLMPlanProposal,
        previously_denied_actions: set[str] | None = None,
        task_id: str = "task_plan",
        plan_id: str = "plan_validated",
    ) -> AREPlanProposal:
        """Ejecuta las 7 validaciones perimétricas completas fuera del LLM.

        Retorna un AREPlanProposal verificado con orden topológico y hash de integridad.
        """
        # Parsear propuesta de plan
        if isinstance(plan_input, str):
            try:
                raw_dict = json.loads(plan_input)
            except Exception as e:
                raise PlanValidationError(
                    f"El formato del plan propuesto no es un JSON válido: {e}",
                    code="INVALID_JSON",
                )
            proposal = LLMPlanProposal.model_validate(raw_dict)
        elif isinstance(plan_input, dict):
            proposal = LLMPlanProposal.model_validate(plan_input)
        elif isinstance(plan_input, LLMPlanProposal):
            proposal = plan_input
        else:
            raise PlanValidationError(
                f"Tipo de plan no soportado: {type(plan_input).__name__}",
                code="UNSUPPORTED_PLAN_TYPE",
            )

        steps = proposal.steps
        goal = proposal.goal.strip()
        denied_actions = set(previously_denied_actions or set())

        # ── 1. Validación de Presupuesto (Budget) ──
        if len(steps) > self.max_budget_steps:
            raise PlanBudgetExceededError(
                f"El plan propuesto tiene {len(steps)} pasos, superando el límite permitido de {self.max_budget_steps}.",
                code="BUDGET_STEPS_EXCEEDED",
                details={"steps_count": len(steps), "max_steps": self.max_budget_steps},
            )

        if proposal.budget_timeout_seconds > self.max_budget_timeout:
            raise PlanBudgetExceededError(
                f"El tiempo presupuestado ({proposal.budget_timeout_seconds}s) excede el máximo permitido ({self.max_budget_timeout}s).",
                code="BUDGET_TIMEOUT_EXCEEDED",
                details={"requested": proposal.budget_timeout_seconds, "max": self.max_budget_timeout},
            )

        if not steps:
            raise PlanValidationError("El plan no contiene pasos ejecutables.", code="EMPTY_PLAN")

        # ── 2. Validación de Grafo Acíclico Dirigido (DAG) ──
        step_ids = [s.step_id for s in steps]
        if len(step_ids) != len(set(step_ids)):
            raise PlanValidationError(
                f"Identificadores de pasos duplicados detectados en el plan: {step_ids}",
                code="DUPLICATE_STEP_IDS",
            )

        step_id_set = set(step_ids)
        for s in steps:
            for dep in s.depends_on:
                if dep not in step_id_set:
                    raise PlanValidationError(
                        f"El paso '{s.step_id}' depende de un paso inexistente '{dep}'.",
                        code="NON_EXISTENT_DEPENDENCY",
                        details={"step_id": s.step_id, "missing_dependency": dep},
                    )

        # Ordenamiento topológico determinista (detección de ciclos)
        try:
            ordered_steps = topological_sort(
                steps,
                get_id=lambda s: s.step_id,
                get_dependencies=lambda s: s.depends_on,
                tie_breaker=lambda s: s.step_id,
            )
            execution_order = [s.step_id for s in ordered_steps]
        except ValueError as cycle_err:
            raise PlanValidationError(
                f"Dependencia circular detectada en el plan propuesto: {cycle_err}",
                code="CIRCULAR_DEPENDENCY",
            )

        # ── 3. Validación de Capacidad, Políticas y Denegaciones Previas ──
        are_steps: list[AREStepProposal] = []
        dependencies_map: dict[str, list[str]] = {}

        for step in ordered_steps:
            action_id = step.action or step.action_type
            if not action_id:
                raise PlanValidationError(
                    f"El paso '{step.step_id}' no especifica ninguna acción.",
                    code="EMPTY_ACTION",
                )

            # Invariante de Replanificación: no se puede borrar una denegación previa
            if action_id in denied_actions:
                raise ReplanningDenialViolationError(
                    f"Violación de política de replanificación: la acción '{action_id}' fue denegada previamente por seguridad y no puede ser reintroducida.",
                    code="DENIED_ACTION_REINTRODUCTION",
                    details={"action_id": action_id, "step_id": step.step_id},
                )

            # Capacidad prohibida perimétrica
            if any(fc in action_id for fc in _FORBIDDEN_CAPABILITIES):
                raise PlanValidationError(
                    f"La acción '{action_id}' en el paso '{step.step_id}' invoca una capacidad estrictamente prohibida.",
                    code="FORBIDDEN_CAPABILITY",
                    details={"action_id": action_id, "forbidden": list(_FORBIDDEN_CAPABILITIES)},
                )

            # Resolución en catálogo real (rechaza placeholders genéricos como action.execute)
            try:
                resolved_action = self.catalog.resolve_action(action_id)
            except UnresolvableActionError as e:
                raise UnresolvableActionError(
                    f"Fallo en paso '{step.step_id}': {e.message}",
                    code=e.code,
                    details=e.details,
                )

            # ── 4. Validación de Parámetros y Flujo de Datos ──
            params = step.parameters or {}

            # Extraer referencias a pasos previos y validar que estén declaradas en depends_on
            referenced_steps = DataFlowResolver.extract_referenced_steps(params)
            for ref_s in referenced_steps:
                if ref_s not in step.depends_on:
                    raise PlanValidationError(
                        f"El paso '{step.step_id}' consume salidas de '{ref_s}', "
                        f"pero no lo declara explícitamente en 'depends_on'.",
                        code="UNDECLARED_DATAFLOW_DEPENDENCY",
                        details={"step_id": step.step_id, "undeclared_dep": ref_s},
                    )

            # Validar parámetros requeridos contra input_schema de la acción concreta
            req_props = resolved_action.input_schema.get("required", [])
            for prop in req_props:
                if prop not in params:
                    # Comprobar si el objetivo general carece de este destino o recurso
                    raise PlanValidationError(
                        f"El paso '{step.step_id}' ({action_id}) carece del parámetro obligatorio '{prop}'.",
                        code="MISSING_REQUIRED_PARAMETER",
                        details={"step_id": step.step_id, "action": action_id, "missing_parameter": prop},
                    )

            # ── 5. Validación de Privacidad y Sandboxing ──
            if self.sandbox_dir:
                self._validate_sandboxing_parameters(step.step_id, params)

            # ── 6. Detección de Recursos Esenciales Faltantes (Solicitud de Aclaración) ──
            self._check_essential_resources(step.step_id, action_id, params, goal)

            # Construir propuesta de paso tipada
            are_steps.append(
                AREStepProposal(
                    step_id=step.step_id,
                    title=step.title or f"{action_id} ({step.step_id})",
                    action_type=action_id,
                    action=action_id,
                    parameters=params,
                    depends_on=list(step.depends_on),
                    required_capabilities=[action_id],
                    risk_level=str(resolved_action.risk_level),
                    is_critical=step.is_critical,
                    status="PROPOSED",
                )
            )
            dependencies_map[step.step_id] = list(step.depends_on)

        # ── 7. Computar Hash de Integridad Criptográfico SHA-256 ──
        integrity_hash = AREPlanProposal.compute_integrity_hash(
            task_id=task_id,
            plan_id=plan_id,
            goal=goal,
            execution_order=execution_order,
            steps=are_steps,
        )

        return AREPlanProposal(
            task_id=task_id,
            plan_id=plan_id,
            goal=goal,
            steps=are_steps,
            execution_order=execution_order,
            dependencies=dependencies_map,
            required_capabilities=[s.action_type for s in are_steps],
            risk_context={"total_steps": len(are_steps), "sandbox": str(self.sandbox_dir) if self.sandbox_dir else "GLOBAL"},
            confidence=0.98,
            provenance="ARE.PlanValidator",
            integrity_hash=integrity_hash,
            is_evaluated=True,
            is_valid=True,
            evaluation_errors=[],
        )

    def _validate_sandboxing_parameters(self, step_id: str, params: dict[str, Any]) -> None:
        """Verifica que ningún parámetro de ruta escape de los límites del sandbox permitido."""
        if not self.sandbox_dir:
            return

        path_keys = (
            "file_path", "path", "source_path", "destination_path",
            "target_path", "output_path", "table_path", "directory",
        )

        for k, v in params.items():
            if k in path_keys and isinstance(v, str):
                # Omitir referencias dinámicas que se resuelven en tiempo de ejecución ($step_...)
                if v.startswith("$"):
                    continue

                if ".." in v or v.startswith("/") or (len(v) > 2 and v[1] == ":"):
                    # Verificar resolución absoluta
                    resolved = Path(v).resolve()
                    try:
                        resolved.relative_to(self.sandbox_dir)
                    except ValueError:
                        raise SandboxViolationError(
                            f"Violación de sandbox en el paso '{step_id}': la ruta '{v}' resuelve fuera de '{self.sandbox_dir}'.",
                            code="SANDBOX_VIOLATION",
                            details={"step_id": step_id, "path": v, "sandbox": str(self.sandbox_dir)},
                        )

    def _check_essential_resources(self, step_id: str, action_id: str, params: dict[str, Any], goal: str) -> None:
        """Detecta si un paso carece de destino o recurso esencial que requiera aclaración del usuario."""
        if action_id in ("files.copy", "files.move"):
            dst = params.get("destination_path") or params.get("dst")
            if not dst or (isinstance(dst, str) and not dst.strip()):
                raise PlanClarificationRequired(
                    f"Falta el directorio o ruta de destino para transferir los archivos en el paso '{step_id}'.",
                    missing_resource="destination_path",
                    prompt="¿A qué carpeta o destino deseas transferir los archivos?",
                )

        if action_id == "files.search":
            query = params.get("query") or params.get("pattern")
            directory = params.get("directory") or params.get("path")
            if not query and not directory and not goal:
                raise PlanClarificationRequired(
                    f"No se especificó qué archivo o directorio buscar en el paso '{step_id}'.",
                    missing_resource="search_target",
                    prompt="¿Qué archivo o patrón específico deseas que busque?",
                )

        if action_id in ("documents.create_word_report", "word.create_report"):
            fp = params.get("file_path") or params.get("path") or params.get("output_path")
            if not fp or (isinstance(fp, str) and not fp.strip()):
                raise PlanClarificationRequired(
                    f"Falta la ruta o nombre de destino para el informe Word en el paso '{step_id}'.",
                    missing_resource="file_path",
                    prompt="¿En qué ruta o nombre de archivo deseas guardar el informe Word?",
                )

        if action_id in ("presentation.create_presentation", "powerpoint.create_presentation"):
            fp = params.get("file_path") or params.get("path") or params.get("output_path")
            if not fp or (isinstance(fp, str) and not fp.strip()):
                raise PlanClarificationRequired(
                    f"Falta la ruta o nombre de destino para la presentación PowerPoint en el paso '{step_id}'.",
                    missing_resource="file_path",
                    prompt="¿En qué ruta o nombre de archivo deseas guardar la presentación PowerPoint?",
                )

        if action_id in ("spreadsheet.read_sheet", "excel.read_data"):
            fp = params.get("file_path") or params.get("path")
            if not fp or (isinstance(fp, str) and not fp.strip()):
                raise PlanClarificationRequired(
                    f"Falta la ruta del libro u hoja de cálculo en el paso '{step_id}'.",
                    missing_resource="file_path",
                    prompt="¿Qué archivo de hoja de cálculo deseas que analice?",
                )

        if action_id == "files.preview_organize":
            dir_param = params.get("directory") or params.get("path")
            files_param = params.get("files_list") or params.get("found_files")
            if not dir_param and not files_param:
                raise PlanClarificationRequired(
                    f"Falta la carpeta o conjunto de archivos a organizar en el paso '{step_id}'.",
                    missing_resource="directory",
                    prompt="¿Qué carpeta deseas organizar?",
                )
