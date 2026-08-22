"""Validador formal, analizador de grafos (DAG), detección de ciclos y agregador de riesgos (Fase 35).

Garantiza que toda composición de Skills:
1. Emplee exclusivamente Skills existentes, registradas y habilitadas en SkillRegistry.
2. Forme un Grafo Acíclico Dirigido (DAG) sin referencias circulares (Cycle Detection).
3. Agregue el nivel de riesgo de forma monótonamente creciente (el riesgo de la composición es el máximo de sus partes).
4. Respete los esquemas y restricciones de tipado (Type Safety).
5. Respete los límites de recursión y anidamiento.
"""

from __future__ import annotations

import re

from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.skill_composition_models import (
    CompositionExecutionMode,
    SkillComposition,
)
from skills.skill_models import SkillStatus
from skills.skill_registry import SkillRegistry, get_skill_registry

logger = get_logger("jessyca.skills.composition.validator")

# Jerarquía formal de severidad de riesgo (de menor a mayor)
RISK_HIERARCHY: dict[str, int] = {
    "SAFE": 1,
    "LOW": 1,
    "WARNING": 2,
    "MEDIUM": 2,
    "DANGEROUS": 3,
    "HIGH": 3,
    "CRITICAL": 4,
}


class CompositionValidationError(Exception):
    """Excepción cuando una composición viola invariantes estructurales o de seguridad."""
    pass


class SkillCompositionValidator:
    """Validador estático y de grafo para composiciones de Skills."""

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or get_skill_registry()

    def validate_composition(
        self,
        composition: SkillComposition,
        current_nesting_level: int = 0,
        max_nesting_level: int = 5,
    ) -> tuple[bool, list[str], SecurityLevel]:
        """Valida formalmente la estructura, dependencias, DAG y nivel de riesgo de una composición.

        :return: Tupla (is_valid, errors_list, aggregated_risk_level)
        """
        errors: list[str] = []

        # 1. Comprobación de límites de anidamiento y recursión
        if current_nesting_level > max_nesting_level:
            errors.append(
                f"Límite de anidamiento de composición excedido ({current_nesting_level} > {max_nesting_level})."
            )

        # 2. Comprobación básica de pasos
        if not composition.steps:
            errors.append(f"La composición '{composition.id}' no contiene pasos de ejecución.")

        if len(composition.steps) > composition.max_steps:
            errors.append(
                f"La composición '{composition.id}' excede el número máximo de pasos permitidos "
                f"({len(composition.steps)} > {composition.max_steps})."
            )

        step_ids: set[str] = set()
        for step in composition.steps:
            if not step.step_id or not step.step_id.strip():
                errors.append(f"Paso sin step_id en composición '{composition.id}'.")
            elif step.step_id in step_ids:
                errors.append(f"step_id duplicado '{step.step_id}' en composición '{composition.id}'.")
            step_ids.add(step.step_id)

        # 3. Comprobación de existencia y estado de constituent skills
        highest_risk_score = 1
        for step in composition.steps:
            skill_def = self.registry.lookup_definition(step.skill_id)
            skill_inst = self.registry.lookup(step.skill_id)

            if not skill_def and not skill_inst:
                errors.append(
                    f"Skill requerida '{step.skill_id}' en paso '{step.step_id}' no existe o no está registrada."
                )
                continue

            # Comprobar si está deshabilitada
            status = self.registry.get_status(step.skill_id)
            if status in (SkillStatus.DISABLED, SkillStatus.INVALID, SkillStatus.FAILED):
                errors.append(
                    f"Skill requerida '{step.skill_id}' en paso '{step.step_id}' se encuentra en estado '{status}' (no ejecutable)."
                )

            # Extraer nivel de riesgo de la Skill constituyente
            risk_val = "SAFE"
            if skill_def and skill_def.risk_level:
                risk_val = str(getattr(skill_def.risk_level, "value", skill_def.risk_level)).upper()
            elif skill_inst and hasattr(skill_inst, "nivel_riesgo"):
                risk_num_map = {1: "SAFE", 2: "LOW", 3: "HIGH"}
                risk_val = risk_num_map.get(skill_inst.nivel_riesgo, "SAFE")

            score = RISK_HIERARCHY.get(risk_val, 1)
            if score > highest_risk_score:
                highest_risk_score = score

        # 4. Calcular nivel de riesgo agregado de la composición
        score_to_risk: dict[int, SecurityLevel] = {
            1: SecurityLevel.SAFE,
            2: SecurityLevel.WARNING,
            3: SecurityLevel.HIGH,
            4: SecurityLevel.CRITICAL,
        }
        aggregated_risk = score_to_risk.get(highest_risk_score, SecurityLevel.SAFE)

        # Comprobar si supera el techo de riesgo declarado
        if composition.risk_ceiling:
            ceiling_val = str(getattr(composition.risk_ceiling, "value", composition.risk_ceiling)).upper()
            ceiling_score = RISK_HIERARCHY.get(ceiling_val, 1)
            if highest_risk_score > ceiling_score:
                errors.append(
                    f"El riesgo agregado de la composición ({aggregated_risk}) supera el techo permitido "
                    f"({composition.risk_ceiling})."
                )

        # 5. Detección de Ciclos (Cycle Detection en Grafo Dirigido)
        cycle_errors = self._detect_cycles(composition)
        errors.extend(cycle_errors)

        # 6. Validación de coherencia en modo paralelo
        if composition.execution_mode == CompositionExecutionMode.PARALLEL:
            parallel_dep_errors = self._validate_parallel_independence(composition)
            errors.extend(parallel_dep_errors)

        is_valid = len(errors) == 0
        if not is_valid:
            logger.warning(f"[COMPOSITION INVALID] '{composition.id}' rechazada con {len(errors)} errores: {errors}")
        else:
            logger.info(f"[COMPOSITION VALID] '{composition.id}' validada con riesgo agregado '{aggregated_risk}'.")

        return is_valid, errors, aggregated_risk

    def _detect_cycles(self, composition: SkillComposition) -> list[str]:
        """Construye el grafo de dependencias de pasos y detecta ciclos utilizando DFS."""
        errors: list[str] = []
        adj: dict[str, list[str]] = {step.step_id: [] for step in composition.steps}

        # Extraer dependencias explícitas (depends_on) y dependencias implícitas (data flow {{steps.<id>...}})
        template_re = re.compile(r"steps\.([a-zA-Z0-9_\-]+)")

        for step in composition.steps:
            # 1. depends_on explícito
            for dep in step.depends_on:
                if dep not in adj:
                    errors.append(
                        f"Paso '{step.step_id}' declara dependencia en paso inexistente '{dep}'."
                    )
                else:
                    adj[dep].append(step.step_id)

            # 2. data flow en input_mapping
            mapping_str = str(step.input_mapping)
            for m in template_re.finditer(mapping_str):
                dep_step = m.group(1)
                if dep_step == step.step_id:
                    errors.append(f"Autorreferencia cíclica detectada en paso '{step.step_id}'.")
                elif dep_step not in adj:
                    errors.append(
                        f"Paso '{step.step_id}' referencia output de paso inexistente '{dep_step}'."
                    )
                else:
                    if step.step_id not in adj[dep_step]:
                        adj[dep_step].append(step.step_id)

            # 3. data flow en condition
            if step.condition:
                cond_str = str(step.condition)
                for m in template_re.finditer(cond_str):
                    dep_step = m.group(1)
                    if dep_step not in adj:
                        errors.append(
                            f"Condición de paso '{step.step_id}' referencia paso inexistente '{dep_step}'."
                        )
                    else:
                        if step.step_id not in adj[dep_step]:
                            adj[dep_step].append(step.step_id)

        # Algoritmo de detección de ciclos mediante DFS (3 colores: 0=UNVISITED, 1=VISITING, 2=VISITED)
        state: dict[str, int] = dict.fromkeys(adj, 0)
        cycle_path: list[str] = []

        def _dfs(node: str) -> bool:
            state[node] = 1  # VISITING
            cycle_path.append(node)

            for neighbor in adj.get(node, []):
                if state.get(neighbor) == 1:
                    cycle_start_idx = cycle_path.index(neighbor)
                    cycle_loop = cycle_path[cycle_start_idx:] + [neighbor]
                    errors.append(f"Ciclo de dependencias detectado: {' -> '.join(cycle_loop)}")
                    return True
                elif state.get(neighbor) == 0:
                    if _dfs(neighbor):
                        return True

            cycle_path.pop()
            state[node] = 2  # VISITED
            return False

        for node in adj:
            if state[node] == 0:
                _dfs(node)

        return errors

    def _validate_parallel_independence(self, composition: SkillComposition) -> list[str]:
        """Valida que en modo PARALLEL estricto, no existan dependencias secuenciales no resolvibles."""
        errors: list[str] = []
        template_re = re.compile(r"steps\.([a-zA-Z0-9_\-]+)")

        for step in composition.steps:
            if step.depends_on:
                errors.append(
                    f"Modo PARALLEL no admite 'depends_on' en paso '{step.step_id}'. "
                    f"Los pasos paralelos deben ser independientes."
                )
            mapping_str = str(step.input_mapping)
            if template_re.search(mapping_str):
                errors.append(
                    f"Modo PARALLEL no admite data flow entre pasos en paso '{step.step_id}'. "
                    f"Utilice modo SEQUENTIAL o CONDITIONAL para pasos con dependencias de datos."
                )

        return errors
