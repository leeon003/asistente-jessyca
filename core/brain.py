import json
import logging
import os
import re
from typing import Any

import requests
from dotenv import load_dotenv

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


def procesar_orden(texto_usuario: str, skills_disponibles: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Envía el texto del usuario al LLM (Ollama local con gemma4:e4b) y parsea la respuesta
    como instrucción estructurada para el orquestador.

    Retorna:
        {
            "respuesta_hablada": str,
            "skill": str | None,
            "parametros": dict | None,
            "error": str | None   <- sólo presente si algo falló
        }
    """
    skills_map = skills_disponibles or {}
    system_prompt = _cargar_system_prompt()
    skills_descripcion = _construir_prompt_skills(skills_map)

    prompt_completo = (
        f"{system_prompt}\n\n"
        f"{skills_descripcion}\n\n"
        f"ORDEN DEL USUARIO: {texto_usuario}\n\n"
        "Responde ÚNICAMENTE con el JSON solicitado, sin texto extra."
    )

    ultimo_error = None

    for intento in range(1, 3):  # hasta 2 intentos
        try:
            texto_respuesta = _llamar_ollama(prompt_completo)
        except requests.exceptions.ConnectionError:
            return {
                "respuesta_hablada": "No puedo conectarme al servicio de inteligencia local. ¿Está Ollama corriendo?",
                "skill": None,
                "parametros": None,
                "error": f"Ollama no disponible en {OLLAMA_HOST}. Verifica que el servicio esté activo."
            }
        except requests.exceptions.Timeout:
            return {
                "respuesta_hablada": "El modelo tardó demasiado en responder. Intenta de nuevo.",
                "skill": None,
                "parametros": None,
                "error": "Timeout al conectar con Ollama."
            }
        except Exception as e:
            return {
                "respuesta_hablada": "Ocurrió un error inesperado al consultar el modelo.",
                "skill": None,
                "parametros": None,
                "error": str(e)
            }

        parsed = _extraer_json(texto_respuesta)
        if parsed is not None:
            # Validar que la skill exista en el registro si se especificaron skills disponibles
            skill_pedida = parsed.get("skill")
            if skill_pedida and skills_map and skill_pedida not in skills_map:
                logger.warning(f"LLM sugirió skill desconocida: '{skill_pedida}'. Se ignora.")
                parsed["skill"] = None
                parsed["parametros"] = None
                parsed.setdefault("respuesta_hablada", "Entendí tu orden pero no tengo esa habilidad disponible aún.")

            return {
                "respuesta_hablada": parsed.get("respuesta_hablada", ""),
                "skill": parsed.get("skill"),
                "parametros": parsed.get("parametros"),
                "error": None
            }

        logger.warning(f"Intento {intento}: JSON mal formado. Texto recibido: {texto_respuesta[:200]}")
        ultimo_error = f"Respuesta no parseable después de {intento} intento(s): {texto_respuesta[:300]}"

    return {
        "respuesta_hablada": "No pude interpretar la respuesta del modelo. Por favor, repite tu orden.",
        "skill": None,
        "parametros": None,
        "error": ultimo_error
    }
