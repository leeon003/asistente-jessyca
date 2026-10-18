# REGISTRO DE ERRORES IDENTIFICADOS Y CORREGIDOS

**Proyecto:** JESSYCA Asistente Personal  
**Fecha:** 16 de Octubre de 2026  
**Ámbito:** Reparación de Inicio, Núcleo Cognitivo y Lanzador Oficial

---

## 1. Relación Detallada de Correcciones

### Error 1: Cierre Inmediato de `iniciar_jessyca.bat` por Terminaciones LF y Caracteres Multibyte
- **Severidad:** CRÍTICA (Bloqueaba el inicio de todo el sistema por doble clic).
- **Archivo:** `iniciar_jessyca.bat`
- **Causa Técnica:** El archivo batch contenía saltos de línea UNIX LF (`\n`) combinados con caracteres multibyte UTF-8 (`—`). El lector de búfer de `cmd.exe` se desalineaba, leyendo tokens rotos (`hon` en vez de `python`, `001` en vez de `chcp 65001`) y abortaba inmediatamente.
- **Solución:** Reescritura completa del archivo batch con saltos de línea Windows CRLF (`\r\n`), comandos limpios y pausa incondicional `pause >nul`.

---

### Error 2: Ejecución en Directorio Erróneo al Hacer Doble Clic
- **Severidad:** CRÍTICA.
- **Archivo:** `iniciar_jessyca.bat`
- **Causa Técnica:** Al hacer doble clic en Windows Explorer, el directorio actual (`%CD%`) no estaba garantizado y podía ser `C:\Windows\System32`, causando que `python iniciar_jessyca.py` fallara con `FileNotFoundError`.
- **Solución:** Inclusión de `cd /d "%~dp0"` como primera instrucción operativa para anclar la ejecución en la carpeta raíz del proyecto.

---

### Error 3: Detección Inadecuada del Intérprete Python y Entorno Virtual Incompleto
- **Severidad:** ALTA.
- **Archivo:** `iniciar_jessyca.bat`
- **Causa Técnica:** En la raíz existía una carpeta `venv` que carecía de `torch` y dependencias completas. Invocaciones a `python` podían seleccionar ese `venv` o el stub de WindowsApps.
- **Solución:** Se implementó una lógica de detección con verificación previa de dependencias (`python -c "import core.local_agent"`). Se prioriza el Python 3.11 instalado con todas las librerías del proyecto (`C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe`) con fallback seguro.

---

### Error 4: `TypeError` en `urllib.request.Request` dentro de `iniciar_jessyca.py`
- **Severidad:** MEDIA.
- **Archivo:** `iniciar_jessyca.py`
- **Causa Técnica:** La función `check_ollama` invocaba `urllib.request.Request("http://localhost:11434/api/tags", timeout=3)`. El constructor `Request.__init__` de Python no acepta el parámetro `timeout`, lanzando un `TypeError` que se atrapaba y reportaba falsamente que Ollama no estaba disponible.
- **Solución:** Se corrigió a `urllib.request.urlopen(req, timeout=3)`.

---

### Error 5: `NameError: name 'settings' is not defined` en `core/local_agent/local_agent.py`
- **Severidad:** CRÍTICA.
- **Archivo:** `core/local_agent/local_agent.py` (línea 163)
- **Causa Técnica:** Se intentaba leer `getattr(settings, "USE_JESSYCA_BRAIN", True)` en el método `__init__` sin haber obtenido `settings` mediante `get_settings()`.
- **Solución:** Se importó y obtuvo `_settings = get_settings()` antes de acceder al atributo.

---

### Error 6: Clasificación Inadecuada de Preguntas Conceptuales como Órdenes de Acción
- **Severidad:** MEDIA.
- **Archivo:** `core/cognitive_brain/reasoning_engine.py`
- **Causa Técnica:** Preguntas como *"JESSYCA, ¿qué diferencia existe entre inteligencia artificial y aprendizaje automático?"* no coincidían con los iniciadores conversacionales existentes (solo existía `"¿qué es"` y no `"¿qué diferencia"` o `"diferencia entre"`), provocando que el cerebro intentara crear un plan con herramientas en lugar de generar una respuesta hablada/texto directa.
- **Solución:** Se añadieron iniciadores conversacionales completos (`"¿qué diferencia"`, `"diferencia entre"`, `"¿cuál es la diferencia"`, `"explícame de otra manera"`, etc.) y se implementó una regla de continuación conversacional para *"continúa con lo anterior"* cuando el tema previo es conceptual.

---

### Error 7: `TypeError` por Argumento Inexistente en `GoalComprehension`
- **Severidad:** ALTA.
- **Archivo:** `core/cognitive_brain/reasoning_engine.py` (línea 92)
- **Causa Técnica:** Se instanciaba `GoalComprehension(..., anaphora_resolved=anaphora_resolved)`. El campo formal en `contracts.py` se llama `context_references`.
- **Solución:** Se renombró el argumento a `context_references=anaphora_resolved`.

---

### Error 8: Manejo de Tupla de Retorno en `scripts/guided_voice_test.py`
- **Severidad:** MEDIA.
- **Archivo:** `scripts/guided_voice_test.py`
- **Causa Técnica:** `tts_mgr.synthesize(...)` retorna una tupla `(TTSAudioResult, TTSMetrics)` en lugar de una ruta string, lo que impedía que `pygame.mixer` reprodujera el archivo de audio.
- **Solución:** Se extrajeron los `audio_bytes` del resultado, guardándolos en `scratch/voice_tests/live_response.mp3` y reproduciéndolos directamente a través de `pygame.mixer`.
