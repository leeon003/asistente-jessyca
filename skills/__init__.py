"""
Módulo de habilidades (skills) del asistente Jessyca.
"""

from skills.apps import AbrirAplicacion, CerrarAplicacion
from skills.archivos import BuscarArchivo

# Registro de skills disponibles en el sistema
SKILLS_DISPONIBLES = {
    "abrir_aplicacion": AbrirAplicacion(),
    "cerrar_aplicacion": CerrarAplicacion(),
    "buscar_archivo": BuscarArchivo(),
}
