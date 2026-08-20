import json
import logging
import os
import re
from typing import Any

import requests
from dotenv import load_dotenv

from core.intent_models import IntentStatus, ParsedIntent, PendingIntent

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")

SYSTEM_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "system_prompt.txt"
)

logger = logging.getLogger("brain")


def _cargar_system_prompt() -> str:
    try:
        with open(SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "Eres Jessyca, un asistente de voz y texto local para Windows."


def _construir_prompt_skills(skills_disponibles: dict[str, Any] | None) -> str:
    if not skills_disponibles:
        return "No hay habilidades registradas actualmente."
    lineas = ["HABILIDADES DISPONIBLES (usa el campo 'skill' con exactamente este nombre):"]
    for nombre, skill in skills_disponibles.items():
        desc = skill.descripcion() if hasattr(skill, "descripcion") else str(skill)
        lineas.append(f"- \"{nombre}\": {desc}")
    return "\n".join(lineas)


def _extraer_json(texto: str) -> dict[str, Any] | None:
    """Intenta extraer un JSON válido del texto, incluso si viene con markdown o texto adicional."""
    if not texto:
        return None
    texto = texto.strip()
    # 1. Intento directo
    try:
        data = json.loads(texto)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 2. Buscar bloques de código markdown ```json ... ```
    md_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', texto, re.DOTALL)
    if md_match:
        try:
            data = json.loads(md_match.group(1))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # 3. Buscar el bloque JSON más externo con regex (entre la primera '{' y la última '}')
    match = re.search(r'\{.*\}', texto, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None


def _llamar_ollama(prompt_completo: str) -> str:
    """Realiza la llamada HTTP a Ollama y retorna el texto de la respuesta."""
    url = f"{OLLAMA_HOST}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt_completo,
        "stream": False,
        "options": {"temperature": 0.1}
    }
    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
    return str(response.json().get("response", ""))


def procesar_orden(
    texto_usuario: str,
    skills_disponibles: dict[str, Any] | None = None,
    contexto_aclaracion: PendingIntent | None = None,
) -> ParsedIntent:
    """
    Envía el texto del usuario al LLM (Ollama local con gemma4:e4b) y parsea la respuesta
    como instrucción estructurada y tipada (ParsedIntent) para el validador y orquestador.
    """
    skills_map = skills_disponibles or {}
    system_prompt = _cargar_system_prompt()
    skills_descripcion = _construir_prompt_skills(skills_map)

    if contexto_aclaracion is not None:
        prompt_completo = (
            f"{system_prompt}\n\n"
            f"{skills_descripcion}\n\n"
            f"CONTEXTO DE ACLARACIÓN PENDIENTE:\n"
            f"- Habilidad en curso: {contexto_aclaracion.skill_nombre}\n"
            f"- Pregunta formulada al usuario: {contexto_aclaracion.pregunta_formulada}\n"
            f"- Parámetro esperado: {contexto_aclaracion.parametro_esperado}\n"
            f"- Parámetros acumulados: {contexto_aclaracion.parametros_parciales}\n\n"
            f"RESPUESTA DE ACLARACIÓN DEL USUARIO: {texto_usuario}\n\n"
            "Integra la respuesta del usuario para completar la intención. Responde ÚNICAMENTE con el JSON solicitado."
        )
    else:
        prompt_completo = (
            f"{system_prompt}\n\n"
            f"{skills_descripcion}\n\n"
            f"ORDEN DEL USUARIO: {texto_usuario}\n\n"
            "Responde ÚNICAMENTE con el JSON solicitado, sin texto extra."
        )

    ultimo_error: str | None = None

    for intento in range(1, 3):  # hasta 2 intentos
        try:
            texto_respuesta = _llamar_ollama(prompt_completo)
        except requests.exceptions.ConnectionError:
            return ParsedIntent(
                estado=IntentStatus.INVALID,
                respuesta_hablada="No puedo conectarme al servicio de inteligencia local. ¿Está Ollama corriendo?",
                error=f"Ollama no disponible en {OLLAMA_HOST}. Verifica que el servicio esté activo.",
            )
        except requests.exceptions.Timeout:
            return ParsedIntent(
                estado=IntentStatus.INVALID,
                respuesta_hablada="El modelo tardó demasiado en responder. Intenta de nuevo.",
                error="Timeout al conectar con Ollama.",
            )
        except Exception as e:
            return ParsedIntent(
                estado=IntentStatus.INVALID,
                respuesta_hablada="Ocurrió un error inesperado al consultar el modelo.",
                error=str(e),
            )

        parsed = _extraer_json(texto_respuesta)
        if parsed is not None:
            # Interpretar y mapear el estado devuelto
            estado_raw = str(parsed.get("estado", "CLEAR")).upper().strip()
            try:
                estado = IntentStatus(estado_raw)
            except ValueError:
                estado = IntentStatus.CLEAR

            skill_pedida = parsed.get("skill")
            parametros = parsed.get("parametros") or {}
            respuesta_hablada = str(parsed.get("respuesta_hablada", ""))
            pregunta_aclaratoria = parsed.get("pregunta_aclaratoria")
            parametro_faltante = parsed.get("parametro_faltante")
            candidatos = parsed.get("candidatos") or []

            # Si el LLM sugirió una skill no registrada en el catálogo
            if skill_pedida and skills_map and skill_pedida not in skills_map:
                logger.warning(f"LLM sugirió skill desconocida: '{skill_pedida}'. Se clasifica como UNSUPPORTED.")
                estado = IntentStatus.UNSUPPORTED
                skill_pedida = None
                parametros = None
                if not respuesta_hablada:
                    respuesta_hablada = "Entendí tu orden pero no tengo esa habilidad disponible aún."

            return ParsedIntent(
                estado=estado,
                respuesta_hablada=respuesta_hablada,
                skill=skill_pedida,
                parametros=parametros if isinstance(parametros, dict) else {},
                pregunta_aclaratoria=str(pregunta_aclaratoria) if pregunta_aclaratoria else None,
                parametro_faltante=str(parametro_faltante) if parametro_faltante else None,
                candidatos=list(candidatos) if isinstance(candidatos, list) else [],
                error=None,
            )

        logger.warning(f"Intento {intento}: JSON mal formado. Texto recibido: {texto_respuesta[:200]}")
        ultimo_error = f"Respuesta no parseable después de {intento} intento(s): {texto_respuesta[:300]}"

    return ParsedIntent(
        estado=IntentStatus.INVALID,
        respuesta_hablada="No pude interpretar la respuesta del modelo. Por favor, repite tu orden.",
        error=ultimo_error,
    )
