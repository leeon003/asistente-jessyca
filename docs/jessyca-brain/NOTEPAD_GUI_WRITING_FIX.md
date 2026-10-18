# JESSYCA ASISTENTE 4.0 — CORRECCIÓN DE ESCRITURA EN INTERFAZ GRÁFICA (BLOC DE NOTAS)

## 1. RESUMEN EJECUTIVO
Se auditó y corrigió el pipeline de comprensión, planificación, ejecución y verificación de **JESSYCA BRAIN** en Windows 11 para la interacción con editores de texto gráficos (Bloc de notas / Notepad). Anteriormente, la instrucción *"Jessica, abre el Bloc de notas y escribe los 3 principios de la termodinámica"* abría `notepad.exe` pero redirigía la escritura a `files.create`, creando un archivo en disco (`resumen.txt`) de forma invisible sin interactuar con la ventana activa y anunciando falsamente que había completado la tarea.

La arquitectura ha sido corregida quirúrgicamente: ahora el planificador diferencia rigurosamente entre creación de archivos en disco y escritura en ventanas gráficas; el orquestador genera el contenido conceptual estructurado mediante Ollama (`llama3.2:latest`); el controlador de escritorio (`UnifiedDesktopController`) enfoca la ventana y su área editable inyectando el texto mediante el portapapeles o teclado seguro; y el motor de verificación (`ExecutionVerifier`) comprueba activamente que el contenido exista dentro de la ventana de la aplicación.

---

## 2. AUDITORÍA DE CAUSA RAÍZ

### 2.1 La Confusión de Operaciones en el Planificador y Agente Local
Se identificó que el pipeline anterior colapsaba cuatro operaciones distintas en una sola:
1. **Creación de archivo de sistema (`create_file`):** Operación en disco (`scratch/` o filesystem) usando llamadas I/O directas.
2. **Apertura de aplicación (`open_application`):** Lanzamiento del proceso ejecutable (`notepad.exe`) y localización de su HWND.
3. **Escritura en interfaz gráfica (`write_in_window`):** Enfoque de la ventana del editor, localización del control editable (UIA/Win32) e inyección real de texto.
4. **Guardado interactivo del documento (`save_document`):** Envío de secuencia `Ctrl+G` o `Ctrl+S` para persistir el documento activo.

En `planner_engine.py`, la acción de redacción se mapeaba erróneamente a `notepad_writer` con parámetro `filename="resumen.txt"`. En `local_agent.py`, el puente de herramientas redirigía ciegamente `notepad_writer` hacia la skill `files.create`.

### 2.2 Omisión de Generación Conceptual
Cuando el usuario solicitaba información conceptual (ej. *"los 3 principios de la termodinámica"*), el sistema no disponía de un paso cognitivo para invocar el LLM y generar el cuerpo del texto. En su lugar, usaba frases genéricas predefinidas o intentaba escribir el título de la orden como contenido literal.

### 2.3 Falsos Éxitos por Verificación Desconectada
`ExecutionVerifier` utilizaba `FileExistsVerificationStrategy` para cualquier acción que contuviera la palabra `"write"`. Como `files.create` efectivamente creaba `resumen.txt` en disco, el verificador reportaba `is_verified=True` y éxito al 100%, mientras la ventana del Bloc de notas en pantalla permanecía totalmente vacía.

### 2.4 Bloqueo de Enfoque en Windows 11 (Foreground Lock Timeout)
En Windows 11, llamadas aisladas a `SetForegroundWindow(hwnd)` desde hilos en segundo plano fallaban con el código Win32 `(1460, 'SetForegroundWindow', 'Se devolvió esta operación porque se agotó el tiempo de espera.')`. Se implementó el desbloqueo activo de la cola de eventos mediante simulación de pulsación `ALT` (`VK_MENU`) y fallback con `SwitchToThisWindow` y `BringWindowToTop`.

---

## 3. ARCHIVOS MODIFICADOS Y REFACTORIZACIONES

1. [unified_controller.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/desktop/unified_controller.py):
   - Implementado método robusto `write_in_window(app_name_or_title, text, hwnd, mode, verify_content)`.
   - Soporte para modos: `"write"` (reescritura limpia), `"append"` (`Ctrl+End` + salto de línea), `"replace"` (`Ctrl+E` + nuevo texto).
   - Inyección acelerada mediante portapapeles (`pyperclip` + `Ctrl+V`) para caracteres especiales y tildes en español, con fallback a `pyautogui.typewrite`.
   - Desbloqueo de foco en Windows 11 (`VK_MENU` + `SwitchToThisWindow`).
   - Verificación de HWND mediante `win32gui.IsWindow(target_hwnd)` para evitar escritura a ciegas ante pérdida de foco.

2. [execution_verifier.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/execution/execution_verifier.py):
   - Implementada la estrategia `GuiTextVerificationStrategy`.
   - Exclusividad: las acciones de escritura gráfica (`write_in_window`, `gui_write_text`, `type_text`) son verificadas contra la ventana activa y la evidencia de inyección, nunca contra el disco.

3. [reasoning_engine.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/cognitive_brain/reasoning_engine.py):
   - Diferenciación rigurosa entre texto literal (entre comillas o tras `:`) y tema conceptual (`writing_topic`).
   - Resolución de anáforas de continuidad entre turnos (`"ahora escribe..."`, `"en esa ventana..."`, `"agrega..."`, `"corrige..."`) asociando `active_app` y `active_hwnd`.
   - Detección de intención `user_correction:unseen_text` ante frases como *"Jessica, no veo lo que escribiste"*.

4. [planner_engine.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/cognitive_brain/planner_engine.py):
   - Submetas de redacción mapeadas a `action_name="write_in_window"` y `tool_name="desktop_editor"`.
   - Mapeo diferenciado para `save_document` (`Ctrl+G`), `create_file` (filesystem), y `inspect_and_rewrite` (correcciones).

5. [brain_orchestrator.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/cognitive_brain/brain_orchestrator.py):
   - Incorporado generador de contenido conceptual `_generate_conceptual_content(topic)` con Ollama (`llama3.2:latest`) estructurado en 3 principios de termodinámica.
   - Ejecución directa de `write_in_window` con actualización de memoria de trabajo (`active_app`, `active_hwnd`, `last_written_text`).
   - Síntesis verbal precisa que informa al usuario: *"Listo, abrí Bloc de notas y escribí los 3 principios de la termodinámica."*
   - Manejo de correcciones de usuario con `inspect_and_rewrite`.

6. [procedure_learning_engine.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/cognitive_brain/procedure_learning_engine.py):
   - Filtro anti-falso éxito: rechazo absoluto de aprendizaje ante presencia de alertas `false_success` o desajuste de intención de escritura.
   - Incorporado método `audit_and_protect_candidates()` para auditar procedimientos previos sin destruirlos.

7. [memory_engine.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/cognitive_brain/memory_engine.py):
   - Integrados campos directos `active_app`, `active_hwnd`, `last_written_text` en `WorkingMemoryState` y aplanamiento en `to_dict()`.

8. [local_agent.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/local_agent/local_agent.py):
   - Eliminada la redirección silenciosa de `notepad_writer` a `files.create`.

---

## 4. COMPARATIVA DE PLANES

### Antes de la Corrección
```json
{
  "goal": "Abre el Bloc de notas y escribe los 3 principios de la termodinámica",
  "steps": [
    {
      "step_id": "step-1",
      "action_name": "open_application",
      "tool_name": "windows.apps",
      "parameters": {"app_name": "notepad.exe"}
    },
    {
      "step_id": "step-2",
      "action_name": "write_document",
      "tool_name": "files.create",
      "parameters": {"filename": "resumen.txt", "content": "Los 3 principios..."}
    }
  ]
}
```
*Resultado:* Bloc de notas vacío en pantalla. Archivo `resumen.txt` creado en disco. Falso éxito reportado.

### Después de la Corrección
```json
{
  "goal": "Abre el Bloc de notas y escribe los 3 principios de la termodinámica",
  "steps": [
    {
      "step_id": "step-1",
      "action_name": "open_application",
      "tool_name": "app_launcher",
      "parameters": {"app_name": "bloc de notas"}
    },
    {
      "step_id": "step-2",
      "action_name": "write_in_window",
      "tool_name": "desktop_editor",
      "parameters": {
        "app_name": "bloc de notas",
        "content_topic": "los 3 principios de la termodinámica",
        "mode": "write",
        "hwnd": 1445570
      }
    }
  ]
}
```
*Resultado:* Bloc de notas enfocado en pantalla. Contenido conceptual generado por Ollama pegado directamente en el editor. Verificación UI Automation confirmada. Anuncio verbal coherente.

---

## 5. PROCEDIMIENTO DE ROLLBACK
En caso de requerir volver al estado previo:
1. Revertir `core/desktop/unified_controller.py`: restaurar versión anterior del manejador de foco y métodos de escritura.
2. Revertir `core/cognitive_brain/planner_engine.py`: restaurar mapeo de `_map_subgoal_to_action`.
3. Revertir `core/cognitive_brain/brain_orchestrator.py`: eliminar `_generate_conceptual_content` y restaurar `_synthesize_plan_response`.
4. Revertir `core/cognitive_brain/procedure_learning_engine.py`: retirar comprobaciones de desajuste en `learn_from_experience`.
5. Ejecutar la suite de pruebas para confirmar integridad:
   ```powershell
   pytest tests/cognitive_brain/test_reasoning_and_planning.py
   ```
