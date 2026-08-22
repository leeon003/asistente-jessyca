"""Motor de flujo de datos y evaluador de condiciones seguro para Skill Composition (Fase 35).

Proporciona resolución determinista de parámetros y condiciones entre pasos de composición
sin recurrir a eval() ni exec(), preservando la integridad del entorno y evitando inyecciones de código.
"""

from __future__ import annotations

import re
from typing import Any

from core.logger import get_logger
from skills.skill_composition_models import SkillCompositionStepResult

logger = get_logger("jessyca.skills.composition.dataflow")

TEMPLATE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_\.\-\[\]]+)\s*\}\}")


class DataFlowResolutionError(Exception):
    """Excepción al fallar la resolución de parámetros en el flujo de datos."""
    pass


class SkillDataFlowResolver:
    """Resuelve referencias a inputs de composición y outputs de pasos previos."""

    @classmethod
    def resolve_mapping(
        cls,
        mapping: dict[str, Any],
        composition_inputs: dict[str, Any],
        step_results: dict[str, SkillCompositionStepResult],
    ) -> dict[str, Any]:
        """Resuelve recursivamente un diccionario de mapeo de parámetros."""
        resolved: dict[str, Any] = {}
        for key, val in mapping.items():
            resolved[key] = cls.resolve_value(val, composition_inputs, step_results)
        return resolved

    @classmethod
    def resolve_value(
        cls,
        val: Any,
        composition_inputs: dict[str, Any],
        step_results: dict[str, SkillCompositionStepResult],
    ) -> Any:
        """Resuelve un valor individual (escalar, template, lista o diccionario)."""
        if isinstance(val, str):
            val_str = val.strip()
            # 1. Caso de sustitución exacta: "{{path}}"
            exact_match = re.fullmatch(r"\{\{\s*([a-zA-Z0-9_\.\-\[\]]+)\s*\}\}", val_str)
            if exact_match:
                path = exact_match.group(1)
                return cls._extract_path_value(path, composition_inputs, step_results)

            # 2. Caso de interpolación dentro de string: "Buscar {{inputs.query}} en Google"
            if "{{" in val and "}}" in val:
                def _replace_match(match: re.Match[str]) -> str:
                    p = match.group(1)
                    res = cls._extract_path_value(p, composition_inputs, step_results)
                    return str(res) if res is not None else ""

                return TEMPLATE_PATTERN.sub(_replace_match, val)

            return val

        elif isinstance(val, dict):
            return {k: cls.resolve_value(v, composition_inputs, step_results) for k, v in val.items()}

        elif isinstance(val, list):
            return [cls.resolve_value(item, composition_inputs, step_results) for item in val]

        elif isinstance(val, tuple):
            return tuple(cls.resolve_value(item, composition_inputs, step_results) for item in val)

        return val

    @classmethod
    def _extract_path_value(
        cls,
        path: str,
        composition_inputs: dict[str, Any],
        step_results: dict[str, SkillCompositionStepResult],
    ) -> Any:
        """Extrae de forma segura el valor apuntado por una ruta de propiedad.

        Rutas soportadas:
        - `inputs.<key>`
        - `steps.<step_id>.output`
        - `steps.<step_id>.output.<key>`
        - `steps.<step_id>.output.<key>[0].<subkey>`
        - `steps.<step_id>.success`
        - `steps.<step_id>.status`
        """
        parts = path.split(".")
        if not parts:
            raise DataFlowResolutionError("Ruta de flujo de datos vacía.")

        root = parts[0]

        if root == "inputs":
            current: Any = composition_inputs
            for part in parts[1:]:
                current = cls._traverse_subpart(current, part)
            return current

        elif root == "steps":
            if len(parts) < 2:
                raise DataFlowResolutionError(f"Ruta de paso incompleta en '{path}'.")
            step_id = parts[1]
            if step_id not in step_results:
                raise DataFlowResolutionError(f"El paso '{step_id}' no ha sido ejecutado o no existe.")

            step_res = step_results[step_id]
            if len(parts) == 2:
                return step_res.output

            target_attr = parts[2]
            if target_attr == "output":
                current = step_res.output
                for part in parts[3:]:
                    current = cls._traverse_subpart(current, part)
                return current
            elif target_attr == "success":
                return step_res.success
            elif target_attr == "status":
                return str(step_res.status)
            elif target_attr == "error":
                return step_res.error
            else:
                current = step_res.output
                for part in parts[2:]:
                    current = cls._traverse_subpart(current, part)
                return current

        else:
            # Si no empieza por inputs ni steps, intentar buscar en inputs directamente
            current = composition_inputs
            for part in parts:
                current = cls._traverse_subpart(current, part)
            return current

    @classmethod
    def _traverse_subpart(cls, current: Any, part: str) -> Any:
        """Navega por un nivel de atributo, clave de diccionario o índice de lista."""
        if current is None:
            return None

        # Comprobar si incluye indexación por lista: e.g. "items[0]"
        list_match = re.match(r"^([a-zA-Z0-9_\-]+)\[(\d+)\]$", part)
        if list_match:
            name, idx_str = list_match.groups()
            idx = int(idx_str)
            sub_obj = cls._get_dict_or_attr(current, name)
            if isinstance(sub_obj, (list, tuple)) and 0 <= idx < len(sub_obj):
                return sub_obj[idx]
            return None

        return cls._get_dict_or_attr(current, part)

    @classmethod
    def _get_dict_or_attr(cls, obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        elif hasattr(obj, key):
            return getattr(obj, key)
        return None


class SkillConditionEvaluator:
    """Evalúa condiciones lógicas para pasos condicionales de forma determinista y segura."""

    @classmethod
    def evaluate(
        cls,
        condition: str | dict[str, Any] | None,
        composition_inputs: dict[str, Any],
        step_results: dict[str, SkillCompositionStepResult],
    ) -> bool:
        """Evalúa si la condición de ejecución se cumple (True) o no (False).

        Si condition es None, siempre es True.
        """
        if condition is None:
            return True

        if isinstance(condition, bool):
            return condition

        if isinstance(condition, dict):
            return cls._evaluate_dict_condition(condition, composition_inputs, step_results)

        if isinstance(condition, str):
            return cls._evaluate_str_condition(condition, composition_inputs, step_results)

        return bool(condition)

    @classmethod
    def _evaluate_dict_condition(
        cls,
        cond: dict[str, Any],
        composition_inputs: dict[str, Any],
        step_results: dict[str, SkillCompositionStepResult],
    ) -> bool:
        field_path = cond.get("field", "")
        op = cond.get("operator", "==").strip()
        expected = cond.get("value")

        actual = SkillDataFlowResolver.resolve_value(field_path, composition_inputs, step_results)

        if op in ("==", "eq"):
            return bool(actual == expected)
        elif op in ("!=", "neq"):
            return bool(actual != expected)
        elif op in (">", "gt"):
            return bool(actual is not None and expected is not None and actual > expected)
        elif op in ("<", "lt"):
            return bool(actual is not None and expected is not None and actual < expected)
        elif op in (">=", "gte"):
            return bool(actual is not None and expected is not None and actual >= expected)
        elif op in ("<=", "lte"):
            return bool(actual is not None and expected is not None and actual <= expected)
        elif op in ("in", "contains"):
            return bool(expected in actual if actual is not None else False)
        elif op in ("not in", "not_contains"):
            return bool(expected not in actual if actual is not None else True)
        elif op in ("is_truthy", "truthy"):
            return bool(actual)
        elif op in ("is_falsy", "falsy"):
            return not bool(actual)

        return False

    @classmethod
    def _resolve_operand(
        cls,
        raw: str,
        composition_inputs: dict[str, Any],
        step_results: dict[str, SkillCompositionStepResult],
    ) -> Any:
        raw = raw.strip()
        if raw.lower() == "true":
            return True
        if raw.lower() == "false":
            return False
        if raw.lower() in ("none", "null"):
            return None
        if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
            return int(raw)
        try:
            return float(raw)
        except ValueError:
            pass
        if (raw.startswith("'") and raw.endswith("'")) or (raw.startswith('"') and raw.endswith('"')):
            return raw[1:-1]
        if raw.startswith("steps.") or raw.startswith("inputs."):
            try:
                return SkillDataFlowResolver._extract_path_value(raw, composition_inputs, step_results)
            except Exception:
                return None
        if "{{" in raw and "}}" in raw:
            return SkillDataFlowResolver.resolve_value(raw, composition_inputs, step_results)
        return SkillDataFlowResolver.resolve_value(raw, composition_inputs, step_results)

    @classmethod
    def _evaluate_str_condition(
        cls,
        expr: str,
        composition_inputs: dict[str, Any],
        step_results: dict[str, SkillCompositionStepResult],
    ) -> bool:
        expr = expr.strip()
        if not expr:
            return True

        if expr.lower() == "true":
            return True
        if expr.lower() == "false":
            return False

        # Comprobar operadores binarios estándar
        for op in ("==", "!=", ">=", "<=", ">", "<", " in ", " not in "):
            if op in expr:
                parts = expr.split(op, 1)
                left_raw = parts[0].strip()
                right_raw = parts[1].strip()

                left_val = cls._resolve_operand(left_raw, composition_inputs, step_results)
                right_val = cls._resolve_operand(right_raw, composition_inputs, step_results)

                op_clean = op.strip()
                if op_clean == "==":
                    return bool(left_val == right_val)
                elif op_clean == "!=":
                    return bool(left_val != right_val)
                elif op_clean == ">=":
                    return bool(left_val is not None and right_val is not None and left_val >= right_val)
                elif op_clean == "<=":
                    return bool(left_val is not None and right_val is not None and left_val <= right_val)
                elif op_clean == ">":
                    return bool(left_val is not None and right_val is not None and left_val > right_val)
                elif op_clean == "<":
                    return bool(left_val is not None and right_val is not None and left_val < right_val)
                elif op_clean == "in":
                    return bool(left_val in right_val if right_val is not None else False)
                elif op_clean == "not in":
                    return bool(left_val not in right_val if right_val is not None else True)

        # Expresión unaria de campo (truthy)
        val = cls._resolve_operand(expr, composition_inputs, step_results)
        return bool(val)
