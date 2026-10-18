# GUÍA DE USO Y ARRANQUE — JESSYCA BRAIN 1.0 (WINDOWS 11)

**Proyecto:** JESSYCA Asistente Personal  
**Versión:** 4.0 / JESSYCA BRAIN 1.0  
**Fecha:** 16 de Octubre de 2026

---

## 1. Inicio Rápido (Método Recomendado por Doble Clic)

1. Abre el Explorador de Archivos de Windows en la carpeta del proyecto:
   ```
   D:\JESSYCA 3.0\asistente-jessyca
   ```
2. Haz **doble clic** en el archivo:
   ```
   iniciar_jessyca.bat
   ```
3. Se abrirá una ventana de consola con el título **JESSYCA BRAIN 1.0 — Asistente Personal Windows 11**.
4. La ventana ejecutará automáticamente las comprobaciones pre-flight y mostrará el estado del sistema en pantalla:
   - Runtime Python y ruta del intérprete.
   - Estado del servidor Ollama y modelos locales.
   - Estado de JESSYCA BRAIN (9 motores cognitivos).
   - Memoria persistente SQLite.
   - Micrófono (Logitech G435) y Altavoces.
   - Controlador nativo de Windows 11.
5. Aparecerá el menú interactivo para seleccionar cómo deseas utilizar el asistente.

---

## 2. Opciones del Menú Principal

```text
=================================================================
  SELECCIONA EL MODO DE INICIO PARA JESSYCA:
  1. Iniciar Modo Voz Continuo (Escucha constante / 'Jessica')
  2. Iniciar Modo Pulsar para Hablar (PTT con tecla ENTER)
  3. Iniciar Modo Texto Interactivo (Consola de chat CLI)
  4. Ejecutar Prueba Presencial Guiada de Micrófono (G435)
  5. Diagnóstico Completo del Asistente (Doctor & Pre-Flight)
  6. Ejecutar Suite de Aceptación de Usuario (10 Escenarios)
  7. Salir
=================================================================
```

### Opción 1: Modo Voz Continuo
- El micrófono se mantiene en escucha activa.
- Di en voz alta: *"Jessica, ¿quién fue Albert Einstein?"* o *"Jessica, abre la Calculadora"*.
- Para terminar la conversación di *"adiós"*, *"salir"* o presiona `Ctrl+C`.

### Opción 2: Modo Pulsar para Hablar (Push-To-Talk / PTT)
- El micrófono permanece inactivo para no saturar tu conexión ni escuchar ruidos ambientales.
- Cuando quieras hablar, presiona la tecla `ENTER`, habla hacia tu micrófono y suelta.
- JESSYCA procesará tu audio y responderá por los altavoces con voz neural.

### Opción 3: Modo Texto Interactivo (Predeterminado)
- Se inicia una consola de conversación directa por teclado.
- Puedes escribir cualquier consulta o pedirle que controle aplicaciones:
  - *"abre la Calculadora"*
  - *"escribe un resumen sobre inteligencia artificial en Bloc de notas"*
  - *"baja el volumen"*

### Opción 4: Prueba Presencial Guiada de Micrófono (G435)
- Permite comprobar rápidamente que tu diadema Logitech G435 está grabando y reproduciendo audio.
- Graba 4 segundos de tu voz, transcribe con Whisper, consulta a JESSYCA BRAIN y reproduce la respuesta hablada por tus altavoces con métricas de latencia.

### Opción 5: Diagnóstico Completo (Doctor)
- Ejecuta una auditoría completa del entorno (GPU/VRAM, versión de Windows, permisos de escritura en carpetas segregadas).

### Opción 6: Suite de Aceptación de 10 Escenarios
- Ejecuta de forma desatendida las 10 pruebas maestras de usuario (conversación, control de escritorio, memoria, aprendizaje y parada de emergencia).

---

## 3. Resolución de Problemas Frecuentes

### ¿Qué hago si Ollama no responde o aparece como no disponible?
- El lanzador `iniciar_jessyca.bat` intentará arrancar `ollama serve` automáticamente si no lo encuentra.
- Si prefieres iniciarlo manualmente, abre una terminal de Windows y escribe:
  ```powershell
  ollama serve
  ```
- Comprueba que el modelo principal esté descargado ejecutando:
  ```powershell
  ollama list
  ```
  Debe aparecer `llama3.2:latest`.

### ¿Qué hago si el micrófono Logitech G435 no se escucha?
- Asegúrate de que los auriculares estén encendidos y emparejados por el receptor Lightspeed (LED en color cian) o por Bluetooth (LED en color azul).
- Verifica en la configuración de sonido de Windows 11 que el dispositivo de entrada predeterminado sea **Micrófono (G435 Wireless Gaming Headset)** y que el volumen del micrófono esté al 80% o más.
- Ejecuta la **Opción 4** del lanzador para validar la captura en vivo.

### ¿Dónde consulto los registros de fallos?
- Cada inicio y cualquier excepción ocurrida se guardan detalladamente en:
  ```
  logs\startup.log
  ```
- Los logs operativos del núcleo y el servidor MCP se encuentran en:
  ```
  logs\jessyca_mcp.log
  ```

---

## 4. Mecanismo de Rollback (Reversión Segura)

Si deseas volver al pipeline anterior sin el cerebro unificado, edita `config/settings.py` y cambia:
```python
USE_JESSYCA_BRAIN = False
```
Guarda el archivo. JESSYCA utilizará de inmediato el enrutador legado sin perder ningún archivo ni dato previo.
