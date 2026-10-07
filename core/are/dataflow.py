"""Módulo de Flujo de Datos y Resolución de Referencias Tipadas entre Pasos en ARE.

Permite que un paso de ejecución consuma de forma estructurada las salidas generadas
por pasos previos mediante referencias sintácticas como '$step_id.output.propiedad'.
Valida tipos, existencia de dependencias y rechaza referencias faltantes o nulas.
"""

from __future__ import annotations

import re
from typing import Any

from core.are.exceptions import MissingOutputDependencyError
from core.logger import get_logger

logger = get_logger("jessyca.are.dataflow")

# Expresión regular para referencias a salidas de pasos previos:
# Ejemplos: $step_1.output.found_files, $step_1.output, $step_1.output.rows[0]
_REF_PATTERN = re.compile(
    r"^\$([a-zA-Z0-9_]+)\.output(?:\.([a-zA-Z0-9_]+(?:\[[0-9]+\])?))?$"
)


class DataFlowResolver:
    """Resuelve referencias tipadas de salidas entre pasos de un grafo de ejecución ARE."""

    @classmethod
    def extract_referenced_steps(cls, val: Any) -> set[str]:
        """Extrae recursivamente los identificadores de pasos referenciados en una estructura de parámetros."""
        steps: set[str] = set()
        if isinstance(val, str):
            match = _REF_PATTERN.match(val.strip())
            if match:
                steps.add(match.group(1))
            else:
                # Comprobar referencias inline dentro de cadenas
                inline_matches = re.findall(r"\$([a-zA-Z0-9_]+)\.output", val)
                for m in inline_matches:
                    steps.add(m)
        elif isinstance(val, dict):
            for v in val.values():
                steps.update(cls.extract_referenced_steps(v))
        elif isinstance(val, (list, tuple, set)):
            for item in val:
                steps.update(cls.extract_referenced_steps(item))
        return steps

    @classmethod
    def resolve_value(
        cls,
        val: Any,
        completed_step_outputs: dict[str, Any],
        current_step_id: str = "",
    ) -> Any:
        """Resuelve un valor individual, dict o lista que pueda contener referencias a pasos previos."""
        if isinstance(val, str):
            clean = val.strip()
            match = _REF_PATTERN.match(clean)
            if match:
                step_id = match.group(1)
                prop_path = match.group(2)
                return cls._resolve_path(step_id, prop_path, completed_step_outputs, current_step_id)

            # Reemplazo de referencias textuales inline (ej: "Directorio: $step_1.output.directory")
            if "$step_" in clean:
                def _replace_match(m: re.Match[str]) -> str:
                    s_id = m.group(1)
                    p_name = m.group(2)
                    res = cls._resolve_path(s_id, p_name, completed_step_outputs, current_step_id)
                    return str(res)

                return re.sub(
                    r"\$([a-zA-Z0-9_]+)\.output\.([a-zA-Z0-9_]+)",
                    _replace_match,
                    clean,
                )
            return val

        elif isinstance(val, dict):
            return {
                k: cls.resolve_value(v, completed_step_outputs, current_step_id)
                for k, v in val.items()
            }
        elif isinstance(val, list):
            return [
                cls.resolve_value(item, completed_step_outputs, current_step_id)
                for item in val
            ]
        return val

    @classmethod
    def _resolve_path(
        cls,
        step_id: str,
        prop_path: str | None,
        completed_step_outputs: dict[str, Any],
        current_step_id: str,
    ) -> Any:
        """Navega y extrae la propiedad solicitada de la salida del paso especificado."""
        if step_id not in completed_step_outputs:
            raise MissingOutputDependencyError(
                f"El paso '{current_step_id or 'actual'}' depende de la salida del paso '{step_id}', "
                f"pero dicho paso no ha concluido exitosamente o no produjo salidas.",
                code="MISSING_STEP_OUTPUT",
                details={"target_step": current_step_id, "required_step": step_id},
            )

        step_out = completed_step_outputs[step_id]
        if prop_path is None or not prop_path.strip():
            return step_out

        if not isinstance(step_out, dict):
            raise MissingOutputDependencyError(
                f"La salida del paso '{step_id}' no es un diccionario estructurado (tipo: {type(step_out).__name__}).",
                code="INVALID_STEP_OUTPUT_TYPE",
                details={"step_id": step_id, "property": prop_path},
            )

        # Manejar indexación opcional de lista: ej. found_files[0]
        array_match = re.match(r"^([a-zA-Z0-9_]+)\[([0-9]+)\]$", prop_path)
        if array_match:
            prop_name = array_match.group(1)
            idx = int(array_match.group(2))
            if prop_name not in step_out:
                raise MissingOutputDependencyError(
                    f"Propiedad requerida '{prop_name}' no encontrada en la salida del paso '{step_id}'.",
                    code="PROPERTY_NOT_FOUND",
                    details={"step_id": step_id, "property": prop_name},
                )
            arr = step_out[prop_name]
            if not isinstance(arr, (list, tuple)) or idx >= len(arr):
                raise MissingOutputDependencyError(
                    f"Índice [{idx}] fuera de rango en la propiedad '{prop_name}' del paso '{step_id}' (longitud: {len(arr) if isinstance(arr, list) else 0}).",
                    code="INDEX_OUT_OF_RANGE",
                    details={"step_id": step_id, "property": prop_name, "index": idx},
                )
            return arr[idx]

        if prop_path not in step_out:
            raise MissingOutputDependencyError(
                f"Propiedad requerida '{prop_path}' ausente en la salida del paso '{step_id}'. Claves disponibles: {list(step_out.keys())}.",
                code="PROPERTY_NOT_FOUND",
                details={"step_id": step_id, "property": prop_path, "available_keys": list(step_out.keys())},
            )

        val = step_out[prop_path]
        if val is None:
            raise MissingOutputDependencyError(
                f"La propiedad '{prop_path}' en la salida del paso '{step_id}' es nula (None).",
                code="NULL_OUTPUT_PROPERTY",
                details={"step_id": step_id, "property": prop_path},
            )
        return val

    @classmethod
    def resolve_parameters(
        cls,
        parameters: dict[str, Any],
        completed_step_outputs: dict[str, Any],
        step_id: str = "",
    ) -> dict[str, Any]:
        """Resuelve todos los parámetros dependientes de un paso contra el histórico de salidas."""
        return cls.resolve_value(parameters, completed_step_outputs, current_step_id=step_id)
