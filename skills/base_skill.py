"""Clase base abstracta para habilidades de JESSYCA (base_skill.py - Fase 28.0).

Garantiza compatibilidad dual:
1. Interfaz retrocompatible: ejecutar(parametros) -> dict
2. Interfaz moderna Skill Framework: execute(context) -> SkillResult
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from core.security_architecture import SecurityLevel
from skills.skill_models import (
    SkillContext,
    SkillDefinition,
    SkillResult,
    SkillStatus,
)


class BaseSkill(ABC):
    """Clase base abstracta para todas las habilidades (skills) de Jessyca."""

    def __init__(
        self,
        nombre: str,
        nivel_riesgo: int = 1,
        definition: SkillDefinition | None = None,
    ) -> None:
        """Inicializa la skill.

        :param nombre: Nombre identificador de la skill.
        :param nivel_riesgo: 1 = bajo (auto-ejecuta), 2 = medio (confirma una vez), 3 = alto (siempre confirma explícito).
        :param definition: Definición tipada opcional del Skill Framework.
        """
        self.nombre = nombre
        self.nivel_riesgo = nivel_riesgo

        # Mapeo de nivel de riesgo numérico a SecurityLevel
        risk_map = {
            1: SecurityLevel.SAFE,
            2: SecurityLevel.LOW,
            3: SecurityLevel.HIGH,
        }
        eff_risk = risk_map.get(nivel_riesgo, SecurityLevel.SAFE)

        self._definition = definition or SkillDefinition(
            skill_id=nombre,
            name=nombre,
            description=self.descripcion(),
            risk_level=eff_risk,
        )

    @property
    def skill_id(self) -> str:
        """Identificador de la skill."""
        return self._definition.skill_id

    @property
    def version(self) -> str:
        """Versión de la skill."""
        return self._definition.version

    @property
    def definition(self) -> SkillDefinition:
        """Metadatos formales e inmutables de la skill."""
        return self._definition

    @abstractmethod
    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta la acción correspondiente a la skill (método clásico).

        :param parametros: Diccionario con los parámetros requeridos para la ejecución.
        :return: Diccionario con el formato {"exito": bool, "mensaje": str}
        """
        pass

    def execute(self, context: SkillContext) -> SkillResult:
        """Ejecución moderna tipada e integrada con SkillContext del Skill Framework."""
        start_time = time.perf_counter()
        try:
            res_dict = self.ejecutar(context.parameters)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            success = bool(res_dict.get("exito", False))
            status = SkillStatus.COMPLETED if success else SkillStatus.FAILED
            msg = str(res_dict.get("mensaje", ""))
            error_msg = None if success else msg

            return SkillResult(
                skill_id=self.skill_id,
                success=success,
                status=status,
                output=res_dict,
                error=error_msg,
                execution_id=context.execution_id,
                duration_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillResult(
                skill_id=self.skill_id,
                success=False,
                status=SkillStatus.FAILED,
                error=str(e),
                execution_id=context.execution_id,
                duration_ms=elapsed_ms,
            )

    def descripcion(self) -> str:
        """Retorna la descripción de lo que realiza la skill."""
        if self.__doc__:
            return self.__doc__.strip()
        return f"Skill {self.nombre}"
