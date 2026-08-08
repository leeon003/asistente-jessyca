# Arquitectura de Gestores del Core: Capability, Context y Session Manager

Este documento describe el diseño, funcionamiento y ejemplos de integración de la tríada de gestores centralizados en **Jessyca Windows MCP**:

1. **Capability Manager**: Desacoplamiento del Task Executor.
2. **Context Manager**: Estado temporal de conversación y escritorio Windows.
3. **Session Manager**: Auditoría y ciclo de vida de sesiones.

---

## 1. Capability Manager (`core/capability.py`)

### Objetivo
Desacoplar la ejecución de tareas de los nombres concretos de herramientas (`copiador_v2_tool`), permitiendo invocarlas por su **Capacidad** (`capability`), **Acción** (`action`) y **Alias** (`aliases`).

### Ejemplos de Clasificación

| Capacidad (`capability`) | Acción (`action`) | Alias (`aliases`) | Herramienta Asignada |
| :--- | :--- | :--- | :--- |
| `Filesystem` | `copy` | `["copiar_archivo", "duplicar", "cp"]` | `file_copy_tool` |
| `Filesystem` | `delete` | `["borrar", "eliminar_archivo", "rm"]` | `file_delete_tool` |
| `Network` | `ping` | `["probar_conexion", "ping_host"]` | `network_ping_tool` |
| `Applications` | `open` | `["abrir_app", "ejecutar_programa"]` | `app_launcher_tool` |

### Uso del Capability Manager

```python
from core.capability import CapabilityManager, ToolCapabilitySpec
from tools.registry import ToolRegistry

# Instanciación e indexación automática desde el ToolRegistry
registry = ToolRegistry()
registry.discover()

cap_manager = CapabilityManager()
cap_manager.discover_capabilities(registry)

# 1. Resolución por Capacidad y Acción (Sin saber el nombre de la herramienta)
tool = cap_manager.resolve(capability="Filesystem", action="copy")

# 2. Resolución por Alias o palabra clave
tool = cap_manager.resolve_by_alias("copiar_archivo")

# 3. Enumerar todas las capacidades disponibles
capabilities = cap_manager.get_available_capabilities()
print(capabilities)  # {'Filesystem': ['copy', 'delete'], 'Network': ['ping']}
```

---

## 2. Context Manager (`core/context_manager.py`)

### Objetivo
Mantener el contexto temporal de la conversación y del entorno del usuario en Windows 10/11 de manera 100% independiente del LLM o motor de lenguaje utilizado.

### Atributos y Helpers de Estado de Escritorio

- **`active_window`**: Título de la ventana activa, nombre de proceso y PID.
- **`current_file`**: Ruta completa del archivo actual, nombre y extensión.
- **`last_directory`**: Última carpeta explorada o navegada.
- **`last_application`**: Última aplicación ejecutada.
- **`last_screenshot`**: Ruta a la última imagen capturada.
- **`last_ocr_result`**: Texto extraído por OCR, recuento de caracteres e idioma.

### Uso del Context Manager

```python
from core.context_manager import ContextManager

context = ContextManager()

# Actualizar contexto del escritorio
context.set_active_window(window_title="Documento.docx - Word", process_name="WINWORD.EXE", pid=1234)
context.set_current_file("C:/Users/Usuario/Documentos/informe.pdf")
context.set("user_preference_lang", "es", ttl_seconds=300)  # Guarda con TTL de 5 minutos

# Leer contexto
window = context.get("active_window")
current_file = context.get("current_file")

# Obtener snapshot completo del contexto no expirado
snapshot = context.get_snapshot()
```

---

## 3. Session Manager (`core/session_manager.py`)

### Objetivo
Gestionar el ciclo de vida de cada sesión de uso del asistente (ID único UUID4, hora de inicio, hora de fin, usuario, herramientas utilizadas, errores capturados, duración total) y permitir su exportación en formatos estandarizados **JSON** y **Markdown**.

### Uso del Session Manager

```python
from core.session_manager import SessionManager

session_mgr = SessionManager()

# 1. Iniciar Sesión
session = session_mgr.start_session(user="Usuario1", metadata={"environment": "production"})

# 2. Registrar ejecución de herramientas
session_mgr.record_tool_usage(
    tool_name="system_health",
    arguments={"include_metrics": True},
    is_success=True
)

# 3. Registrar errores no fatales
session_mgr.record_error("Fallo al conectar a impresora", details={"error_code": 503})

# 4. Finalizar Sesión
completed_session = session_mgr.end_session()
print(f"Duración de la sesión: {completed_session.duration_seconds} segundos")

# 5. Exportar Informe
json_report = session_mgr.export_session(completed_session.session_id, format="json")
md_report = session_mgr.export_session(completed_session.session_id, format="markdown", file_path="logs/session_report.md")
```
