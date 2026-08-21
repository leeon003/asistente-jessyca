"""Arquitectura de Tool Calling robusta y desacoplada (tool_calling.py - Fase 5: Robust Tool Calling).

Evoluciona la interpretación desde Prompt -> JSON -> Regex hacia una arquitectura formal de Tool Calling,
manteniendo total retrocompatibilidad con Structured JSON y garantizando que Tool Calling NO equivale a autorización.

PIPELINE DE EJECUCIÓN SEGURO:
LLM
 ↓
ToolCall
 ↓
Schema / ToolCallValidator
 ↓
IntentValidator
 ↓
Security (RiskEngine -> PermissionManager -> ConfirmationManager -> ActionGuard -> AuditLogger)
 ↓
Execution
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from core.intent_models import IntentStatus, ParsedIntent
from core.logger import get_logger

logger = get_logger("jessyca.llm.tool_calling")


@dataclass(frozen=True)
class ToolCall:
    """Representación formal, inmutable y tipada de una llamada a herramienta generada por el LLM."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_call: dict[str, Any] | str | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Serializa la llamada a herramienta a un diccionario estructurado."""
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ToolCallValidationVerdict:
    """Veredicto determinista resultante de la validación de una ToolCall."""

    is_valid: bool
    tool_name: str
    sanitized_arguments: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    requires_confirmation: bool = False


class ToolCallParser:
    """Parser multiformato tolerante a fallos para extraer llamadas a herramientas desde salidas LLM."""

    @classmethod
    def parse(cls, text_or_data: str | dict[str, Any] | Any) -> ToolCall | None:
        """Intenta parsear una ToolCall desde diversos formatos (Ollama/OpenAI tools, Structured JSON, Markdown)."""
        if not text_or_data:
            return None

        # 1. Si ya es un diccionario estructurado
        if isinstance(text_or_data, dict):
            return cls._parse_from_dict(text_or_data)

        # 2. Si es una cadena de texto
        if isinstance(text_or_data, str):
            clean_str = text_or_data.strip()
            if not clean_str:
                return None

            # 2.1 Intentar parsing directo de JSON
            try:
                data = json.loads(clean_str)
                if isinstance(data, dict):
                    return cls._parse_from_dict(data)
            except json.JSONDecodeError:
                pass

            # 2.2 Bloques XML-like <tool_call>...</tool_call>
            xml_match = re.search(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', clean_str, re.DOTALL)
            if xml_match:
                try:
                    data = json.loads(xml_match.group(1))
                    if isinstance(data, dict):
                        return cls._parse_from_dict(data)
                except json.JSONDecodeError:
                    pass

            # 2.3 Bloques Markdown ```json ... ```
            md_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', clean_str, re.DOTALL)
            if md_match:
                try:
                    data = json.loads(md_match.group(1))
                    if isinstance(data, dict):
                        return cls._parse_from_dict(data)
                except json.JSONDecodeError:
                    pass

            # 2.4 Regex de objeto JSON más externo
            match = re.search(r'\{.*\}', clean_str, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                    if isinstance(data, dict):
                        return cls._parse_from_dict(data)
                except json.JSONDecodeError:
                    pass

        return None

    @classmethod
    def _parse_from_dict(cls, data: dict[str, Any]) -> ToolCall | None:
        """Extrae los campos de ToolCall desde un diccionario con diferentes convenciones de nombres."""
        call_id = str(data.get("id") or data.get("call_id") or f"call-{uuid.uuid4().hex[:8]}")

        # Caso A: Convención OpenAI / Ollama: {"function": {"name": "...", "arguments": ...}}
        if "function" in data and isinstance(data["function"], dict):
            fn = data["function"]
            name = fn.get("name")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if name:
                return ToolCall(
                    call_id=call_id,
                    tool_name=str(name).strip(),
                    arguments=args if isinstance(args, dict) else {},
                    raw_call=data,
                )

        # Caso B: Convención JESSYCA Structured Intent: {"skill": "...", "parametros": {...}}
        if "skill" in data and data["skill"]:
            name = str(data["skill"]).strip()
            args = data.get("parametros") or {}
            return ToolCall(
                call_id=call_id,
                tool_name=name,
                arguments=args if isinstance(args, dict) else {},
                raw_call=data,
            )

        # Caso C: Convención genérica: {"name": "...", "parameters": {...}} o {"tool": "...", "arguments": {...}}
        name = data.get("name") or data.get("tool") or data.get("action")
        if name and isinstance(name, str):
            args = data.get("parameters") or data.get("arguments") or data.get("params") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            return ToolCall(
                call_id=call_id,
                tool_name=name.strip(),
                arguments=args if isinstance(args, dict) else {},
                raw_call=data,
            )

        return None


class ToolCallValidator:
    """Validador determinista de esquema y argumentos para llamadas a herramientas."""

    def __init__(self, catalog: Mapping[str, Any] | None = None) -> None:
        self.catalog = catalog or {}

    def validate(
        self,
        tool_call: ToolCall,
        catalog: Mapping[str, Any] | None = None,
    ) -> ToolCallValidationVerdict:
        """Valida determinísticamente la llamada contra el catálogo de herramientas y sanitiza argumentos."""
        active_catalog = catalog if catalog is not None else self.catalog

        # 1. Validar nombre de la herramienta
        if not tool_call.tool_name:
            return ToolCallValidationVerdict(
                is_valid=False,
                tool_name="",
                error="El nombre de la herramienta está vacío o ausente.",
            )

        tool_name = tool_call.tool_name.strip()

        # 2. Validar existencia en el catálogo si el catálogo está provisto
        if active_catalog and tool_name not in active_catalog:
            return ToolCallValidationVerdict(
                is_valid=False,
                tool_name=tool_name,
                error=f"La herramienta '{tool_name}' no existe en el catálogo registrado.",
            )

        # 3. Validar integridad de argumentos
        sanitized_args: dict[str, Any] = {}
        for k, v in tool_call.arguments.items():
            if not isinstance(k, str) or not k.strip():
                continue
            clean_key = k.strip()
            # Validación de tipos primitivos seguros
            if isinstance(v, (str, int, float, bool, list, dict)) or v is None:
                sanitized_args[clean_key] = v

        return ToolCallValidationVerdict(
            is_valid=True,
            tool_name=tool_name,
            sanitized_arguments=sanitized_args,
            error=None,
        )


class ToolCallAdapter:
    """Adaptador bidireccional entre ToolCall y ParsedIntent con soporte de fallback seguro."""

    @classmethod
    def to_parsed_intent(
        cls,
        tool_call: ToolCall | None,
        raw_text: str = "",
        respuesta_hablada: str = "",
    ) -> ParsedIntent:
        """Convierte una ToolCall en un ParsedIntent listo para el IntentValidator del sistema."""
        if tool_call is None:
            # Fallback a respuesta conversacional o inválida
            return ParsedIntent(
                estado=IntentStatus.CLEAR if respuesta_hablada else IntentStatus.INVALID,
                respuesta_hablada=respuesta_hablada or raw_text or "No pude comprender la orden.",
                skill=None,
                parametros={},
                error=None if respuesta_hablada else "No se detectó ninguna llamada a herramienta estructurada válida.",
            )

        return ParsedIntent(
            estado=IntentStatus.CLEAR,
            respuesta_hablada=respuesta_hablada or f"Ejecutando {tool_call.tool_name}.",
            skill=tool_call.tool_name,
            parametros=dict(tool_call.arguments),
            error=None,
        )

    @classmethod
    def from_parsed_intent(cls, intent: ParsedIntent) -> ToolCall | None:
        """Convierte un ParsedIntent válido en una ToolCall estructurada."""
        if not intent.skill or intent.estado != IntentStatus.CLEAR:
            return None

        return ToolCall(
            call_id=f"call-{uuid.uuid4().hex[:8]}",
            tool_name=str(intent.skill),
            arguments=dict(intent.parametros) if intent.parametros else {},
            confidence=1.0,
        )
