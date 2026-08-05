import os
from typing import Dict, Any, List
from skills.base_skill import BaseSkill


class BuscarArchivo(BaseSkill):
    """Busca archivos por nombre dentro de una ruta o directorio especificado."""

    def __init__(self):
        super().__init__(nombre="buscar_archivo", nivel_riesgo=1)

    def ejecutar(self, parametros: Dict[str, Any]) -> Dict[str, Any]:
        nombre_buscado = parametros.get("nombre_archivo") or parametros.get("nombre")
        if not nombre_buscado:
            return {"exito": False, "mensaje": "Debe especificar el nombre del archivo a buscar."}

        ruta_base = parametros.get("ruta") or parametros.get("directorio")
        if not ruta_base or not os.path.exists(str(ruta_base)):
            ruta_base = os.path.expanduser("~")

        coincidencias: List[str] = []
        max_resultados = int(parametros.get("max_resultados", 10))
        nombre_buscado_lower = str(nombre_buscado).lower()

        try:
            for root, _, files in os.walk(ruta_base):
                for f in files:
                    if nombre_buscado_lower in f.lower():
                        coincidencias.append(os.path.join(root, f))
                        if len(coincidencias) >= max_resultados:
                            break
                if len(coincidencias) >= max_resultados:
                    break

            if coincidencias:
                return {
                    "exito": True,
                    "mensaje": f"Se encontraron {len(coincidencias)} archivo(s) coincidentes.",
                    "archivos": coincidencias
                }
            else:
                return {
                    "exito": False,
                    "mensaje": f"No se encontraron archivos que contengan '{nombre_buscado}' en '{ruta_base}'."
                }
        except Exception as e:
            return {
                "exito": False,
                "mensaje": f"Error al buscar archivos en '{ruta_base}': {str(e)}"
            }
