"""Skill de búsqueda de archivos en el sistema de archivos (file_search_skill.py - Fase 28.7).

Permite buscar archivos respetando límites de sandbox y rutas críticas de Windows.
No accede a APIs privilegiadas directamente; se ejecuta bajo SecurityPipeline.
"""

from __future__ import annotations

import os
from typing import Any

from core.logger import get_logger
from core.risk_engine import WINDOWS_CRITICAL_PATHS
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillManifest,
)

logger = get_logger("jessyca.skills.filesearch")


class FilesSearchSkill(BaseSkill):
    """Skill de producción para búsqueda segura de archivos y documentos."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.search",
            name="Filesystem Search",
            version="1.0.0",
            description="Busca archivos y documentos en el sistema de archivos respetando sandbox y rutas protegidas.",
            author="Jessyca Core",
            capabilities=("filesystem_read", "filesystem"),
            required_tools=("file.search", "files.search"),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("file.search",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="files.search",
            name="Filesystem Search",
            version="1.0.0",
            description="Busca archivos y documentos en el sistema de archivos.",
            capabilities=("filesystem_read", "filesystem"),
            required_tools=("file.search", "files.search"),
            required_permissions=("file.search",),
            risk_level=SecurityLevel.SAFE,
            tags=("archivos", "buscar", "documentos", "ficheros", "informe", "disco", "busca", "archivo"),
            manifest=manifest,
        )
        super().__init__(nombre="files.search", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        nombre_archivo = str(
            parametros.get("nombre")
            or parametros.get("query")
            or parametros.get("pattern")
            or parametros.get("file")
            or ""
        ).strip().lower()

        if not nombre_archivo:
            return {"exito": False, "mensaje": "Debe especificar el nombre o patrón del archivo a buscar."}

        ruta_base = str(parametros.get("ruta") or parametros.get("path") or os.getcwd()).strip()

        # Validación de ruta contra rutas críticas de Windows
        ruta_clean = ruta_base.lower().replace("/", "\\")
        for crit in WINDOWS_CRITICAL_PATHS:
            if crit.replace("/", "\\") in ruta_clean:
                return {
                    "exito": False,
                    "mensaje": f"Acceso denegado: Búsqueda bloqueada en ruta protegida '{crit}'.",
                }

        if not os.path.exists(ruta_base):
            return {"exito": False, "mensaje": f"La ruta de búsqueda '{ruta_base}' no existe."}

        coincidencias = []
        max_resultados = int(parametros.get("max_results", 20))

        try:
            for root, _dirs, files in os.walk(ruta_base):
                # Omitir directorios ocultos o pesados
                if ".git" in root or "node_modules" in root or ".venv" in root or "venv" in root:
                    continue

                for f in files:
                    if nombre_archivo in f.lower():
                        full_path = os.path.join(root, f)
                        try:
                            tamano = os.path.getsize(full_path)
                        except OSError:
                            tamano = 0

                        coincidencias.append({
                            "nombre": f,
                            "ruta": full_path,
                            "tamano_bytes": tamano,
                        })
                        if len(coincidencias) >= max_resultados:
                            break

                if len(coincidencias) >= max_resultados:
                    break

            return {
                "exito": True,
                "mensaje": f"Búsqueda finalizada. Se encontraron {len(coincidencias)} archivo(s).",
                "coincidencias": coincidencias,
                "total": len(coincidencias),
            }

        except Exception as exc:
            logger.error(f"[FILE SEARCH ERROR] Error durante la búsqueda: {exc}")
            return {"exito": False, "mensaje": f"Error al buscar archivos: {exc}"}
