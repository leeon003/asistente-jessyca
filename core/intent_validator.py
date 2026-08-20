"""Validador determinista de intenciones, estructura y suficiencia de parámetros (Fase 2).

GARANTÍA DE AUTORIDAD:
El LLM (Gemma) interpreta y propone; IntentValidator valida determinísticamente
contra el contrato real de las Skills registradas antes de permitir la ejecución.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.intent_models import IntentStatus, ParsedIntent, ValidationResult

# Palabras/frases ambiguas que indican una referencia no resuelta
PALABRAS_AMBIGUAS: set[str] = {
    "eso",
    "esto",
    "aquello",
    "la ventana",
    "la pestaña",
    "el programa",
    "la app",
    "la aplicacion",
    "la aplicación",
    "lo de antes",
}

# Requisitos deterministas de parámetros por skill
PARAMETROS_REQUERIDOS_SKILLS: dict[str, list[tuple[str, ...]]] = {
    "abrir_aplicacion": [("nombre_app", "app", "nombre")],
    "cerrar_aplicacion": [("nombre_proceso", "nombre_app", "app", "nombre")],
    "buscar_archivo": [("nombre_archivo", "extension", "nombre", "patron", "ruta")],
}

PREGUNTAS_ACLARATORIAS_DEFAULT: dict[str, dict[str, str]] = {
    "abrir_aplicacion": {
        "nombre_app": "¿Qué aplicación quieres que abra?",
        "ambiguo": "¿Qué aplicación o ventana deseas abrir?",
    },
    "cerrar_aplicacion": {
        "nombre_app": "¿Qué aplicación o proceso deseas cerrar?",
        "ambiguo": "¿Qué ventana o aplicación quieres cerrar?",
    },
    "buscar_archivo": {
        "nombre_archivo": "¿Qué nombre de archivo o extensión estás buscando?",
        "ambiguo": "¿Qué tipo de archivo o carpeta deseas buscar?",
    },
}


class IntentValidator:
    """Validador determinista de intenciones y completitud de parámetros."""

    def __init__(self, skills_disponibles: Mapping[str, Any] | None = None) -> None:
        self.skills_disponibles = skills_disponibles or {}

    def validate(
        self,
        parsed_intent: ParsedIntent,
        skills: Mapping[str, Any] | None = None,
    ) -> ValidationResult:
        """Valida determinísticamente el resultado emitido por el Brain.

        Args:
            parsed_intent: Objeto ParsedIntent producido por el Brain.
            skills: Catálogo opcional de skills activas en tiempo de ejecución.

        Returns:
            ValidationResult con el veredicto formal y estado verificado.
        """
        catalogo = skills if skills is not None else self.skills_disponibles

        # 1. Validación de estado INVALID o error crítico
        if parsed_intent.estado == IntentStatus.INVALID or parsed_intent.error:
            return ValidationResult(
                is_valid=False,
                status=IntentStatus.INVALID,
                reason=parsed_intent.error or "Entrada no válida o estructura JSON mal formada.",
                clarification_prompt=parsed_intent.respuesta_hablada or "No pude comprender la orden. Por favor, repítela.",
            )

        # 2. Validación de comandos conversacionales puros (sin skill solicitada)
        if not parsed_intent.skill:
            if parsed_intent.estado == IntentStatus.UNSUPPORTED:
                return ValidationResult(
                    is_valid=False,
                    status=IntentStatus.UNSUPPORTED,
                    reason="Habilidad solicitada no soportada o fuera de alcance.",
                    clarification_prompt=parsed_intent.respuesta_hablada or "Todavía no tengo esa habilidad disponible.",
                )
            return ValidationResult(
                is_valid=True,
                status=IntentStatus.CLEAR,
                reason="Respuesta conversacional válida sin invocación de skill.",
                clarification_prompt=parsed_intent.respuesta_hablada,
            )

        nombre_skill = str(parsed_intent.skill).strip()

        # 3. Validación de existencia de la Skill en el catálogo
        if catalogo and nombre_skill not in catalogo:
            return ValidationResult(
                is_valid=False,
                status=IntentStatus.UNSUPPORTED,
                skill_name=nombre_skill,
                reason=f"La skill '{nombre_skill}' no existe en el catálogo registrado.",
                clarification_prompt=parsed_intent.respuesta_hablada or f"No tengo disponible la habilidad '{nombre_skill}'.",
            )

        parametros_raw = dict(parsed_intent.parametros or {})
        candidatos = list(parsed_intent.candidatos or [])

        # 4. Comprobación determinista de referencias ambiguas en los parámetros
        for k, v in parametros_raw.items():
            if isinstance(v, str):
                v_clean = v.strip().lower()
                if v_clean in PALABRAS_AMBIGUAS:
                    pregunta = (
                        parsed_intent.pregunta_aclaratoria
                        or PREGUNTAS_ACLARATORIAS_DEFAULT.get(nombre_skill, {}).get("ambiguo")
                        or "¿A qué elemento específico te refieres?"
                    )
                    return ValidationResult(
                        is_valid=False,
                        status=IntentStatus.AMBIGUOUS,
                        skill_name=nombre_skill,
                        validated_parameters=parametros_raw,
                        missing_parameter=k,
                        clarification_prompt=pregunta,
                        candidates=candidatos,
                        reason=f"El valor '{v}' para el parámetro '{k}' es ambiguo.",
                    )

        # 5. Si el Brain ya clasificó explícitamente como AMBIGUOUS
        if parsed_intent.estado == IntentStatus.AMBIGUOUS:
            pregunta = (
                parsed_intent.pregunta_aclaratoria
                or PREGUNTAS_ACLARATORIAS_DEFAULT.get(nombre_skill, {}).get("ambiguo")
                or "¿Qué opción deseas seleccionar?"
            )
            return ValidationResult(
                is_valid=False,
                status=IntentStatus.AMBIGUOUS,
                skill_name=nombre_skill,
                validated_parameters=parametros_raw,
                missing_parameter=parsed_intent.parametro_faltante,
                clarification_prompt=pregunta,
                candidates=candidatos,
                reason="Intención clasificada como ambigua con múltiples objetivos posibles.",
            )

        # 6. Verificación determinista de presencia de parámetros requeridos
        requisitos = PARAMETROS_REQUERIDOS_SKILLS.get(nombre_skill, [])
        for grupo_alias in requisitos:
            valor_encontrado: Any = None
            for alias in grupo_alias:
                if alias in parametros_raw and parametros_raw[alias]:
                    val_str = str(parametros_raw[alias]).strip()
                    if val_str:
                        valor_encontrado = parametros_raw[alias]
                        break

            if valor_encontrado is None:
                # Falta parámetro obligatorio -> INCOMPLETE
                param_principal = grupo_alias[0]
                pregunta = (
                    parsed_intent.pregunta_aclaratoria
                    or PREGUNTAS_ACLARATORIAS_DEFAULT.get(nombre_skill, {}).get(param_principal)
                    or f"¿Cuál es el valor para '{param_principal}'?"
                )
                return ValidationResult(
                    is_valid=False,
                    status=IntentStatus.INCOMPLETE,
                    skill_name=nombre_skill,
                    validated_parameters=parametros_raw,
                    missing_parameter=param_principal,
                    clarification_prompt=pregunta,
                    reason=f"Falta el parámetro requerido '{param_principal}' para la skill '{nombre_skill}'.",
                )

        # 7. Si el Brain lo marcó como INCOMPLETE pero los parámetros están presentes
        if parsed_intent.estado == IntentStatus.INCOMPLETE:
            param_sugerido = parsed_intent.parametro_faltante
            if param_sugerido and (param_sugerido not in parametros_raw or not parametros_raw[param_sugerido]):
                pregunta = (
                    parsed_intent.pregunta_aclaratoria
                    or PREGUNTAS_ACLARATORIAS_DEFAULT.get(nombre_skill, {}).get(param_sugerido)
                    or f"¿Qué {param_sugerido} deseas especificar?"
                )
                return ValidationResult(
                    is_valid=False,
                    status=IntentStatus.INCOMPLETE,
                    skill_name=nombre_skill,
                    validated_parameters=parametros_raw,
                    missing_parameter=param_sugerido,
                    clarification_prompt=pregunta,
                    reason=f"Falta el parámetro '{param_sugerido}'.",
                )

        # 8. Todos los controles aprobados -> CLEAR y listo para autorizar
        return ValidationResult(
            is_valid=True,
            status=IntentStatus.CLEAR,
            skill_name=nombre_skill,
            validated_parameters=parametros_raw,
            reason="Intención y parámetros validados determinísticamente con éxito.",
        )


__all__ = [
    "IntentValidator",
    "PALABRAS_AMBIGUAS",
    "PARAMETROS_REQUERIDOS_SKILLS",
    "PREGUNTAS_ACLARATORIAS_DEFAULT",
]
