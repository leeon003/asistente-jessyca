import logging
import os
from typing import Any

from core.brain import procesar_orden
from core.seguridad import confirmar_con_usuario, registrar_auditoria, requiere_confirmacion
from skills import SKILLS_DISPONIBLES

# Logger general del orquestador
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

orq_logger = logging.getLogger("orquestador")
orq_logger.setLevel(logging.INFO)
if not orq_logger.handlers:
    _handler = logging.FileHandler(os.path.join(LOG_DIR, "jessyca.log"), encoding="utf-8")
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    orq_logger.addHandler(_handler)


def ejecutar_orden_texto(texto: str, skills: dict[str, Any] | None = None) -> str:
    """
    Orquesta el flujo completo de una orden de texto:
    1. Envía el texto al Cerebro (LLM).
    2. Decide si se debe ejecutar una skill.
    3. Aplica la política de seguridad (confirmación si aplica).
    4. Ejecuta la skill y registra el resultado en auditoría.
    5. Retorna la respuesta hablada.

    :param texto: Orden del usuario en lenguaje natural.
    :param skills: Registro de skills disponibles (por defecto usa SKILLS_DISPONIBLES global).
    :return: Texto de respuesta para presentar al usuario.
    """
    if skills is None:
        skills = SKILLS_DISPONIBLES

    orq_logger.info(f"Orden recibida: '{texto}'")

    # ── Paso 1: Consultar al Cerebro ──────────────────────────────────────────
    decision = procesar_orden(texto, skills)

    if decision.get("error") and not decision.get("skill"):
        # Error en el Cerebro (Ollama caído, JSON roto, etc.)
        orq_logger.warning(f"Error en Cerebro: {decision['error']}")
        return decision.get("respuesta_hablada") or "Tuve un problema al procesar tu orden."

    respuesta_hablada = decision.get("respuesta_hablada", "")
    nombre_skill = decision.get("skill")
    parametros = decision.get("parametros") or {}

    # ── Paso 2: Sin skill → respuesta conversacional ──────────────────────────
    if not nombre_skill:
        orq_logger.info("Sin skill detectada — respuesta conversacional.")
        return respuesta_hablada

    # ── Paso 3: Buscar la skill en el registro ────────────────────────────────
    skill = skills.get(nombre_skill)
    if not skill:
        orq_logger.warning(f"Skill '{nombre_skill}' no encontrada en el registro.")
        return f"Lo entendí, pero no tengo la habilidad '{nombre_skill}' disponible aún."

    # ── Paso 4: Política de seguridad ─────────────────────────────────────────
    if requiere_confirmacion(skill):
        mensaje_confirmacion = (
            f"Jessyca va a ejecutar '{nombre_skill}'"
            + (f" con {parametros}" if parametros else "")
            + ". ¿Confirmas?"
        )
        print(f"\n  ⚠  {mensaje_confirmacion}")
        confirmado = confirmar_con_usuario("¿Proceder?")
        registrar_auditoria(nombre_skill, parametros, confirmado, skill.nivel_riesgo)

        if not confirmado:
            orq_logger.info(f"Skill '{nombre_skill}' cancelada por el usuario.")
            return "De acuerdo, cancelé la acción."

    # ── Paso 5: Ejecutar la skill ─────────────────────────────────────────────
    try:
        resultado = skill.ejecutar(parametros)
    except Exception as e:
        orq_logger.error(f"Excepción al ejecutar '{nombre_skill}': {e}", exc_info=True)
        return f"Ocurrió un error inesperado al ejecutar '{nombre_skill}'."

    # ── Paso 6: Auditoría y respuesta ─────────────────────────────────────────
    exito = resultado.get("exito", False)
    mensaje_skill = resultado.get("mensaje", "")

    orq_logger.info(
        f"Skill '{nombre_skill}' | params={parametros} | exito={exito} | msg={mensaje_skill}"
    )

    if exito:
        return respuesta_hablada or mensaje_skill
    else:
        return mensaje_skill or "La acción no pudo completarse."
