import logging
import os
import time
from typing import Any

from core.brain import procesar_orden
from core.intent_models import IntentStatus, PendingIntent
from core.intent_validator import IntentValidator
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

# Constantes de control de diálogo y aclaración
MAX_CLARIFICATION_ATTEMPTS: int = 2
CLARIFICATION_TTL_SECONDS: float = 60.0
PALABRAS_CANCELACION: set[str] = {
    "cancelar",
    "cancela",
    "no",
    "salir",
    "exit",
    "quit",
    "olvídalo",
    "olvidalo",
    "dejalo",
    "déjalo",
    "nada",
    "ninguna",
}

# Estado de intención pendiente en memoria (sesión interactiva)
_active_pending_intent: PendingIntent | None = None


def get_pending_intent() -> PendingIntent | None:
    """Obtiene la intención pendiente activa en memoria."""
    global _active_pending_intent
    return _active_pending_intent


def set_pending_intent(pending: PendingIntent | None) -> None:
    """Establece o limpia la intención pendiente activa (útil para pruebas y control de sesión)."""
    global _active_pending_intent
    _active_pending_intent = pending


def clear_pending_intent() -> None:
    """Limpia la intención pendiente activa."""
    global _active_pending_intent
    _active_pending_intent = None


def ejecutar_orden_texto(texto: str, skills: dict[str, Any] | None = None) -> str:
    """
    Orquesta el flujo completo de una orden de texto con soporte de aclaración (Fase 2):
    1. Comprueba si hay una intención pendiente activa o si ha expirado (TTL).
    2. Detecta comandos de cancelación explícita.
    3. Envía el texto (y contexto de aclaración si aplica) al Cerebro (LLM).
    4. Somete el resultado a IntentValidator (validación determinista contra las Skills).
    5. Si faltan datos (INCOMPLETE / AMBIGUOUS), guarda PendingIntent y formula la pregunta aclaratoria.
    6. Si está CLEAR, pasa obligatoriamente por la capa de Seguridad, Políticas y Confirmación.
    7. Ejecuta la Skill autorizada y registra el resultado en Auditoría.
    """
    global _active_pending_intent
    if skills is None:
        skills = SKILLS_DISPONIBLES

    texto_limpio = texto.strip()
    texto_lower = texto_limpio.lower()
    orq_logger.info(f"Orden recibida: '{texto_limpio}'")

    # ── Paso 0: Verificación de TTL de intención pendiente ────────────────────
    if _active_pending_intent is not None:
        if _active_pending_intent.ha_expirado(CLARIFICATION_TTL_SECONDS):
            orq_logger.info(f"Intención pendiente expirada por TTL ({CLARIFICATION_TTL_SECONDS}s). Descartando.")
            _active_pending_intent = None

    # ── Paso 1: Cancelación explícita durante aclaración ──────────────────────
    if _active_pending_intent is not None and texto_lower in PALABRAS_CANCELACION:
        orq_logger.info(f"Aclaración cancelada explícitamente por el usuario ('{texto_limpio}').")
        _active_pending_intent = None
        return "De acuerdo, cancelé la acción."

    # ── Paso 2: Control de límite de intentos (Anti-Loop) ─────────────────────
    contexto_aclaracion: PendingIntent | None = None
    if _active_pending_intent is not None:
        if _active_pending_intent.intentos >= MAX_CLARIFICATION_ATTEMPTS:
            orq_logger.warning(
                f"Límite máximo de aclaraciones superado ({MAX_CLARIFICATION_ATTEMPTS} intentos). Cancelando orden."
            )
            _active_pending_intent = None
            return "No pude determinar la opción solicitada tras dos intentos. Por favor, formula la orden completa de nuevo."
        _active_pending_intent.intentos += 1
        contexto_aclaracion = _active_pending_intent

    # ── Paso 3: Consultar al Cerebro (LLM) ────────────────────────────────────
    decision = procesar_orden(texto_limpio, skills, contexto_aclaracion=contexto_aclaracion)

    if decision.get("error") and not decision.get("skill") and decision.estado == IntentStatus.INVALID:
        orq_logger.warning(f"Error en Cerebro: {decision['error']}")
        _active_pending_intent = None
        return decision.get("respuesta_hablada") or "Tuve un problema al procesar tu orden."

    # ── Paso 4: Validación Determinista con IntentValidator ───────────────────
    validator = IntentValidator(skills)
    val_result = validator.validate(decision, skills)

    # ── Paso 5: Manejo de AMBIGUOUS o INCOMPLETE (Aclaración) ─────────────────
    if val_result.status in (IntentStatus.AMBIGUOUS, IntentStatus.INCOMPLETE):
        intentos_actuales = _active_pending_intent.intentos if _active_pending_intent else 0
        if intentos_actuales >= MAX_CLARIFICATION_ATTEMPTS:
            orq_logger.warning(
                f"Límite máximo de aclaraciones alcanzado ({MAX_CLARIFICATION_ATTEMPTS} intentos). Cancelando orden."
            )
            _active_pending_intent = None
            return "No pude determinar la opción solicitada tras dos intentos. Por favor, formula la orden completa de nuevo."

        pregunta = val_result.clarification_prompt or decision.pregunta_aclaratoria or decision.respuesta_hablada
        _active_pending_intent = PendingIntent(
            skill_nombre=val_result.skill_name or (decision.skill or ""),
            parametros_parciales=val_result.validated_parameters or (decision.parametros or {}),
            parametro_esperado=val_result.missing_parameter or decision.parametro_faltante,
            candidatos_posibles=val_result.candidates or decision.candidatos,
            pregunta_formulada=pregunta or "",
            timestamp=time.time(),
            intentos=intentos_actuales,
            estado_origen=val_result.status,
        )
        orq_logger.info(
            f"Intención {val_result.status.value}: Guardado PendingIntent para '{_active_pending_intent.skill_nombre}'. Pregunta: '{pregunta}'"
        )
        return pregunta

    # Si la orden resultó en otro estado, limpiar cualquier PendingIntent previo
    _active_pending_intent = None

    # ── Paso 6: Manejo de UNSUPPORTED o INVALID ──────────────────────────────
    if val_result.status == IntentStatus.UNSUPPORTED:
        orq_logger.info(f"Intención no soportada: {val_result.reason}")
        return decision.respuesta_hablada or "Todavía no tengo una habilidad disponible para esa acción."

    if val_result.status == IntentStatus.INVALID:
        orq_logger.info(f"Intención inválida: {val_result.reason}")
        return decision.respuesta_hablada or "No pude comprender la orden. Por favor, repítela."

    # ── Paso 7: Estado CLEAR — Respuesta Conversacional pura ─────────────────
    nombre_skill = val_result.skill_name or decision.skill
    parametros = val_result.validated_parameters if val_result.validated_parameters else (decision.parametros or {})
    respuesta_hablada = decision.respuesta_hablada

    if not nombre_skill:
        orq_logger.info("Sin skill detectada — respuesta conversacional.")
        return respuesta_hablada

    # ── Paso 8: Estado CLEAR con Skill — Capa de Seguridad y Políticas ───────
    skill = skills.get(nombre_skill)
    if not skill:
        orq_logger.warning(f"Skill '{nombre_skill}' no encontrada en el registro.")
        return f"Lo entendí, pero no tengo la habilidad '{nombre_skill}' disponible aún."

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

    # ── Paso 9: Ejecutar la Skill Autorizada ──────────────────────────────────
    try:
        resultado = skill.ejecutar(parametros)
    except Exception as e:
        orq_logger.error(f"Excepción al ejecutar '{nombre_skill}': {e}", exc_info=True)
        return f"Ocurrió un error inesperado al ejecutar '{nombre_skill}'."

    # ── Paso 10: Auditoría y Retorno ─────────────────────────────────────────
    exito = resultado.get("exito", False)
    mensaje_skill = resultado.get("mensaje", "")

    orq_logger.info(
        f"Skill '{nombre_skill}' | params={parametros} | exito={exito} | msg={mensaje_skill}"
    )

    if exito:
        return respuesta_hablada or mensaje_skill
    else:
        return mensaje_skill or "La acción no pudo completarse."
