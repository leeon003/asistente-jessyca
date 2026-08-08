"""Ejemplo de Herramienta MCP con autodescubrimiento automático para Jessyca Windows MCP.

Demuestra cómo crear una nueva herramienta simplemente colocando el archivo
dentro de la carpeta tools/ (o cualquier subdirectorio como tools/domains/example/).
"""

from __future__ import annotations

from core.types import JSONDict
from tools.base_tool import BaseMCPTool
from tools.discovery import mcp_tool


# Ejemplo 1: Usando el decorador @mcp_tool (Recomendado para funciones rápidas y limpias)
@mcp_tool
async def saludar_usuario(nombre: str = "Usuario", idioma: str = "es") -> dict[str, str]:
    """Genera un saludo personalizado en español o inglés.

    Args:
        nombre: Nombre de la persona a saludar.
        idioma: Idioma del saludo ('es' para español, 'en' para inglés).
    """
    if idioma.lower() == "en":
        saludo = f"Hello {nombre}, welcome to Jessyca Windows MCP!"
    else:
        saludo = f"¡Hola {nombre}, bienvenido a Jessyca Windows MCP!"

    return {"saludo": saludo, "idioma": idioma}


# Ejemplo 2: Heredando de BaseMCPTool (Recomendado para herramientas orientadas a objetos)
class CalculadoraSimultaneaTool(BaseMCPTool):
    """Herramienta de ejemplo orientada a objetos para realizar operaciones aritméticas básicas."""

    def __init__(self) -> None:
        super().__init__(
            name="calculadora_basica",
            description="Realiza operaciones aritméticas sencillas (suma, resta, multiplicación, división).",
        )

    def _get_input_schema(self) -> JSONDict:
        return {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "Primer número"},
                "b": {"type": "number", "description": "Segundo número"},
                "operacion": {
                    "type": "string",
                    "description": "Operación a realizar (suma, resta, multiplicacion, division)",
                    "default": "suma",
                },
            },
            "required": ["a", "b"],
        }

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        a = float(arguments.get("a", 0))
        b = float(arguments.get("b", 0))
        op = str(arguments.get("operacion", "suma")).lower()

        if op == "suma":
            res = a + b
        elif op == "resta":
            res = a - b
        elif op == "multiplicacion":
            res = a * b
        elif op == "division":
            if b == 0:
                raise ValueError("No se puede dividir entre cero.")
            res = a / b
        else:
            raise ValueError(f"Operación '{op}' no soportada.")

        return {"resultado": res, "operacion": op}
