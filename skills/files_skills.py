"""Habilidades del subsistema de archivos (files_skills.py - Fase 28.8).

Contiene:
1. FilesReadSkill (files.read)
2. FilesCreateSkill (files.create)
3. FilesCopySkill (files.copy)
4. FilesMoveSkill (files.move)
5. FilesRenameSkill (files.rename)
6. FilesOrganizeSkill (files.organize)

Todas las habilidades respetan el sandbox de rutas y bloquean rutas críticas de Windows.
"""

from __future__ import annotations

import os
import shutil
from typing import Any

from core.logger import get_logger
from core.risk_engine import WINDOWS_CRITICAL_PATHS
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillManifest,
)

logger = get_logger("jessyca.skills.files")

FORBIDDEN_EXECUTABLE_EXTENSIONS: frozenset[str] = frozenset({
    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".msi", ".dll", ".sys", ".scr", ".pif",
})


def _is_path_critical(path: str) -> bool:
    path_norm = os.path.abspath(path).lower().replace("/", "\\")
    for crit in WINDOWS_CRITICAL_PATHS:
        crit_norm = crit.lower().replace("/", "\\")
        if crit_norm in path_norm:
            return True
    return False


class FilesReadSkill(BaseSkill):
    """Skill para lectura segura de archivos de texto y código."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.read",
            name="Filesystem Reader",
            version="1.0.0",
            description="Lee el contenido de archivos de texto, código y configuración dentro del espacio de trabajo.",
            author="Jessyca Core",
            capabilities=("filesystem_read", "filesystem"),
            required_tools=("file.read",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("file.read",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="files.read",
            name="Filesystem Reader",
            version="1.0.0",
            description="Lectura segura de archivos.",
            capabilities=("filesystem_read", "filesystem"),
            required_tools=("file.read",),
            required_permissions=("file.read",),
            risk_level=SecurityLevel.SAFE,
            tags=("leer", "archivo", "contenido", "texto", "codigo", "read"),
            manifest=manifest,
        )
        super().__init__(nombre="files.read", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        ruta = str(parametros.get("ruta") or parametros.get("path") or parametros.get("file") or "").strip()
        if not ruta:
            return {"exito": False, "mensaje": "Debe especificar la ruta del archivo a leer."}

        if _is_path_critical(ruta):
            return {"exito": False, "mensaje": "Acceso denegado: Intento de lectura en ruta crítica de Windows."}

        if not os.path.isfile(ruta):
            return {"exito": False, "mensaje": f"El archivo '{ruta}' no existe o no es un archivo regular."}

        try:
            with open(ruta, encoding="utf-8", errors="replace") as f:
                contenido = f.read(50000)  # Límite seguro de lectura
            return {
                "exito": True,
                "mensaje": f"Archivo '{os.path.basename(ruta)}' leído con éxito.",
                "contenido": contenido,
                "longitud": len(contenido),
            }
        except Exception as exc:
            return {"exito": False, "mensaje": f"Error al leer el archivo '{ruta}': {exc}"}


class FilesCreateSkill(BaseSkill):
    """Skill para creación segura de archivos de texto/código dentro del workspace."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.create",
            name="Filesystem Creator",
            version="1.0.0",
            description="Crea nuevos archivos de texto o código validando extensiones no ejecutables.",
            author="Jessyca Core",
            capabilities=("filesystem_write", "filesystem"),
            required_tools=("file.write",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("file.write",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="files.create",
            name="Filesystem Creator",
            version="1.0.0",
            description="Creación segura de archivos.",
            capabilities=("filesystem_write", "filesystem"),
            required_tools=("file.write",),
            required_permissions=("file.write",),
            risk_level=SecurityLevel.SAFE,
            tags=("crear", "escribir", "guardar", "archivo", "nuevo", "create"),
            manifest=manifest,
        )
        super().__init__(nombre="files.create", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        ruta = str(parametros.get("ruta") or parametros.get("path") or parametros.get("file") or "").strip()
        contenido = str(parametros.get("contenido") or parametros.get("content") or "")

        if not ruta:
            return {"exito": False, "mensaje": "Debe especificar la ruta del archivo a crear."}

        _, ext = os.path.splitext(ruta)
        if ext.lower() in FORBIDDEN_EXECUTABLE_EXTENSIONS:
            return {
                "exito": False,
                "mensaje": f"Seguridad: Extensión de archivo peligrosa bloqueada '{ext}'.",
            }

        if _is_path_critical(ruta):
            return {"exito": False, "mensaje": "Acceso denegado: Intento de escritura en ruta crítica de Windows."}

        try:
            dir_name = os.path.dirname(ruta)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(contenido)
            return {
                "exito": True,
                "mensaje": f"Archivo '{os.path.basename(ruta)}' creado con éxito.",
                "ruta": os.path.abspath(ruta),
                "bytes_escritos": len(contenido.encode("utf-8")),
            }
        except Exception as exc:
            return {"exito": False, "mensaje": f"Error al crear archivo '{ruta}': {exc}"}


class FilesCopySkill(BaseSkill):
    """Skill para duplicar/copiar archivos de forma segura."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.copy",
            name="Filesystem Copier",
            version="1.0.0",
            description="Copia archivos entre ubicaciones válidas del sistema.",
            author="Jessyca Core",
            capabilities=("filesystem_read", "filesystem_write"),
            required_tools=("file.copy",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("file.copy",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="files.copy",
            name="Filesystem Copier",
            version="1.0.0",
            description="Copia de archivos.",
            capabilities=("filesystem_read", "filesystem_write"),
            required_tools=("file.copy",),
            required_permissions=("file.copy",),
            risk_level=SecurityLevel.SAFE,
            tags=("copiar", "duplicar", "archivo", "copy"),
            manifest=manifest,
        )
        super().__init__(nombre="files.copy", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        origen = str(parametros.get("origen") or parametros.get("source") or "").strip()
        destino = str(parametros.get("destino") or parametros.get("target") or "").strip()

        if not origen or not destino:
            return {"exito": False, "mensaje": "Debe especificar origen y destino."}

        if _is_path_critical(origen) or _is_path_critical(destino):
            return {"exito": False, "mensaje": "Acceso denegado: Operación bloqueada en ruta crítica."}

        if not os.path.exists(origen):
            return {"exito": False, "mensaje": f"El archivo origen '{origen}' no existe."}

        try:
            shutil.copy2(origen, destino)
            return {"exito": True, "mensaje": f"Archivo copiado de '{origen}' a '{destino}'."}
        except Exception as exc:
            return {"exito": False, "mensaje": f"Error al copiar archivo: {exc}"}


class FilesMoveSkill(BaseSkill):
    """Skill para mover archivos entre directorios autorizados."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.move",
            name="Filesystem Mover",
            version="1.0.0",
            description="Mueve archivos de forma gobernada.",
            author="Jessyca Core",
            capabilities=("filesystem_read", "filesystem_write"),
            required_tools=("file.move",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("file.move",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="files.move",
            name="Filesystem Mover",
            version="1.0.0",
            description="Mover archivos.",
            capabilities=("filesystem_read", "filesystem_write"),
            required_tools=("file.move",),
            required_permissions=("file.move",),
            risk_level=SecurityLevel.SAFE,
            tags=("mover", "trasladar", "archivo", "move"),
            manifest=manifest,
        )
        super().__init__(nombre="files.move", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        origen = str(parametros.get("origen") or parametros.get("source") or "").strip()
        destino = str(parametros.get("destino") or parametros.get("target") or "").strip()

        if not origen or not destino:
            return {"exito": False, "mensaje": "Debe especificar origen y destino."}

        if _is_path_critical(origen) or _is_path_critical(destino):
            return {"exito": False, "mensaje": "Acceso denegado: Operación bloqueada en ruta crítica."}

        if not os.path.exists(origen):
            return {"exito": False, "mensaje": f"El archivo origen '{origen}' no existe."}

        try:
            shutil.move(origen, destino)
            return {"exito": True, "mensaje": f"Archivo movido a '{destino}'."}
        except Exception as exc:
            return {"exito": False, "mensaje": f"Error al mover archivo: {exc}"}


class FilesRenameSkill(BaseSkill):
    """Skill para renombrar archivos dentro del mismo directorio."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.rename",
            name="Filesystem Renamer",
            version="1.0.0",
            description="Renombra archivos validando nombres no maliciosos.",
            author="Jessyca Core",
            capabilities=("filesystem_read", "filesystem_write"),
            required_tools=("file.rename",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("file.rename",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="files.rename",
            name="Filesystem Renamer",
            version="1.0.0",
            description="Renombrar archivos.",
            capabilities=("filesystem_read", "filesystem_write"),
            required_tools=("file.rename",),
            required_permissions=("file.rename",),
            risk_level=SecurityLevel.SAFE,
            tags=("renombrar", "cambiar nombre", "archivo", "rename"),
            manifest=manifest,
        )
        super().__init__(nombre="files.rename", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        ruta_actual = str(parametros.get("ruta") or parametros.get("path") or "").strip()
        nuevo_nombre = str(parametros.get("nuevo_nombre") or parametros.get("new_name") or "").strip()

        if not ruta_actual or not nuevo_nombre:
            return {"exito": False, "mensaje": "Debe especificar la ruta actual y el nuevo nombre."}

        if _is_path_critical(ruta_actual):
            return {"exito": False, "mensaje": "Acceso denegado: Operación bloqueada en ruta crítica."}

        if not os.path.exists(ruta_actual):
            return {"exito": False, "mensaje": f"El archivo '{ruta_actual}' no existe."}

        dir_name = os.path.dirname(ruta_actual)
        nueva_ruta = os.path.join(dir_name, nuevo_nombre)

        try:
            os.rename(ruta_actual, nueva_ruta)
            return {"exito": True, "mensaje": f"Archivo renombrado a '{nuevo_nombre}'."}
        except Exception as exc:
            return {"exito": False, "mensaje": f"Error al renombrar archivo: {exc}"}


class FilesOrganizeSkill(BaseSkill):
    """Skill para organizar archivos en carpetas según su extensión o categoría."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.organize",
            name="Filesystem Organizer",
            version="1.0.0",
            description="Organiza mis archivos en subdirectorios categorizados por extensión.",
            author="Jessyca Core",
            capabilities=("filesystem_read", "filesystem_write"),
            required_tools=("file.search", "file.move"),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("file.search", "file.move"),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="files.organize",
            name="Filesystem Organizer",
            version="1.0.0",
            description="Organización automática de archivos.",
            capabilities=("filesystem_read", "filesystem_write"),
            required_tools=("file.search", "file.move"),
            required_permissions=("file.search", "file.move"),
            risk_level=SecurityLevel.SAFE,
            tags=("organiza", "organizar", "ordenar", "archivos", "carpetas", "limpieza"),
            manifest=manifest,
        )
        super().__init__(nombre="files.organize", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        directorio = str(parametros.get("directorio") or parametros.get("path") or ".").strip()

        if _is_path_critical(directorio):
            return {"exito": False, "mensaje": "Acceso denegado: No se puede organizar un directorio crítico de Windows."}

        if not os.path.isdir(directorio):
            return {"exito": False, "mensaje": f"El directorio '{directorio}' no existe."}

        categorias = {
            "Documentos": {".pdf", ".docx", ".doc", ".txt", ".md", ".xlsx", ".pptx"},
            "Imagenes": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"},
            "Datos": {".json", ".csv", ".xml", ".yaml", ".yml", ".sql"},
            "Audio_Video": {".mp3", ".wav", ".mp4", ".mkv", ".avi"},
            "Comprimidos": {".zip", ".rar", ".7z", ".tar", ".gz"},
        }

        organizados = 0
        try:
            for item in os.listdir(directorio):
                item_path = os.path.join(directorio, item)
                if os.path.isfile(item_path):
                    _, ext = os.path.splitext(item)
                    ext_lower = ext.lower()

                    for cat_nombre, ext_set in categorias.items():
                        if ext_lower in ext_set:
                            dest_dir = os.path.join(directorio, cat_nombre)
                            os.makedirs(dest_dir, exist_ok=True)
                            shutil.move(item_path, os.path.join(dest_dir, item))
                            organizados += 1
                            break

            return {
                "exito": True,
                "mensaje": f"Organización completada. Se clasificaron {organizados} archivo(s).",
                "archivos_organizados": organizados,
            }
        except Exception as exc:
            return {"exito": False, "mensaje": f"Error organizando archivos: {exc}"}
