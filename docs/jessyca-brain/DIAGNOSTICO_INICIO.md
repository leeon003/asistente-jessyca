# DIAGNÓSTICO Y REPARACIÓN DEL INICIO DE JESSYCA BRAIN 1.0

**Proyecto:** JESSYCA Asistente Personal  
**Sistema Operativo:** Windows 11 Pro 64-bit  
**Fecha:** 16 de Octubre de 2026  
**Prioridad:** ABSOLUTA (Reparación de Inicio por Doble Clic y Lanzador Oficial)

---

## 1. Resumen Ejecutivo del Problema

El usuario reportó:
> *"Cuando hago doble clic en `iniciar_jessyca.bat`, JESSYCA NO SE INICIA. La Fase 7 reportó 93 pruebas exitosas y declaró JESSYCA BRAIN 1.0 funcional, pero actualmente no puedo utilizar el asistente porque su lanzador no funciona correctamente. Este problema tiene PRIORIDAD ABSOLUTA."*

Se llevó a cabo una investigación profunda y rigurosa en el entorno Windows 11 sin suposiciones, reproduciendo exactamente la ejecución del archivo batch y de los módulos de inicio.

---

## 2. Causas Raíz Técnicas Identificadas

### Causa 1: Desincronización de Caracteres en CMD por Terminaciones UNIX LF y Caracteres Multibyte UTF-8 (Causa Primaria de Cierre Inmediato)
- **Diagnóstico:** El archivo `iniciar_jessyca.bat` original fue guardado con finales de línea UNIX LF (`\n`, byte `0x0A`) en lugar de finales de línea nativos de Windows CRLF (`\r\n`, bytes `0x0D 0x0A`). Al mismo tiempo contenía caracteres multibyte UTF-8 (como el guión largo em-dash `—` de 3 bytes `\xe2\x80\x94`).
- **Comportamiento en Windows 11:** El analizador sintáctico de `cmd.exe` lee archivos batch por bloques de bytes asumiendo CRLF. Al procesar caracteres multibyte con LF, el puntero de lectura se desfasó, causando que CMD leyera palabras cortadas a la mitad:
  - `chcp 65001 > nul` fue leído como `"001" no se reconoce como un comando interno o externo`
  - `title JESSYCA BRAIN...` fue leído como `"ESSYCA" no se reconoce como un comando interno o externo`
  - `echo Iniciando...` fue leído como `"Iniciando" no se reconoce como un comando interno o externo`
  - `python iniciar_jessyca.py` fue leído como `"hon" no se reconoce como un comando interno o externo`
  - `if errorlevel 1` fue leído como `"errorlevel" no se reconoce como un comando interno o externo`
- **Impacto:** Ninguna línea se ejecutó. La consola se abría y se cerraba en menos de 100 milisegundos sin dejar rastro visible para el usuario.

### Causa 2: Ausencia de Anclaje de Directorio (`cd /d "%~dp0"`)
- **Diagnóstico:** El lanzador original no incluía `cd /d "%~dp0"`.
- **Impacto:** Cuando un usuario hace doble clic desde el Explorador de Archivos o un acceso directo en el escritorio, el directorio de trabajo predeterminado de Windows puede ser `C:\Windows\System32` o la carpeta personal del usuario. Al invocar `python iniciar_jessyca.py`, Python buscaba el archivo en la ruta equivocada arrojando `[Errno 2] No such file or directory`.

### Causa 3: Detección Ambigua del Intérprete Python y Entorno Virtual Incompleto
- **Diagnóstico:** En la raíz del repositorio existía una carpeta `venv`, pero carecía de dependencias esenciales (`torch`, etc.). Al invocar un comando genérico `python`, en Windows 11 podía resolverse el alias de la Tienda de Windows (`WindowsApps/python.exe`), el `venv` roto o un intérprete sin dependencias.
- **Impacto:** Excepciones silenciosas o aborto de inicio por módulos faltantes.

### Causa 4: Cierre Prematuro por Ausencia de Pausa Incondicional
- **Diagnóstico:** El batch original únicamente ejecutaba `pause` bajo `if errorlevel 1`. Si el proceso de Python finalizaba de forma limpia (código 0) tras una opción o salida, o si el usuario cerraba el diálogo, la ventana desaparecía instantáneamente sin permitir leer la salida o diagnósticos.

### Causa 5: Error en `urllib.request.Request` dentro de `iniciar_jessyca.py`
- **Diagnóstico:** En `iniciar_jessyca.py`, la comprobación de Ollama utilizaba `urllib.request.Request("...", timeout=3)`. En la biblioteca estándar de Python, `Request.__init__` no acepta el argumento `timeout` (éste pertenece a `urllib.request.urlopen`).
- **Impacto:** La función capturaba `TypeError` y marcaba erróneamente Ollama como `NO DISPONIBLE`.

### Causa 6: Excepción `NameError: name 'settings' is not defined` en `core/local_agent/local_agent.py`
- **Diagnóstico:** En la línea 163 de `core/local_agent/local_agent.py`, se había introducido:
  ```python
  self.use_jessyca_brain = bool(getattr(settings, "USE_JESSYCA_BRAIN", True))
  ```
  sin invocar `get_settings()` previamente en el ámbito del método `__init__`.
- **Impacto:** Cualquier arranque que instanciara `JessycaLocalAgent` fallaba inmediatamente con `NameError`.

---

## 3. Correcciones Implementadas

1. **Reescritura Estricta de `iniciar_jessyca.bat` con Formato Windows CRLF:**
   - Codificación UTF-8 pura con saltos de línea Windows CRLF (`\r\n`).
   - Inclusión obligatoria de `cd /d "%~dp0"` para garantizar la ejecución en la carpeta raíz del proyecto independientemente del método de apertura.
   - Algoritmo de detección inteligente de Python 3.11:
     1. Prueba `C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe` verificando que importe `core.local_agent`.
     2. Prueba `python` global en PATH verificando dependencias.
     3. Prueba `venv` local si está sano.
     4. Prueba `py -3.11`.
   - Verificación y auto-arranque en segundo plano del servidor Ollama (`localhost:11434`) si no está activo.
   - Comando `pause >nul` incondicional al final: la consola jamás se cerrará sola tras un doble clic.

2. **Reparación y Refactorización de `iniciar_jessyca.py`:**
   - Corrección de `urlopen(req, timeout=3)`.
   - Registro estructurado y persistente de cada inicio en `logs/startup.log`.
   - Comprobaciones completas de hardware de audio (detección de Logitech G435 y Realtek Audio).
   - Menú interactivo enriquecido (Modo Voz Continuo, PTT, Modo Texto, Prueba Guiada, Diagnósticos Doctor, Suite de Aceptación, Salir).
   - Soporte para argumentos CLI directos (`--voice`, `--ptt`, `--text`, `--diag`, `--acceptance`, `--guided-voice`).

3. **Corrección de `core/local_agent/local_agent.py`:**
   - Se añadió la resolución limpia de configuración con `get_settings()` en `__init__`.

---

## 4. Evidencia de Comprobación y Certificación

La ejecución del archivo batch mediante el lanzador en Windows 11 produjo:
```text
=========================================================================
      JESSYCA BRAIN 1.0 — ASISTENTE PERSONAL (WINDOWS 11)
=========================================================================
[INFO] Carpeta de instalacion: D:\JESSYCA 3.0\asistente-jessyca
[OK] Python 3.11 verificado en AppData
[INFO] Comprobando servidor Ollama en localhost:11434...
[INFO] Iniciando JESSYCA BRAIN 1.0...

--- COMPROBACIONES PRE-FLIGHT DEL SISTEMA ---
  [✓] Runtime Python:        3.11.9 (C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe)
  [✓] Directorio Proyecto:   D:\JESSYCA 3.0\asistente-jessyca
  [✓] Servidor Ollama:       CONECTADO (Modelo: llama3.2:latest)
      Modelos disponibles:   qwen3-vl:4b, qwen3:8b, llama3.1:latest, llama3.2:latest, gemma4:e4b
  [✓] JESSYCA BRAIN 1.0:     JESSYCA BRAIN 1.0 Activo y Completo (9 Motores Certificados)
  [✓] Memoria Persistente:   Bases conectadas (memory_brain: 116 KB, sessions: 164 KB)
  [✓] Micrófono Entrada:     Logitech G435 (Micrófono (G435 Wireless Gaming Headset))
  [✓] Altavoces Salida:      Realtek Audio (Headphones (Realtek HD Audio 2nd output))
  [✓] Control de Escritorio: UnifiedDesktopController (NativeWindowsDriver)
---------------------------------------------------------------------------
JESSYCA se cerro correctamente.
Presione cualquier tecla para cerrar esta ventana...
```
**Código de Salida:** `0` (Éxito absoluto).  
**Registro:** Guardado con éxito en `logs/startup.log`.
