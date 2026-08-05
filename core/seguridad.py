import os
import logging
from typing import Dict, Any
from skills.base_skill import BaseSkill

# Configuración del logger de auditoría
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "auditoria.log")

auditoria_logger = logging.getLogger("auditoria")
auditoria_logger.setLevel(logging.INFO)

if not auditoria_logger.handlers:
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    auditoria_logger.addHandler(handler)


def requiere_confirmacion(skill: BaseSkill) -> bool:
    """
    Determina si una skill requiere confirmación del usuario según su nivel de riesgo.

    Niveles de riesgo:
    1: Bajo (Auto-ejecuta) -> False
    2: Medio (Confirma una vez) -> True
    3: Alto (Siempre confirma explícitamente) -> True
    """
    return skill.nivel_riesgo >= 2


def confirmar_con_usuario(mensaje: str) -> bool:
    """
    Pide confirmación al usuario por teclado (CLI).
    Retorna True si el usuario responde afirmativamente, False en caso contrario.
    """
    respuesta = input(f"{mensaje} (s/n): ").strip().lower()
    return respuesta in ("s", "sí", "si", "y", "yes")


def registrar_auditoria(skill_nombre: str, parametros: Dict[str, Any], confirmado: bool, nivel_riesgo: int) -> None:
    """
    Registra en logs/auditoria.log las acciones intentadas para skills de nivel de riesgo 2 o 3.
    """
    if nivel_riesgo >= 2:
        estado = "CONFIRMADO" if confirmado else "CANCELADO"
        auditoria_logger.info(
            f"Skill: {skill_nombre} | Riesgo: {nivel_riesgo} | Parámetros: {parametros} | Estado: {estado}"
        )
