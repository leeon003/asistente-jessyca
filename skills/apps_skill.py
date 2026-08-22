"""Skill de gestión de aplicaciones de Windows (apps_skill.py - Fase 28.7).

Permite abrir, inspeccionar y cerrar aplicaciones de escritorio de forma gobernada.
No accede a APIs privilegiadas directamente; se ejecuta bajo SecurityPipeline.
"""

from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from typing import Any

import psutil
import yaml

from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillManifest,
)

CONFIG_APPS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "apps.yaml",
)


def _normalizar(texto: str) -> str:
    """Normaliza cadenas para comparar nombres de aplicaciones tolerando variaciones."""
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[_\-]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _buscar_en_mapeo(nombre_input: str, mapeo: dict[str, str]) -> str | None:
    input_norm = _normalizar(nombre_input)
    mapeo_norm = {_normalizar(k): v for k, v in mapeo.items()}

    if input_norm in mapeo_norm:
        return mapeo_norm[input_norm]

    for clave_norm, ejecutable in mapeo_norm.items():
        if input_norm in clave_norm or clave_norm in input_norm:
            return ejecutable

    return None


class WindowsAppsSkill(BaseSkill):
    """Skill de producción para control de aplicaciones de Windows."""

    def __init__(self, ruta_config: str = CONFIG_APPS_PATH) -> None:
        self.ruta_config = ruta_config
        manifest = SkillManifest(
            id="windows.apps",
            name="Windows Apps Manager",
            version="1.0.0",
            description="Controla la apertura, inspección y cierre de aplicaciones en Windows (ej: Bloc de notas, Calculadora, Explorer).",
            author="Jessyca Core",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "apps.inspect"),
            required_agents=("DesktopAgent", "SystemAgent"),
            required_models=("llama3.2:latest",),
            permissions=("apps.open", "apps.close", "apps.inspect"),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="windows.apps",
            name="Windows Apps Manager",
            version="1.0.0",
            description="Controla la apertura, inspección y cierre de aplicaciones en Windows.",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "apps.inspect"),
            required_permissions=("apps.open", "apps.close", "apps.inspect"),
            risk_level=SecurityLevel.SAFE,
            tags=("apps", "windows", "abrir", "cerrar", "programa", "aplicacion", "bloc", "notas"),
            manifest=manifest,
        )
        super().__init__(nombre="windows.apps", nivel_riesgo=1, definition=def_obj)

    def _cargar_mapeo(self) -> dict[str, str]:
        # Fallback predeterminado si el archivo config/apps.yaml no existe
        defaults = {
            "bloc de notas": "notepad.exe",
            "notepad": "notepad.exe",
            "calculadora": "calc.exe",
            "explorer": "explorer.exe",
            "cmd": "cmd.exe",
            "paint": "mspaint.exe",
            "edge": "msedge.exe",
        }
        if not os.path.exists(self.ruta_config):
            return defaults
        try:
            with open(self.ruta_config, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "applications" in data and isinstance(data["applications"], dict):
                    merged = dict(defaults)
                    merged.update({str(k): str(v) for k, v in data["applications"].items()})
                    return merged
        except Exception:
            pass
        return defaults

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        accion = str(parametros.get("accion") or parametros.get("action") or "abrir").lower()
        nombre_app = (
            parametros.get("nombre_app")
            or parametros.get("app")
            or parametros.get("nombre")
            or parametros.get("query")
        )

        if not nombre_app:
            return {"exito": False, "mensaje": "Debe especificar el nombre de la aplicación."}

        mapeo = self._cargar_mapeo()
        comando = _buscar_en_mapeo(str(nombre_app), mapeo) or f"{nombre_app}.exe"

        # 1. ACCIÓN: ABRIR
        if accion in ("abrir", "open", "launch"):
            try:
                subprocess.Popen(comando, shell=True)
                from core.execution.execution_verifier import get_execution_verifier
                evidence = get_execution_verifier().verify_execution("open_application", comando, {"nombre_app": nombre_app}, timeout_seconds=2.0)
                if evidence.is_verified:
                    return {
                        "exito": True,
                        "mensaje": f"Aplicación '{nombre_app}' lanzada y verificada con éxito.",
                        "comando": comando,
                        "evidence": evidence.to_dict(),
                    }
                else:
                    return {
                        "exito": False,
                        "mensaje": f"Se envió el comando para abrir '{nombre_app}', pero Windows no confirmó que el proceso esté en ejecución.",
                        "comando": comando,
                        "evidence": evidence.to_dict(),
                        "error_code": "VERIFICATION_FAILED",
                    }
            except Exception as e:
                return {"exito": False, "mensaje": f"Error al abrir '{nombre_app}': {e}"}

        # 2. ACCIÓN: CERRAR
        elif accion in ("cerrar", "close", "stop"):
            proc_name = comando.lower()
            terminados = 0
            targets_to_check = [proc_name]
            if "notepad" in proc_name:
                targets_to_check.extend(["notepad.exe", "notepad"])
            elif "calc" in proc_name:
                targets_to_check.extend(["calculatorapp.exe", "calc.exe", "calculator.exe"])

            procs_to_wait = []
            for proc in psutil.process_iter(["name"]):
                try:
                    pname = (proc.info.get("name") or "").lower()
                    if any(t == pname or t in pname for t in targets_to_check):
                        proc.terminate()
                        procs_to_wait.append(proc)
                        terminados += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if procs_to_wait:
                _gone, alive = psutil.wait_procs(procs_to_wait, timeout=1.0)
                for p in alive:
                    try:
                        p.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            from core.execution.execution_verifier import get_execution_verifier
            evidence = get_execution_verifier().verify_execution("close_application", comando, {"nombre_app": nombre_app}, timeout_seconds=2.0)

            if terminados > 0 and evidence.is_verified:
                return {
                    "exito": True,
                    "mensaje": f"Se cerraron {terminados} proceso(s) de '{nombre_app}'.",
                    "terminados": terminados,
                    "evidence": evidence.to_dict(),
                }
            elif terminados == 0:
                return {
                    "exito": False,
                    "mensaje": f"No se encontraron procesos activos de '{nombre_app}' para cerrar.",
                    "terminados": 0,
                    "evidence": evidence.to_dict(),
                }
            else:
                return {
                    "exito": False,
                    "mensaje": f"Se intentó cerrar '{nombre_app}', pero el proceso sigue activo.",
                    "terminados": terminados,
                    "evidence": evidence.to_dict(),
                    "error_code": "VERIFICATION_FAILED",
                }

        # 3. ACCIÓN: INSPECCIONAR
        elif accion in ("inspeccionar", "inspect", "status"):
            proc_name = comando.lower()
            activos = []
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if proc.info["name"] and proc.info["name"].lower() == proc_name:
                        activos.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            return {
                "exito": True,
                "mensaje": f"Se encontraron {len(activos)} instancia(s) activa(s) de '{nombre_app}'.",
                "instancias": activos,
            }

        return {"exito": False, "mensaje": f"Acción '{accion}' no reconocida."}
