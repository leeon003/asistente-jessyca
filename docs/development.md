# Guía para Desarrolladores - Jessyca Windows MCP

## Requisitos Previos

- Python 3.11+
- Git
- Consola de Windows (PowerShell, Command Prompt o Windows Terminal)

---

## Configuración del Entorno de Desarrollo

1. Clonar el repositorio y navegar a la carpeta:
```powershell
git clone https://github.com/leeon003/asistente-jessyca.git
cd asistente-jessyca
```

2. Crear y activar un entorno virtual de Python:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

3. Instalar las dependencias de desarrollo:
```powershell
pip install -r requirements.txt
```

---

## Creación y Declaración de Herramientas MCP

Para agregar una nueva herramienta en Jessyca Windows MCP, ubica el módulo en el subdirectorio temático correspondiente en `tools/` (ej. `tools/filesystem/`, `tools/network/`, `tools/system/`).

### Ejemplo Conceptual de Herramienta

```python
from tools.base_tool import BaseMCPTool
from core.security import RiskLevel
from core.types import JSONDict

class ReadFileTool(BaseMCPTool):
    def __init__(self) -> None:
        super().__init__(
            name="read_file",
            description="Lee el contenido de un archivo del disco",
            version="1.0.0",
            author="Jessyca Core Team",
            category="filesystem",
            capability="filesystem",
            action="read",
            aliases=["leer_archivo", "abrir_archivo"],
            risk_level=RiskLevel.SAFE,
            required_permissions=["filesystem.read"],
            timeout_seconds=10.0,
            supports_rollback=False,
        )

    def _get_input_schema(self) -> JSONDict:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Ruta del archivo a leer"}
            },
            "required": ["file_path"]
        }

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        file_path = str(arguments["file_path"])
        # Lógica de la herramienta...
        return {"content": "..."}
```

Al colocar la clase derivante de `BaseMCPTool` en la carpeta `tools/`, el `ToolDiscoveryEngine` la descubrirá automáticamente al iniciar el servidor, registrándola en el `ToolRegistry`, asociando sus metadatos en el `CapabilityManager` y exponiéndola en `FastMCP`.

---

## Pruebas y Calidad de Código

```powershell
# Ejecución de pruebas unitarias
pytest -v

# Verificación de linter y formateo
python -m ruff check .

# Verificación de tipos estáticos
python -m mypy core config services tools utils server.py main.py
```
