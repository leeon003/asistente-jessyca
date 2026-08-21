import os
import re
import subprocess
import unicodedata
from typing import Any

import psutil
import yaml

from skills.base_skill import BaseSkill

CONFIG_APPS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "apps.yaml"
)


def _normalizar(texto: str) -> str:
    """Normalización robusta para comparar nombres de apps tolerando variaciones del LLM."""
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[_\-]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _buscar_en_mapeo(nombre_input: str, mapeo: dict[str, str]) -> str | None:
    input_norm = _normalizar(nombre_input)
    mapeo_norm = {_normalizar(k): v for k, v in mapeo.items()}

    # 1. Exacto
    if input_norm in mapeo_norm:
        return mapeo_norm[input_norm]

    # 2. Substring bidireccional
    for clave_norm, ejecutable in mapeo_norm.items():
        if input_norm in clave_norm or clave_norm in input_norm:
            return ejecutable

    return None


class AbrirAplicacion(BaseSkill):
    """Abre una aplicación registrada en el mapeo de aplicaciones por su nombre coloquial."""

    def __init__(self, ruta_config: str = CONFIG_APPS_PATH) -> None:
        super().__init__(nombre="abrir_aplicacion", nivel_riesgo=1)
        self.ruta_config = ruta_config

    def _cargar_mapeo(self) -> dict[str, str]:
        if not os.path.exists(self.ruta_config):
            return {}
        try:
            with open(self.ruta_config, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "applications" in data and isinstance(data["applications"], dict):
                    return {str(k): str(v) for k, v in data["applications"].items()}
        except Exception:
            pass
        return {}

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        nombre_app = (
            parametros.get("nombre_app")
            or parametros.get("app")
            or parametros.get("nombre")
        )
        if not nombre_app:
            return {"exito": False, "mensaje": "Debe especificar el nombre de la aplicación a abrir."}

        mapeo = self._cargar_mapeo()
        comando = _buscar_en_mapeo(str(nombre_app), mapeo)

        if not comando:
            return {
                "exito": False,
                "mensaje": f"La aplicación '{nombre_app}' no está registrada en el mapeo de aplicaciones."
            }

        try:
            subprocess.Popen(comando, shell=True)
            return {
                "exito": True,
                "mensaje": f"Aplicación '{nombre_app}' lanzada con éxito ({comando})."
            }
        except Exception as e:
            return {
                "exito": False,
                "mensaje": f"Error al intentar abrir la aplicación '{nombre_app}': {str(e)}"
            }


class CerrarAplicacion(BaseSkill):
    """Cierra las instancias activas de un proceso por su nombre."""

    def __init__(self) -> None:
        super().__init__(nombre="cerrar_aplicacion", nivel_riesgo=2)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        nombre_app = (
            parametros.get("nombre_proceso")
            or parametros.get("nombre_app")
            or parametros.get("app")
            or parametros.get("nombre")
        )
        if not nombre_app:
            return {"exito": False, "mensaje": "Debe especificar el nombre del proceso o aplicación a cerrar."}

        target = _normalizar(str(nombre_app))
        target_exe = target if target.endswith(".exe") else f"{target}.exe"

        procesos_cerrados = 0

        for proc in psutil.process_iter(['name']):
            try:
                proc_name = _normalizar(proc.info.get('name') or '')
                if proc_name == target or proc_name == target_exe:
                    proc.terminate()
                    procesos_cerrados += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if procesos_cerrados > 0:
            return {
                "exito": True,
                "mensaje": f"Se cerraron {procesos_cerrados} instancia(s) de '{nombre_app}'."
            }
        else:
            return {
                "exito": False,
                "mensaje": f"No se encontró ningún proceso activo con el nombre '{nombre_app}'."
            }
