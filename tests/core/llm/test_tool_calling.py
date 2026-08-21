"""Tests unitarios exhaustivos para el sistema de Robust Tool Calling (Fase 5: Robust Tool Calling)."""

from typing import Any

from core.intent_models import IntentStatus
from core.intent_validator import IntentValidator
from core.llm.tool_calling import (
    ToolCall,
    ToolCallAdapter,
    ToolCallParser,
    ToolCallValidator,
)


class DummySkill:
    def __init__(self, name: str) -> None:
        self.name = name

    def descripcion(self) -> str:
        return f"Habilidad {self.name}"

    def ejecutar(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"exito": True}


SKILLS_CATALOG = {
    "abrir_aplicacion": DummySkill("abrir_aplicacion"),
    "cerrar_aplicacion": DummySkill("cerrar_aplicacion"),
    "buscar_archivo": DummySkill("buscar_archivo"),
}


class TestRobustToolCalling:
    """Pruebas de parsing, validación, adaptación y seguridad para llamadas a herramientas."""

    def test_parse_valid_openai_format_tool_call(self) -> None:
        """Verifica el parsing de ToolCall en formato OpenAI/Ollama function calling."""
        payload = {
            "id": "call-12345",
            "function": {
                "name": "abrir_aplicacion",
                "arguments": {"nombre_app": "notepad"},
            },
        }
        tool_call = ToolCallParser.parse(payload)

        assert tool_call is not None
        assert tool_call.call_id == "call-12345"
        assert tool_call.tool_name == "abrir_aplicacion"
        assert tool_call.arguments == {"nombre_app": "notepad"}

    def test_parse_valid_structured_json_intent(self) -> None:
        """Verifica el parsing de ToolCall en formato tradicional de Jessyca (skill + parametros)."""
        payload = {
            "skill": "buscar_archivo",
            "parametros": {"nombre_archivo": "reporte.pdf", "extension": "pdf"},
        }
        tool_call = ToolCallParser.parse(payload)

        assert tool_call is not None
        assert tool_call.tool_name == "buscar_archivo"
        assert tool_call.arguments["nombre_archivo"] == "reporte.pdf"

    def test_parse_markdown_embedded_tool_call(self) -> None:
        """Verifica el parsing de ToolCall embebida en bloques markdown."""
        text = (
            "Aquí está la acción solicitada:\n"
            "```json\n"
            '{"tool": "abrir_aplicacion", "arguments": {"nombre_app": "calculadora"}}\n'
            "```\n"
        )
        tool_call = ToolCallParser.parse(text)

        assert tool_call is not None
        assert tool_call.tool_name == "abrir_aplicacion"
        assert tool_call.arguments == {"nombre_app": "calculadora"}

    def test_parse_xml_like_tool_call(self) -> None:
        """Verifica el parsing de ToolCall en tags <tool_call>."""
        text = '<tool_call>{"name": "cerrar_aplicacion", "parameters": {"nombre_app": "chrome"}}</tool_call>'
        tool_call = ToolCallParser.parse(text)

        assert tool_call is not None
        assert tool_call.tool_name == "cerrar_aplicacion"
        assert tool_call.arguments == {"nombre_app": "chrome"}

    def test_parse_corrupted_json_returns_none_and_falls_back(self) -> None:
        """Verifica que un JSON roto retorne None y el adaptador cree un ParsedIntent de fallback."""
        corrupted_text = "Esto no es un JSON { tool: 'invalido... "
        tool_call = ToolCallParser.parse(corrupted_text)

        assert tool_call is None

        # Fallback a ParsedIntent conversacional o error controlado
        intent = ToolCallAdapter.to_parsed_intent(tool_call, raw_text=corrupted_text)
        assert intent.estado == IntentStatus.INVALID
        assert intent.skill is None

    def test_validator_accepts_valid_tool(self) -> None:
        """Verifica que ToolCallValidator acepte herramientas registradas con argumentos correctos."""
        validator = ToolCallValidator(catalog=SKILLS_CATALOG)
        call = ToolCall(call_id="c1", tool_name="abrir_aplicacion", arguments={"nombre_app": "notepad"})

        verdict = validator.validate(call)
        assert verdict.is_valid is True
        assert verdict.error is None
        assert verdict.sanitized_arguments == {"nombre_app": "notepad"}

    def test_validator_rejects_nonexistent_tool(self) -> None:
        """Verifica que ToolCallValidator rechace herramientas no registradas en el catálogo."""
        validator = ToolCallValidator(catalog=SKILLS_CATALOG)
        call = ToolCall(call_id="c2", tool_name="herramienta_fantasma_peligrosa", arguments={})

        verdict = validator.validate(call)
        assert verdict.is_valid is False
        assert "no existe en el catálogo" in str(verdict.error)

    def test_adapter_pipeline_to_intent_validator(self) -> None:
        """Demuestra la tubería completa: ToolCall -> ToolCallAdapter -> IntentValidator."""
        call = ToolCall(call_id="c3", tool_name="abrir_aplicacion", arguments={"nombre_app": "notepad"})
        parsed_intent = ToolCallAdapter.to_parsed_intent(call)

        assert parsed_intent.estado == IntentStatus.CLEAR
        assert parsed_intent.skill == "abrir_aplicacion"
        assert parsed_intent.parametros == {"nombre_app": "notepad"}

        # Validación determinista con IntentValidator
        intent_validator = IntentValidator(skills_disponibles=SKILLS_CATALOG)
        val_result = intent_validator.validate(parsed_intent)

        assert val_result.is_valid is True
        assert val_result.status == IntentStatus.CLEAR

    def test_security_rule_tool_call_is_untrusted_data(self) -> None:
        """Invariante de Seguridad: La ToolCall es datos no confiables y no concede autorización por sí misma."""
        # Un modelo puede sugerir argumentos maliciosos o ambiguos
        call = ToolCall(call_id="c4", tool_name="abrir_aplicacion", arguments={"nombre_app": "eso"})
        parsed_intent = ToolCallAdapter.to_parsed_intent(call)

        intent_validator = IntentValidator(skills_disponibles=SKILLS_CATALOG)
        val_result = intent_validator.validate(parsed_intent)

        # "eso" es ambiguo -> IntentValidator debe clasificarlo como AMBIGUOUS
        assert val_result.is_valid is False
        assert val_result.status == IntentStatus.AMBIGUOUS
