"""Cargador aislado y dinámico de módulos de Skills (isolated_loader.py - Fase 32).

Carga dinámicamente el código fuente Python de una Skill desde su directorio de instalación
sin contaminar el espacio de nombres global de 'sys.modules' y asegurando que la instancia
herede de 'BaseSkill'.

INVARIANTES DE SEGURIDAD:
1. Las Skills externas se ejecutan como UNTRUSTED CODE bajo el SkillSecuritySandbox.
2. Cada módulo cargado recibe un espacio de nombres único ('jessyca_installed_skills.<skill_id>_<version>').
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any

from core.exceptions import MCPError
from core.logger import get_logger
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillManifest,
)

logger = get_logger("jessyca.skills.isolated_loader")


class SkillLoaderError(MCPError):
    """Error emitido durante la carga dinámica de una Skill instalada."""

    pass


class IsolatedSkillLoader:
    """Cargador dinámico y seguro de instancias de BaseSkill desde disco."""

    @classmethod
    def load_skill_instance(
        cls,
        installed_dir: str | Path,
        manifest: SkillManifest,
    ) -> BaseSkill:
        """Carga e instancia la clase BaseSkill declarada en el entrypoint del paquete."""
        dir_path = Path(installed_dir).resolve()
        entrypoint_file = (dir_path / manifest.entrypoint).resolve()

        if not entrypoint_file.exists() or not entrypoint_file.is_file():
            raise SkillLoaderError(
                f"El archivo de entrada (entrypoint) '{manifest.entrypoint}' no existe en '{dir_path}'."
            )

        # Nombre de módulo aislado
        safe_mod_name = f"jessyca_installed_skills.{manifest.id.replace('.', '_')}_{manifest.version.replace('.', '_')}"

        try:
            spec = importlib.util.spec_from_file_location(safe_mod_name, str(entrypoint_file))
            if spec is None or spec.loader is None:
                raise SkillLoaderError(f"No se pudo crear el cargador de módulo para '{entrypoint_file}'.")

            module = importlib.util.module_from_spec(spec)
            sys.modules[safe_mod_name] = module

            # Ejecutar el módulo dentro de su espacio de nombres
            spec.loader.exec_module(module)

            # Buscar clases que hereden de BaseSkill
            skill_class: type[BaseSkill] | None = None
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BaseSkill) and obj is not BaseSkill:
                    skill_class = obj
                    break

            if skill_class is None:
                # Si no hay clase que herede directamente de BaseSkill, crear un wrapper genérico
                # buscando una función 'ejecutar' o 'run'
                exec_fn = getattr(module, "ejecutar", None) or getattr(module, "run", None) or getattr(module, "execute", None)
                if exec_fn is None or not callable(exec_fn):
                    raise SkillLoaderError(
                        f"El entrypoint '{manifest.entrypoint}' no define una clase BaseSkill ni una función 'ejecutar(parametros)'."
                    )

                skill_class = cls._create_dynamic_skill_class(manifest, exec_fn)

            # Instanciar la Skill
            try:
                instance = skill_class()  # type: ignore[call-arg]
            except TypeError:
                # Si el constructor requiere parámetros, intentar instanciar con nombre
                instance = skill_class(nombre=manifest.id)

            # Garantizar que la definición contenga el manifiesto
            if instance.definition.manifest is None:
                new_def = SkillDefinition(
                    skill_id=manifest.id,
                    name=manifest.name,
                    version=manifest.version,
                    description=manifest.description,
                    capabilities=manifest.capabilities,
                    required_tools=manifest.required_tools,
                    required_permissions=manifest.permissions,
                    risk_level=manifest.risk_level,
                    author=manifest.author,
                    min_system_version=manifest.min_system_version,
                    manifest=manifest,
                )
                instance._definition = new_def

            logger.info(f"[ISOLATED SKILL LOADED] Skill '{manifest.id}@{manifest.version}' instanciada exitosamente.")
            return instance

        except Exception as exc:
            logger.error(f"[SKILL LOADER ERROR] Error al cargar '{manifest.id}@{manifest.version}': {exc}")
            raise SkillLoaderError(f"Fallo al cargar la Skill '{manifest.id}': {exc}") from exc

    @staticmethod
    def _create_dynamic_skill_class(manifest: SkillManifest, exec_fn: Any) -> type[BaseSkill]:
        """Crea dinámicamente una subclase de BaseSkill para envolver una función 'ejecutar'."""
        class DynamicExternalSkill(BaseSkill):
            def __init__(self) -> None:
                definition = SkillDefinition(
                    skill_id=manifest.id,
                    name=manifest.name,
                    version=manifest.version,
                    description=manifest.description,
                    capabilities=manifest.capabilities,
                    required_tools=manifest.required_tools,
                    required_permissions=manifest.permissions,
                    risk_level=manifest.risk_level,
                    author=manifest.author,
                    min_system_version=manifest.min_system_version,
                    manifest=manifest,
                )
                super().__init__(nombre=manifest.id, nivel_riesgo=1, definition=definition)

            def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
                try:
                    res = exec_fn(parametros)
                    if isinstance(res, dict):
                        return res
                    return {"exito": True, "resultado": res}
                except Exception as e:
                    return {"exito": False, "error": str(e)}

        return DynamicExternalSkill
