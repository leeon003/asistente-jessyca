import logging
import os
import threading
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
DEFAULT_SESSION_ID: str = "default_session"

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

# ─────────────────────────────────────────────────────────────────────────────
# NOTA DE ARQUITECTURA (Fase 10 - Consolidación Gradual):
# core/orquestador.py es un orquestador sincrónico legado diseñado para la
# interacción en consola local (CLI turno a turno con input() interactivo).
# Para flujos HTTP multisesión concurrentes (Mobile API, WebUI Bridge) o flujo
# de Voz principal, la autoridad de despacho unificada y multisesión es
# JessycaLocalAgent (core/local_agent/local_agent.py).
#
# Para evitar interferencias entre sesiones en pruebas o accesos concurrentes,
# el estado de aclaración pendiente se almacena aislado por session_id con TTL
# y sincronización threading.RLock().
# ─────────────────────────────────────────────────────────────────────────────

_session_pending_intents: dict[str, PendingIntent] = {}
_session_lock: threading.RLock = threading.RLock()

# Variable global mantenida únicamente por compatibilidad hacia atrás con código legacy
_active_pending_intent: PendingIntent | None = None


def get_pending_intent(session_id: str = DEFAULT_SESSION_ID) -> PendingIntent | None:
    """Obtiene la intención pendiente activa en memoria para la sesión especificada."""
    global _active_pending_intent
    with _session_lock:
        intent = _session_pending_intents.get(session_id)
        if intent is not None and intent.ha_expirado(CLARIFICATION_TTL_SECONDS):
            orq_logger.info(
                f"[Sesión {session_id}] Intención pendiente expirada por TTL ({CLARIFICATION_TTL_SECONDS}s). Descartando."
            )
            _session_pending_intents.pop(session_id, None)
            if session_id == DEFAULT_SESSION_ID:
                _active_pending_intent = None
            return None
        return intent


def set_pending_intent(pending: PendingIntent | None, session_id: str = DEFAULT_SESSION_ID) -> None:
    """Establece o limpia la intención pendiente activa para la sesión especificada."""
    global _active_pending_intent
    with _session_lock:
        if pending is None:
            _session_pending_intents.pop(session_id, None)
        else:
            _session_pending_intents[session_id] = pending
        if session_id == DEFAULT_SESSION_ID:
            _active_pending_intent = pending


def clear_pending_intent(session_id: str = DEFAULT_SESSION_ID) -> None:
    """Limpia la intención pendiente activa para la sesión especificada."""
    global _active_pending_intent
    with _session_lock:
        _session_pending_intents.pop(session_id, None)
        if session_id == DEFAULT_SESSION_ID:
            _active_pending_intent = None


def clear_all_pending_intents() -> None:
    """Limpia todas las intenciones pendientes de todas las sesiones."""
    global _active_pending_intent
    with _session_lock:
        _session_pending_intents.clear()
        _active_pending_intent = None


def ejecutar_orden_texto(
    texto: str,
    skills: dict[str, Any] | None = None,
    session_id: str = DEFAULT_SESSION_ID,
) -> str:
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
    orq_logger.info(f"[Sesión {session_id}] Orden recibida: '{texto_limpio}'")

    contexto_aclaracion: PendingIntent | None = None
    with _session_lock:
        active_pending = _session_pending_intents.get(session_id)

        # ── Paso 0: Verificación de TTL de intención pendiente ────────────────────
        if active_pending is not None and active_pending.ha_expirado(CLARIFICATION_TTL_SECONDS):
            orq_logger.info(
                f"[Sesión {session_id}] Intención pendiente expirada por TTL ({CLARIFICATION_TTL_SECONDS}s). Descartando."
            )
            _session_pending_intents.pop(session_id, None)
            if session_id == DEFAULT_SESSION_ID:
                _active_pending_intent = None
            active_pending = None

        # ── Paso 1: Cancelación explícita durante aclaración ──────────────────────
        if active_pending is not None and texto_lower in PALABRAS_CANCELACION:
            orq_logger.info(f"[Sesión {session_id}] Aclaración cancelada explícitamente por el usuario ('{texto_limpio}').")
            _session_pending_intents.pop(session_id, None)
            if session_id == DEFAULT_SESSION_ID:
                _active_pending_intent = None
            return "De acuerdo, cancelé la acción."

        # ── Paso 2: Control de límite de intentos (Anti-Loop) ─────────────────────
        if active_pending is not None:
            if active_pending.intentos >= MAX_CLARIFICATION_ATTEMPTS:
                orq_logger.warning(
                    f"[Sesión {session_id}] Límite máximo de aclaraciones superado ({MAX_CLARIFICATION_ATTEMPTS} intentos). Cancelando orden."
                )
                _session_pending_intents.pop(session_id, None)
                if session_id == DEFAULT_SESSION_ID:
                    _active_pending_intent = None
                return "No pude determinar la opción solicitada tras dos intentos. Por favor, formula la orden completa de nuevo."
            active_pending.intentos += 1
            contexto_aclaracion = active_pending

    # ── Paso 3: Consultar al Cerebro (LLM) ────────────────────────────────────
    decision = procesar_orden(texto_limpio, skills, contexto_aclaracion=contexto_aclaracion)

    with _session_lock:
        if decision.get("error") and not decision.get("skill") and decision.estado == IntentStatus.INVALID:
            orq_logger.warning(f"[Sesión {session_id}] Error en Cerebro: {decision['error']}")
            _session_pending_intents.pop(session_id, None)
            if session_id == DEFAULT_SESSION_ID:
                _active_pending_intent = None
            return decision.get("respuesta_hablada") or "Tuve un problema al procesar tu orden."

        # ── Paso 4: Validación Determinista con IntentValidator ───────────────────
        validator = IntentValidator(skills)
        val_result = validator.validate(decision, skills)

        # ── Paso 5: Manejo de AMBIGUOUS o INCOMPLETE (Aclaración) ─────────────────
        if val_result.status in (IntentStatus.AMBIGUOUS, IntentStatus.INCOMPLETE):
            current_pending = _session_pending_intents.get(session_id)
            intentos_actuales = current_pending.intentos if current_pending else 0
            if intentos_actuales >= MAX_CLARIFICATION_ATTEMPTS:
                orq_logger.warning(
                    f"[Sesión {session_id}] Límite máximo de aclaraciones alcanzado ({MAX_CLARIFICATION_ATTEMPTS} intentos). Cancelando orden."
                )
                _session_pending_intents.pop(session_id, None)
                if session_id == DEFAULT_SESSION_ID:
                    _active_pending_intent = None
                return "No pude determinar la opción solicitada tras dos intentos. Por favor, formula la orden completa de nuevo."

            pregunta = val_result.clarification_prompt or decision.pregunta_aclaratoria or decision.respuesta_hablada
            new_pending = PendingIntent(
                skill_nombre=val_result.skill_name or (decision.skill or ""),
                parametros_parciales=val_result.validated_parameters or (decision.parametros or {}),
                parametro_esperado=val_result.missing_parameter or decision.parametro_faltante,
                candidatos_posibles=val_result.candidates or decision.candidatos,
                pregunta_formulada=pregunta or "",
                timestamp=time.time(),
                intentos=intentos_actuales,
                estado_origen=val_result.status,
            )
            _session_pending_intents[session_id] = new_pending
            if session_id == DEFAULT_SESSION_ID:
                _active_pending_intent = new_pending
            orq_logger.info(
                f"[Sesión {session_id}] Intención {val_result.status.value}: Guardado PendingIntent para '{new_pending.skill_nombre}'. Pregunta: '{pregunta}'"
            )
            return pregunta

        # Si la orden resultó en otro estado, limpiar cualquier PendingIntent previo de esta sesión
        _session_pending_intents.pop(session_id, None)
        if session_id == DEFAULT_SESSION_ID:
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
