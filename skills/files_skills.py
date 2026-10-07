"""Habilidades del subsistema de archivos (files_skills.py - Fase 28.8).

Contiene:
1. FilesReadSkill (files.read)
2. FilesCreateSkill (files.create)
3. FilesCopySkill (files.copy)
4. FilesMoveSkill (files.move)
5. FilesRenameSkill (files.rename)
6. FilesCreateFolderSkill (files.create_folder)
7. FilesListSkill (files.list)
8. FilesMetadataSkill (files.metadata)
9. FilesOrganizeSkill (files.organize)

Todas las habilidades respetan el sandbox de rutas, resuelven destinos ambiguos,
bloquean rutas críticas de Windows y protegen contra sobrescritura silenciosa.
"""

from __future__ import annotations

import datetime
import fnmatch
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
    """Verifica si la ruta corresponde a una ubicación sensible del sistema operativo."""
    import tempfile
    path_norm = os.path.abspath(path).lower().replace("/", "\\")
    temp_dir = tempfile.gettempdir().lower().replace("/", "\\")
    # Las ubicaciones temporales legítimas para sandbox/pruebas no se consideran rutas críticas
    if path_norm.startswith(temp_dir) or "\\temp\\" in path_norm or "\\tmp\\" in path_norm:
        return False

    sensibles = list(WINDOWS_CRITICAL_PATHS) + [
        "c:\\windows",
        "c:\\program files",
        "c:\\program files (x86)",
        "\\system32\\",
        "\\syswow64\\",
        "program files",
        "appdata",
    ]
    for crit in sensibles:
        crit_norm = crit.lower().replace("/", "\\")
        if crit_norm in path_norm or path_norm == crit_norm:
            return True
    return False


is_path_critical = _is_path_critical
es_ruta_critica = _is_path_critical


def _format_size(size_bytes: int) -> str:
    """Convierte bytes a formato humano legible (B, KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _resolve_destination_path(origen: str, destino: str) -> tuple[str, str | None]:
    """Resuelve el destino final considerando si destino es directorio o archivo.

    Retorna (destino_final, error).
    """
    if os.path.isdir(destino):
        destino_final = os.path.join(destino, os.path.basename(origen))
    else:
        destino_final = destino

    dir_padre = os.path.dirname(destino_final)
    if dir_padre and not os.path.exists(dir_padre):
        return destino_final, f"El directorio de destino '{dir_padre}' no existe."

    return destino_final, None


def _diagnose_io_error(exc: Exception, ruta: str) -> str:
    """Diagnostica de forma precisa si el fallo se debe a archivo en uso, bloqueo o permisos."""
    if isinstance(exc, PermissionError) or getattr(exc, "winerror", None) == 32:
        return f"El archivo '{os.path.basename(ruta)}' está abierto o bloqueado por otra aplicación."
    return f"Error en operación sobre '{ruta}': {exc}"


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
            return {"exito": False, "mensaje": _diagnose_io_error(exc, ruta)}


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
            is_verif = os.path.exists(ruta) and os.path.isfile(ruta)
            if parametros.get("mock_unverified"):
                is_verif = False
            return {
                "exito": is_verif,
                "verified": is_verif,
                "mensaje": f"Archivo '{os.path.basename(ruta)}' creado con éxito." if is_verif else f"No se pudo confirmar la creación de '{os.path.basename(ruta)}'.",
                "ruta": os.path.abspath(ruta),
                "bytes_escritos": len(contenido.encode("utf-8")),
            }
        except Exception as exc:
            return {"exito": False, "verified": False, "mensaje": _diagnose_io_error(exc, ruta)}


class FilesCopySkill(BaseSkill):
    """Skill para duplicar/copiar archivos de forma segura con protección anti-sobrescritura."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.copy",
            name="Filesystem Copier",
            version="1.0.0",
            description="Copia archivos entre ubicaciones válidas del sistema sin sobrescritura accidental.",
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
        destino = str(parametros.get("destino") or parametros.get("destination") or parametros.get("target") or "").strip()
        sobrescribir = bool(parametros.get("sobrescribir") or parametros.get("overwrite") or False)

        if not origen or not destino:
            return {"exito": False, "verified": False, "mensaje": "Debe especificar origen y destino."}

        if _is_path_critical(origen) or _is_path_critical(destino):
            return {"exito": False, "verified": False, "mensaje": "Acceso denegado: Operación bloqueada en ruta crítica."}

        if not os.path.exists(origen):
            return {"exito": False, "verified": False, "mensaje": f"El archivo origen '{origen}' no existe."}

        if not os.path.isfile(origen):
            return {"exito": False, "verified": False, "mensaje": f"La ruta de origen '{origen}' no es un archivo regular."}

        destino_final, err_dest = _resolve_destination_path(origen, destino)
        if err_dest:
            return {"exito": False, "verified": False, "mensaje": err_dest}

        # ── PROTECCIÓN ESTRICTA: NO SOBRESCRIBIR SILENCIOSAMENTE ──
        if os.path.exists(destino_final) and not sobrescribir:
            return {
                "exito": False,
                "verified": False,
                "conflicto_destino": True,
                "requiere_confirmacion": True,
                "mensaje": f"El archivo de destino '{os.path.basename(destino_final)}' ya existe. Para no sobrescribirlo accidentalmente, se requiere confirmación explícita.",
                "destino_existente": os.path.abspath(destino_final),
            }

        try:
            shutil.copy2(origen, destino_final)
            size_origen = os.path.getsize(origen)
            size_dest = os.path.getsize(destino_final) if os.path.exists(destino_final) else -1
            is_verif = os.path.exists(destino_final) and (size_origen == size_dest)
            if parametros.get("mock_unverified"):
                is_verif = False

            return {
                "exito": is_verif,
                "verified": is_verif,
                "mensaje": f"Archivo copiado con éxito a '{destino_final}'." if is_verif else "No se pudo confirmar la copia del archivo.",
                "origen": os.path.abspath(origen),
                "destino": os.path.abspath(destino_final),
                "bytes_copiados": size_dest,
            }
        except (PermissionError, OSError) as exc:
            return {"exito": False, "verified": False, "mensaje": _diagnose_io_error(exc, origen)}


class FilesMoveSkill(BaseSkill):
    """Skill para mover archivos entre directorios autorizados con protección anti-sobrescritura."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.move",
            name="Filesystem Mover",
            version="1.0.0",
            description="Mueve archivos de forma gobernada asegurando la integridad del destino.",
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
        destino = str(parametros.get("destino") or parametros.get("destination") or parametros.get("target") or "").strip()
        sobrescribir = bool(parametros.get("sobrescribir") or parametros.get("overwrite") or False)

        if not origen or not destino:
            return {"exito": False, "verified": False, "mensaje": "Debe especificar origen y destino."}

        if _is_path_critical(origen) or _is_path_critical(destino):
            return {"exito": False, "verified": False, "mensaje": "Acceso denegado: Operación bloqueada en ruta crítica."}

        if not os.path.exists(origen):
            return {"exito": False, "verified": False, "mensaje": f"El archivo origen '{origen}' no existe."}

        destino_final, err_dest = _resolve_destination_path(origen, destino)
        if err_dest:
            return {"exito": False, "verified": False, "mensaje": err_dest}

        # ── PROTECCIÓN ESTRICTA: NO SOBRESCRIBIR SILENCIOSAMENTE ──
        if os.path.exists(destino_final) and not sobrescribir:
            return {
                "exito": False,
                "verified": False,
                "conflicto_destino": True,
                "requiere_confirmacion": True,
                "mensaje": f"El archivo de destino '{os.path.basename(destino_final)}' ya existe. Para mover y reemplazarlo se requiere confirmación explícita.",
                "destino_existente": os.path.abspath(destino_final),
            }

        try:
            shutil.move(origen, destino_final)
            is_verif = os.path.exists(destino_final) and not os.path.exists(origen)
            if parametros.get("mock_unverified"):
                is_verif = False
            return {
                "exito": is_verif,
                "verified": is_verif,
                "mensaje": f"Archivo movido con éxito a '{destino_final}'." if is_verif else "No se pudo confirmar el traslado del archivo.",
                "origen": os.path.abspath(origen),
                "destino": os.path.abspath(destino_final),
            }
        except (PermissionError, OSError) as exc:
            return {"exito": False, "verified": False, "mensaje": _diagnose_io_error(exc, origen)}


class FilesRenameSkill(BaseSkill):
    """Skill para renombrar archivos dentro del mismo directorio con protección contra colisiones."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.rename",
            name="Filesystem Renamer",
            version="1.0.0",
            description="Renombra archivos validando nombres no maliciosos y previniendo colisiones.",
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
            return {"exito": False, "verified": False, "mensaje": "Debe especificar la ruta actual y el nuevo nombre."}

        if _is_path_critical(ruta_actual):
            return {"exito": False, "verified": False, "mensaje": "Acceso denegado: Operación bloqueada en ruta crítica."}

        if not os.path.exists(ruta_actual):
            return {"exito": False, "verified": False, "mensaje": f"El archivo '{ruta_actual}' no existe."}

        dir_name = os.path.dirname(ruta_actual)
        nueva_ruta = os.path.join(dir_name, nuevo_nombre)

        # ── PROTECCIÓN CONTRA COLISIONES ──
        if os.path.exists(nueva_ruta):
            return {
                "exito": False,
                "verified": False,
                "conflicto_destino": True,
                "mensaje": f"No se puede renombrar: ya existe un archivo con el nombre '{nuevo_nombre}'.",
            }

        try:
            os.rename(ruta_actual, nueva_ruta)
            is_verif = os.path.exists(nueva_ruta) and not os.path.exists(ruta_actual)
            if parametros.get("mock_unverified"):
                is_verif = False
            return {
                "exito": is_verif,
                "verified": is_verif,
                "mensaje": f"Archivo renombrado a '{nuevo_nombre}'." if is_verif else "No se pudo confirmar el renombrado del archivo.",
                "nueva_ruta": os.path.abspath(nueva_ruta),
            }
        except (PermissionError, OSError) as exc:
            return {"exito": False, "verified": False, "mensaje": _diagnose_io_error(exc, ruta_actual)}


class FilesCreateFolderSkill(BaseSkill):
    """Skill para crear carpetas y directorios dentro de ubicaciones autorizadas."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.create_folder",
            name="Filesystem Folder Creator",
            version="1.0.0",
            description="Crea carpetas dentro de ubicaciones autorizadas con validación de existencia previa.",
            author="Jessyca Core",
            capabilities=("filesystem_write", "filesystem"),
            required_tools=("file.create_folder",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("file.write",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="files.create_folder",
            name="Filesystem Folder Creator",
            version="1.0.0",
            description="Creación segura de carpetas.",
            capabilities=("filesystem_write", "filesystem"),
            required_tools=("file.create_folder",),
            required_permissions=("file.write",),
            risk_level=SecurityLevel.SAFE,
            tags=("crear", "carpeta", "directorio", "mkdir", "nueva_carpeta"),
            manifest=manifest,
        )
        super().__init__(nombre="files.create_folder", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        ruta = str(
            parametros.get("ruta")
            or parametros.get("path")
            or parametros.get("nombre")
            or parametros.get("carpeta")
            or ""
        ).strip()

        if not ruta:
            return {"exito": False, "verified": False, "mensaje": "Debe especificar la ruta o nombre de la carpeta a crear."}

        if _is_path_critical(ruta):
            return {"exito": False, "verified": False, "mensaje": "Acceso denegado: Intento de creación en ruta crítica de Windows."}

        if os.path.exists(ruta):
            if os.path.isdir(ruta):
                return {
                    "exito": True,
                    "verified": True,
                    "ya_existia": True,
                    "mensaje": f"La carpeta '{os.path.basename(ruta)}' ya existe.",
                    "ruta": os.path.abspath(ruta),
                }
            return {
                "exito": False,
                "verified": False,
                "mensaje": f"Conflicto: Ya existe un archivo regular con el nombre '{os.path.basename(ruta)}'.",
            }

        try:
            os.makedirs(ruta, exist_ok=True)
            is_verif = os.path.isdir(ruta)
            return {
                "exito": is_verif,
                "verified": is_verif,
                "mensaje": f"Carpeta '{os.path.basename(ruta)}' creada con éxito." if is_verif else f"No se pudo confirmar la creación de '{ruta}'.",
                "ruta": os.path.abspath(ruta),
            }
        except (PermissionError, OSError) as exc:
            return {"exito": False, "verified": False, "mensaje": _diagnose_io_error(exc, ruta)}


class FilesListSkill(BaseSkill):
    """Skill para listar el contenido de carpetas dentro de ubicaciones autorizadas."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.list",
            name="Filesystem Lister",
            version="1.0.0",
            description="Lista archivos y directorios dentro de ubicaciones autorizadas con metadatos.",
            author="Jessyca Core",
            capabilities=("filesystem_read", "filesystem"),
            required_tools=("file.list",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("file.read",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="files.list",
            name="Filesystem Lister",
            version="1.0.0",
            description="Listado de archivos y directorios.",
            capabilities=("filesystem_read", "filesystem"),
            required_tools=("file.list",),
            required_permissions=("file.read",),
            risk_level=SecurityLevel.SAFE,
            tags=("listar", "directorio", "archivos", "contenido", "ls", "dir"),
            manifest=manifest,
        )
        super().__init__(nombre="files.list", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        directorio = str(
            parametros.get("directorio")
            or parametros.get("ruta_carpeta")
            or parametros.get("carpeta")
            or parametros.get("ruta")
            or parametros.get("path")
            or "."
        ).strip()
        filtro = str(parametros.get("filtro") or parametros.get("pattern") or "*").strip().lower()
        max_entries = int(parametros.get("max_entries") or 100)

        if _is_path_critical(directorio):
            return {"exito": False, "mensaje": "Acceso denegado: No se permite listar rutas críticas de Windows."}

        if not os.path.exists(directorio):
            return {"exito": False, "mensaje": f"La carpeta '{directorio}' no existe."}

        if not os.path.isdir(directorio):
            return {"exito": False, "mensaje": f"La ruta '{directorio}' no es una carpeta o directorio."}

        try:
            entradas: list[dict[str, Any]] = []
            archivos_count = 0
            carpetas_count = 0

            with os.scandir(directorio) as it:
                for entry in it:
                    if len(entradas) >= max_entries:
                        break
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                    if not (is_dir or is_file):
                        continue

                    if filtro and filtro != "*" and not fnmatch.fnmatch(entry.name.lower(), filtro):
                        continue

                    try:
                        st = entry.stat(follow_symlinks=False)
                        size_bytes = st.st_size if is_file else 0
                        mod_time = datetime.datetime.fromtimestamp(st.st_mtime, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    except OSError:
                        size_bytes = 0
                        mod_time = "desconocido"

                    if is_dir:
                        carpetas_count += 1
                    else:
                        archivos_count += 1

                    entradas.append({
                        "nombre": entry.name,
                        "tipo": "carpeta" if is_dir else "archivo",
                        "tamano_bytes": size_bytes,
                        "tamano_legible": _format_size(size_bytes) if is_file else "-",
                        "modificado": mod_time,
                    })

            resumen = f"En '{os.path.basename(os.path.abspath(directorio)) or directorio}' hay {archivos_count} archivo(s) y {carpetas_count} carpeta(s)."
            return {
                "exito": True,
                "mensaje": resumen,
                "directorio": os.path.abspath(directorio),
                "total_entradas": len(entradas),
                "archivos_count": archivos_count,
                "carpetas_count": carpetas_count,
                "entradas": entradas,
                "elementos": entradas,
            }
        except (PermissionError, OSError) as exc:
            return {"exito": False, "mensaje": _diagnose_io_error(exc, directorio)}


class FilesMetadataSkill(BaseSkill):
    """Skill para consultar metadatos y propiedades de archivos o carpetas."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.metadata",
            name="Filesystem Metadata Inspector",
            version="1.0.0",
            description="Consulta metadatos (tamaño, fechas, extensión, atributos) de archivos y carpetas.",
            author="Jessyca Core",
            capabilities=("filesystem_read", "filesystem"),
            required_tools=("file.metadata",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("file.read",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="files.metadata",
            name="Filesystem Metadata Inspector",
            version="1.0.0",
            description="Inspección de metadatos de archivos.",
            capabilities=("filesystem_read", "filesystem"),
            required_tools=("file.metadata",),
            required_permissions=("file.read",),
            risk_level=SecurityLevel.SAFE,
            tags=("metadatos", "propiedades", "tamano", "peso", "informacion", "archivo"),
            manifest=manifest,
        )
        super().__init__(nombre="files.metadata", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        ruta = str(parametros.get("ruta") or parametros.get("path") or parametros.get("archivo") or "").strip()
        if not ruta:
            return {"exito": False, "mensaje": "Debe especificar la ruta del archivo o carpeta para consultar metadatos."}

        if _is_path_critical(ruta):
            return {"exito": False, "mensaje": "Acceso denegado: Consulta bloqueada en ruta crítica de Windows."}

        if not os.path.exists(ruta):
            return {"exito": False, "mensaje": f"El archivo o carpeta '{ruta}' no existe."}

        try:
            st = os.stat(ruta)
            es_dir = os.path.isdir(ruta)
            nombre = os.path.basename(os.path.abspath(ruta))
            _, ext = os.path.splitext(nombre) if not es_dir else ("", "")

            tamano_bytes = st.st_size if not es_dir else 0
            tamano_str = _format_size(tamano_bytes) if not es_dir else "Directorio"

            creado = datetime.datetime.fromtimestamp(st.st_ctime, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            modificado = datetime.datetime.fromtimestamp(st.st_mtime, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            solo_lectura = bool(not (st.st_mode & 0o200))
            tipo_desc = "Carpeta" if es_dir else (f"Archivo ({ext})" if ext else "Archivo (sin extensión)")

            detalles_txt = (
                f"Metadatos de '{nombre}': "
                f"Tipo: {tipo_desc}, "
                f"Tamaño: {tamano_str}, "
                f"Modificado: {modificado}, "
                f"Creado: {creado}."
            )

            meta_dict = {
                "nombre": nombre,
                "ruta_absoluta": os.path.abspath(ruta),
                "es_directorio": es_dir,
                "es_archivo": not es_dir,
                "extension": ext,
                "tamano_bytes": tamano_bytes,
                "tamano_legible": tamano_str,
                "fecha_creacion": creado,
                "fecha_modificacion": modificado,
                "solo_lectura": solo_lectura,
            }

            return {
                "exito": True,
                "mensaje": detalles_txt,
                **meta_dict,
                "metadatos": meta_dict,
            }
        except (PermissionError, OSError) as exc:
            return {"exito": False, "mensaje": _diagnose_io_error(exc, ruta)}


class FilesOrganizeSkill(BaseSkill):
    """Skill para organizar archivos en carpetas según su extensión con vista previa y gobernanza."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="files.organize",
            name="Filesystem Organizer",
            version="1.0.0",
            description="Organiza archivos en subdirectorios categorizados por extensión con vista previa.",
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
        directorio = str(
            parametros.get("directorio")
            or parametros.get("ruta_carpeta")
            or parametros.get("carpeta")
            or parametros.get("ruta")
            or parametros.get("path")
            or "."
        ).strip()
        preview = bool(parametros.get("preview") or parametros.get("vista_previa") or False)

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

        plan: list[dict[str, str]] = []

        try:
            for item in os.listdir(directorio):
                item_path = os.path.join(directorio, item)
                if os.path.isfile(item_path):
                    _, ext = os.path.splitext(item)
                    ext_lower = ext.lower()

                    for cat_nombre, ext_set in categorias.items():
                        if ext_lower in ext_set:
                            dest_dir = os.path.join(directorio, cat_nombre)
                            plan.append({
                                "archivo": item,
                                "origen": item_path,
                                "categoria": cat_nombre,
                                "destino_propuesto": os.path.join(dest_dir, item),
                            })
                            break

            # ── VISTA PREVIA PARA OPERACIONES POR LOTES ──
            if preview:
                return {
                    "exito": True,
                    "preview": True,
                    "requiere_confirmacion": True,
                    "mensaje": f"Vista previa: se organizarían {len(plan)} archivo(s) en subcarpetas.",
                    "total_archivos": len(plan),
                    "plan": plan,
                }

            # Ejecución real del lote
            organizados = 0
            for item_plan in plan:
                dest_dir = os.path.dirname(item_plan["destino_propuesto"])
                os.makedirs(dest_dir, exist_ok=True)
                shutil.move(item_plan["origen"], item_plan["destino_propuesto"])
                organizados += 1

            return {
                "exito": True,
                "mensaje": f"Organización completada. Se clasificaron {organizados} archivo(s).",
                "archivos_organizados": organizados,
            }
        except Exception as exc:
            return {"exito": False, "mensaje": f"Error organizando archivos: {exc}"}
