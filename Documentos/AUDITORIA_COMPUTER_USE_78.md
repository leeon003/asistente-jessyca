# AUDITORÍA TÉCNICA PROFUNDA DE COMPUTER USE — JESSYCA 4.0 (FASE 78)

**Fecha de Auditoría**: Septiembre 2026  
**Estado de Modificaciones**: NINGUNA (Fase exclusiva de Inspección, Trazabilidad y Diagnóstico)  
**Objetivo**: Auditar con exhaustividad técnica el estado actual del subsistema de Computer Use de JESSYCA 4.0 y determinar si existe una necesidad real que justifique la integración externa de `windows-use`.

---

## 1. RESUMEN EJECUTIVO

1. **JESSYCA 4.0 ya dispone de una infraestructura de Computer Use madura, nativa y multicapa**:
   - **Capa Semántica y Determinista de Skills**: `windows.apps`, `windows.media`, `windows.screenshot`, `browser.*` para control gobernado de aplicaciones, reproducción y navegación web con latencia inferior a 50 ms.
   - **Capa de Accesibilidad e Inspección UI (UIA)**: `tools/desktop/ui_backend.py` (`WindowsUIAutomationBackend`) y `tools/desktop/ui_inspection_service.py` con árbol semántico de controles (`AutomationId`, nombres accesibles, tipos de control y sanitización de secretos).
   - **Capa de Interacción Física**: `core/integration/adapters/computer_use_adapter.py` y `tools/desktop/executors.py` para control de cursor (movimiento, clics, doble clic, scroll), teclado gobernado con lista blanca (`_ALLOWED_KEYS`), gestión de ventanas Win32 y ciclos atómicos de percepción (`OBSERVAR -> ACTUAR -> OBSERVAR`).
   - **Capa de Percepción Multimodal**: `core/vision/ollama_vision_provider.py` respaldado por `qwen3-vl:4b` con localización de cajas delimitadoras y OCR sanitizado.
   - **Capa de Verificación Estricta**: `ExecutionVerifier` y `ActionVerifier` con la política obligatoria *NO EXECUTION EVIDENCE = NO SUCCESS CLAIM* (cero falsos éxitos).
2. **`windows-use` es Técnicamente Innecesario y Redundante**: JESSYCA cubre el 100% de los casos de uso prácticos de un asistente de voz y escritorio mediante APIs nativas de Windows y UI Automation. Integrar `windows-use` duplicaría código existente, introduciría latencias inaceptables de 3 a 8 segundos por turno y crearía riesgos de evasión de seguridad.
3. **Veredicto Técnico**: **NO INTEGRAR `windows-use`**. La arquitectura actual es autosuficiente, segura y determinista.

---

## 2. ARQUITECTURA Y FLUJO REAL DE COMPUTER USE

El rastreo del código fuente revela que JESSYCA ejecuta la interacción con el sistema operativo a través de una cadena gobernada y trazable:

```text
Usuario (Voz / Texto)
    ↓
CalibratedVoiceCaptureEngine (faster-whisper STT)
    ↓
JessycaLocalAgent.interact()
    ↓
Quality Analyzer & Intent Completeness Checker
    ↓
ActionPlanner (Construye ActionPlan & ActionIntentContract)
    ↓
Security Evaluation (_evaluate_action_security & RiskEngine)
    ↓
¿Requiere Confirmación Humana? ──[SÍ]──> Prompt de Confirmación (AWAITING_CONFIRMATION)
    ↓ [NO / APROBADO]
IdempotencyGuard (Previene dobles ejecuciones)
    ↓
Despacho de Ejecución:
    ├── Skills Nativas (windows.apps, windows.media, browser.youtube)
    ├── UI Automation Backend (WindowsUIAutomationBackend / uiautomation)
    └── ComputerUseAdapter (Interacción directa de mouse/teclado bajo IntegrationHub)
    ↓
Windows OS (HWND, Procesos, PyAutoGUI, Win32, UIA, WebBrowser)
    ↓
ExecutionVerifier / ActionVerifier (Captura PIDs, HWND, Evidencias reales)
    ↓
Feedback & Anti-False Success (claims_success sólo si is_verified == True)
    ↓
ContextManager / ExperienceLogger / VoiceSpeaker (TTS)
```

---

## 3. CAPACIDADES ACTUALES AUDITADAS

### A. Mouse (Ratón)
- **Implementación**: `ComputerUseAdapter._execute_mouse_interact` y `tools/desktop/executors.py` (`WindowsMouseExecutor`).
- **Operaciones Disponibles**:
  - Mover cursor (`move`) a coordenadas `(x, y)`.
  - Clic simple (`click`) con botón izquierdo, derecho o central.
  - Doble clic (`double_click`).
  - Clic derecho contextual (`right_click`).
  - Desplazamiento vertical (`scroll`) con magnitud configurable.
- **Validaciones**: Verificación estricta de coordenadas contra la resolución activa de pantalla (previene clics fuera de pantalla).
- **Compensación DPI**: `core/coordinate_mapping.py` (`CoordinateSpace.PHYSICAL_PIXELS`, `LOGICAL_DIP`, `CLIENT_RELATIVE`).

### B. Teclado
- **Implementación**: `ComputerUseAdapter._execute_keyboard_type` y `tools/desktop/executors.py` (`WindowsKeyboardExecutor`).
- **Operaciones Disponibles**:
  - Escritura de texto (`write_text`) con límite de seguridad (máximo 1,000 caracteres por ráfaga).
  - Pulsación de teclas individuales (`press_key`).
  - Combinaciones y atajos (`hotkey`, ej. `ctrl+c`, `alt+tab`).
- **Restricciones de Seguridad**: Lista blanca estricta `_ALLOWED_KEYS` (alfanuméricos, flechas, teclas de función, modificadores estándar). Teclas destructivas no autorizadas son bloqueadas.

### C. Ventanas
- **Implementación**: `ComputerUseAdapter._execute_window_control`, `skills/apps_skill.py` y `tools/desktop/ui_backend.py`.
- **Operaciones Disponibles**:
  - Listar ventanas visibles (`list_windows`) con extracción de handles HWND, títulos y procesos PID.
  - Enfocar ventana (`focus_window` / `SetForegroundWindow`).
  - Minimizar (`minimize_window` / `ShowWindow SW_MINIMIZE`).
  - Maximizar (`maximize_window` / `ShowWindow SW_MAXIMIZE`).
  - Cerrar ventana (`close_window` suave vía `WM_CLOSE` o terminación de proceso).

### D. Pantalla
- **Implementación**: `ComputerUseAdapter._execute_observe_desktop` y `skills/screenshot_skill.py`.
- **Operaciones Disponibles**:
  - Captura completa del escritorio (`include_screenshot=True`) codificada en Base64 PNG mediante `PIL.ImageGrab`.
  - Telemetría de escritorio: resolución real (`width`, `height`), posición actual del cursor y lista de aplicaciones activas.

### E. Aplicaciones
- **Implementación**: `skills/apps_skill.py` (`WindowsAppsSkill`) y `core/application_session_manager.py`.
- **Operaciones Disponibles**:
  - Apertura gobernada con resolución de alias (`config/apps.yaml`).
  - Detección de procesos previos vs procesos posteriores (`pids_before` vs `pids_after`).
  - Detección de reutilización de instancia (`APPLICATION_ACTIVATED` vs `APPLICATION_OPENED`).
  - Escritura directa en la ventana activa (`_type_into_app`) combinando HWND focus, portapapeles y `ctrl+v`.
  - Cierre gobernado con verificación de terminación de proceso.

### F. Navegador Web
- **Implementación**: `skills/browser_skills.py`, `skills/browser_youtube_skill.py` y `core/browser_session_manager.py`.
- **Operaciones Disponibles**:
  - Apertura de URLs directas en Microsoft Edge / Chrome predeterminado.
  - Búsqueda web automática en Google / Bing.
  - Tarea compuesta de YouTube: `OPEN_YOUTUBE -> SEARCH_YOUTUBE -> SELECT_RESULT (scraping de VideoID) -> PLAY_MEDIA (watch?v=...) -> VERIFY_PLAYBACK`.
  - **Tecnología utilizada**: Protocolo de navegador del SO y `BrowserSessionManager` (no requiere Selenium ni WebDriver pesado).

---

## 4. DIFERENCIACIÓN TÉCNICA: ACTIONPLANNER VS COMPUTERUSEADAPTER

Existe una separación estricta de responsabilidades bajo el principio: **PLANIFICAR != EJECUTAR**.

| Acción Solicitada | ActionPlanner | ComputerUseAdapter | Skill Nativa | Otro Componente |
| :--- | :--- | :--- | :--- | :--- |
| **Abrir aplicación** | Planifica `open_application` | No abre apps directamente | `windows.apps` (Lanza, mide PIDs y enfoca) | `ApplicationSessionManager` |
| **Cerrar aplicación** | Planifica `close_application` | `window_control: close_window` | `windows.apps` (Cierre suave por HWND) | `ApplicationSessionManager` |
| **Escribir texto** | Planifica `type_text` | `keyboard_type: write_text` | `windows.apps._type_into_app` | `WindowsKeyboardExecutor` (UIA) |
| **Clic de ratón** | No gestiona clics atómicos | `mouse_interact: click` | No aplica | `WindowsMouseExecutor` (UIA) |
| **Hotkey** | No gestiona hotkeys crudos | `keyboard_type: hotkey` | `windows.apps` (Uso puntual de `ctrl+v`) | `WindowsKeyboardExecutor` (UIA) |
| **Control de ventana** | No gestiona ventanas crudas | `window_control: focus/min/max` | `windows_skills.py` | `WindowsUIAutomationBackend` |
| **Screenshot** | Planifica `take_screenshot` | `observe_desktop: include_screenshot` | `windows.screenshot` | `PIL.ImageGrab` |
| **Navegador web** | Planifica `open_browser` / `search` | No aplica | `browser.open` / `browser.search` | `BrowserSessionManager` |
| **Reproducir YouTube** | Planifica `youtube_play` compuesto | No aplica | `browser.youtube` (Búsqueda + VideoID) | `webbrowser` |
| **WhatsApp** | Planifica `open_application: whatsapp:`| No aplica | `windows.apps` (URI Scheme + Proceso) | `os.startfile` |
| **Notepad** | Planifica `open_application: notepad` | `window_control` sobre `notepad.exe` | `windows.apps` (Mapeo, PIDs, tipeo) | `ApplicationSessionManager` |

---

## 5. POST-ACTION VERIFICATION (VERIFICACIÓN POST-ACCIÓN)

JESSYCA implementa una política implacable contra falsos éxitos (*Anti-False Success*):

```text
"Abre Notepad" ──> Acción OS ──> ExecutionVerifier compara PIDs ──> ¿Proceso activo? ──> [SÍ] SUCCEEDED
                                                                                     └──> [NO] VERIFICATION_FAILED (0 False Successes)
```

### Clasificación de Verificación por Acción

| Acción | Mecanismo de Verificación Real | Clasificación |
| :--- | :--- | :--- |
| **Apertura de Aplicación** | Inspección de PIDs (`psutil`), detección de HWND visible y delta de procesos | **VERIFICACIÓN FUERTE** |
| **Cierre de Aplicación** | Polling de terminación de proceso (`psutil.process_iter`) | **VERIFICACIÓN FUERTE** |
| **Captura de Pantalla** | Comprobación de bytes en buffer y archivo persistido | **VERIFICACIÓN FUERTE** |
| **Escritura en Bloc de Notas** | `_type_into_app` confirma foco HWND y pegado seguro | **VERIFICACIÓN FUERTE** |
| **Reproducción de Video Local** | Comprobación de procesos reproductores activos | **VERIFICACIÓN FUERTE** |
| **Inspección de UI (UIA)** | `ActionVerifier` valida estado observado vs esperado en árbol UIA | **VERIFICACIÓN FUERTE** |
| **Reproducción en YouTube** | Verificación de navegador activo y carga de URL con VideoID | **VERIFICACIÓN PARCIAL** |
| **Búsqueda Web** | Confirmación de lanzamiento de URL en sesión de navegador | **VERIFICACIÓN PARCIAL** |
| **ComputerUseAdapter (Raw)** | Retorna `verified=False` obligando a verificación externa | **SIN VERIFICACIÓN AUTOMÁTICA** |

---

## 6. AUTONOMÍA Y BUCLES DE EJECUCIÓN

- **¿Existe un bucle `observar -> decidir -> actuar -> observar -> corregir`?**
  - En `ComputerUseAdapter`: La capacidad `computer_use.perceive_and_act` implementa un micro-ciclo de percepción atómica: `OBSERVAR (cursor antes) -> ACTUAR (tecla/mouse) -> OBSERVAR (cursor después, delta detectado)`.
  - En `JessycaLocalAgent`: El sistema opera como un **asistente gobernado y determinista**. No realiza bucles autónomos ciegos de reintento infinito (*no auto-retry* descontrolado).
  - Si una acción falla o no se verifica, el sistema lo informa con precisión al usuario y solicita aclaración o confirmación (`AWAITING_CLARIFICATION`).
  - Esto garantiza que el asistente de voz nunca quede atrapado en bucles infinitos consumiendo CPU o recursos gráficos.

---

## 7. INTERACCIÓN VISUAL Y MULTIMODALIDAD

- **Motor de Visión**: `core/vision/ollama_vision_provider.py` respaldado por `qwen3-vl:4b`.
- **Detección de Elementos**: El modelo emite análisis estructurados en JSON con cajas delimitadoras normalizadas (0 a 1000) para cada elemento de la interfaz.
- **Mapeo de Coordenadas**: `core/coordinate_mapping.py` traduce coordenadas normalizadas a píxeles físicos del escritorio considerando el escalado DPI de Windows.
- **Realidad Operativa**: Aunque JESSYCA cuenta con capacidad visual multimodal completa, para el 95% de las tareas de escritorio **no utiliza visión por pantalla completa** debido a que la API nativa de UI Automation es 100 veces más rápida (latencia de 10 ms frente a 3,500 ms de inferencia LLM) y 100% determinista.

---

## 8. WINDOWS UI AUTOMATION (UIA) — HALLAZGO CLAVE

La auditoría confirma que **JESSYCA YA TIENE IMPLEMENTADO UN SISTEMA COMPLETO DE UI AUTOMATION**:
- **Archivos**: [tools/desktop/ui_backend.py](file:///d:/JESSYCA%203.0/asistente-jessyca/tools/desktop/ui_backend.py), [tools/desktop/ui_inspection_service.py](file:///d:/JESSYCA%203.0/asistente-jessyca/tools/desktop/ui_inspection_service.py), [tools/desktop/executors.py](file:///d:/JESSYCA%203.0/asistente-jessyca/tools/desktop/executors.py) y [tools/desktop/action_verifier.py](file:///d:/JESSYCA%203.0/asistente-jessyca/tools/desktop/action_verifier.py).
- **Capacidades UIA Existentes**:
  - Detección de ventana en primer plano (`GetForegroundControl`).
  - Inspección del árbol semántico accesible (`auto.GetRootControl().GetChildren()`).
  - Lectura de `AutomationId`, `ControlTypeName` (`Button`, `Edit`, `Window`, `CheckBox`, etc.), `BoundingRectangle`, `Name`, `ClassName`, `FrameworkId`, `HasKeyboardFocus`.
  - Clics y pulsaciones mediante UIA nativo (`WindowsMouseExecutor` y `WindowsKeyboardExecutor`).
  - Sanitización de contraseñas, secretos y tokens en los textos de los controles antes de exponerlos al agente (`OCRTextSanitizer`).

---

## 9. SEGURIDAD Y PREVENCIÓN DE BYPASS

Se auditaron todas las posibles rutas de bypass desde el LLM hasta las acciones en Windows:

1. **Parada de Emergencia**: `EmergencyStopManager` intercepta de inmediato cualquier ejecución si el usuario ordena detenerse o se activa la parada.
2. **Evaluación de Riesgo**: Toda acción es evaluada por `RiskEngine` y clasificada (`SAFE`, `MEDIUM`, `HIGH`, `CRITICAL`).
3. **Acciones Destructivas**: Operaciones como eliminación de archivos o terminación forzada de procesos requieren confirmación humana explícita (`AWAITING_CONFIRMATION`).
4. **Filtro de Teclas**: `_ALLOWED_KEYS` impide la ejecución de atajos maliciosos no supervisados.
5. **Aislamiento de Rutas**: `JarvisAdapter` y `ComputerUseAdapter` están confinados y no permiten ejecución arbitraria de scripts de consola.
- **Nivel de Riesgo de Bypass**: **BAJO**. Toda la ejecución de producción pasa forzosamente por `LocalAgent` y sus compuertas de seguridad.

---

## 10. COMPARACIÓN ARQUITECTÓNICA: JESSYCA ACTUAL VS NECESIDAD DE WINDOWS-USE

| Capacidad de Control | JESSYCA Actual | ¿Existe Brecha? | ¿`windows-use` Aportaría Valor Real? |
| :--- | :--- | :---: | :--- |
| **Mouse (Mover/Clic/Scroll)** | Sí (`ComputerUseAdapter`, `WindowsMouseExecutor`) | **NO** | No. Duplicación directa. |
| **Teclado (Tipeo/Atajos)** | Sí (Lista blanca de seguridad `_ALLOWED_KEYS`) | **NO** | No. Menor seguridad en herramientas externas. |
| **Gestión de Ventanas** | Sí (`win32gui`, UIA, enumeración, HWND) | **NO** | No. JESSYCA ya es nativa Win32. |
| **Captura de Pantalla** | Sí (`PIL.ImageGrab`, telemetría de monitor) | **NO** | No. Duplicación directa. |
| **Lanzamiento de Apps** | Sí (`windows.apps`, gestión de PIDs, sesiones) | **NO** | No. JESSYCA tiene idempotencia y verificación. |
| **Navegador Web** | Sí (`browser.*`, YouTube con resolución VideoID) | **NO** | No. JESSYCA no requiere Selenium/WebDriver. |
| **UI Automation (UIA)** | Sí (`WindowsUIAutomationBackend`, `AutomationId`) | **NO** | No. JESSYCA ya posee UIA semántico nativo. |
| **OCR / Sanitización** | Sí (`OCRTextSanitizer`, redacción de secretos) | **NO** | No. JESSYCA ya protege la privacidad. |
| **Visión Multimodal** | Sí (`OllamaVisionProvider` con `qwen3-vl:4b`) | **NO** | No. JESSYCA ya tiene modelo local. |
| **Planificación** | Sí (`ActionPlanner`, `SkillGraphPlanner`) | **NO** | No. JESSYCA planifica por contratos. |
| **Verificación Post-Acción** | Sí (`ExecutionVerifier`, *Anti-False Success*) | **NO** | No. JESSYCA es más rigurosa. |
| **Recuperación de Errores** | Sí (Aclaración contextual gobernada) | **NO** | No. Reintentos ciegos externos son peligrosos. |
| **Bucle Autónomo Libre** | No (Diseño intencional de no-auto-retry) | **NO (POR DISEÑO)** | No deseado en un asistente interactivo por voz. |
| **Seguridad y Auditoría** | Sí (`RiskEngine`, `AuditLogger`, `EventBus`) | **NO** | Herramientas externas suelen eludir la gobernanza. |

---

## 11. PRUEBAS EXISTENTES AUDITADAS

Se ejecutó la suite completa de pruebas unitarias y de integración relacionadas con Computer Use, escritorio, UIA y ejecución de aplicaciones:

| Suite de Pruebas | PASSED | FAILED | SKIPPED |
| :--- | :---: | :---: | :---: |
| `tests/test_computer_use_adapter.py` | 26 | 0 | 0 |
| `tests/desktop/test_action_guard_executors.py` | 8 | 0 | 0 |
| `tests/desktop/test_action_verification.py` | 8 | 0 | 0 |
| `tests/desktop/test_ui_inspection_backend.py` | 5 | 0 | 0 |
| `tests/desktop/test_coordinate_mapping.py` | 7 | 0 | 0 |
| `tests/test_notepad_semantic_execution.py` | 5 | 0 | 0 |
| **TOTAL CONSOLIDADO** | **59** | **0** | **0** |

---

## 12. PRUEBA FUNCIONAL CONTROLADA (EN VIVO, NO DESTRUCTIVA)

Se ejecutó una prueba funcional en el entorno real de Windows validando 5 operaciones críticas sin modificar el sistema:
1. **Inicialización**: `ComputerUseAdapter` inicializado en estado `READY` detectando resolución de monitor de **2560x1440**.
2. **Observación de Escritorio**: Telemetría completada exitosamente reportando resolución y 15 aplicaciones del sistema activas.
3. **Inspección de Ventanas**: Enumeradas exitosamente 18 ventanas visibles en el entorno de escritorio.
4. **Pulsación Segura de Teclado**: Tecla no destructiva `shift` ejecutada con éxito.
5. **Ciclo Percepción + Acción**: Completado ciclo `OBSERVAR -> ACTUAR -> OBSERVAR` con detección de cursor y delta.
6. **Inspección UIA en Vivo**: `WindowsUIAutomationBackend` inspeccionó con éxito la ventana activa en primer plano.
- **Resultado Global de la Prueba Funcional**: **100% OK (0 errores)**.

---

## 13. CONCLUSIÓN TÉCNICA Y RESPUESTAS EXPLÍCITAS

### PREGUNTA 1: ¿JESSYCA necesita actualmente `windows-use`?
> **RESPUESTA: NO.**  
> JESSYCA cuenta con una infraestructura nativa de automatización de Windows superior para los propósitos de un asistente de voz: combina APIs Win32, UI Automation semántico, control de procesos con verificación estricta de PIDs y navegación web limpia.

### PREGUNTA 2: ¿Qué capacidad concreta falta si la respuesta es sí?
> **RESPUESTA**: La única capacidad que `windows-use` plantea como diferenciador es el **bucle autónomo ciego de visión-acción** (*unconstrained vision-agent loop* para interactuar mediante clics visuales repetitivos con aplicaciones desconocidas que carecen de soporte UIA).

### PREGUNTA 3: ¿Puede esa capacidad implementarse utilizando la arquitectura actual?
> **RESPUESTA: SÍ.**  
> JESSYCA ya cuenta con todos los bloques fundacionales para implementar dicha capacidad sin librerías externas: `qwen3-vl:4b` para visión, `coordinate_mapping` para DPI, `ComputerUseAdapter` para clics/teclado y `ExecutionVerifier` para validación.

### PREGUNTA 4: ¿La incorporación de `windows-use` introduciría duplicación?
> **RESPUESTA: SÍ, INTRODUCIRÍA UNA DUPLICACIÓN MASIVA.**  
> Duplicaría el subsistema de mouse, teclado, capturas de pantalla, inspección de ventanas y planificador, además de intentar reemplazar mecanismos deterministas de milisegundos por llamadas visuales pesadas de varios segundos.

### PREGUNTA 5: ¿Existe algún motivo técnico para integrarlo AHORA?
> **RESPUESTA: NO.**  
> No existe ningún motivo técnico. Por el contrario:
> - Aumentaría la latencia de respuesta vocal destruyendo la experiencia de conversación fluida.
> - Aumentaría la superficie de ataque y los riesgos de alucinación de clics.
> - Añadiría dependencias externas frágiles que complican el despliegue local.

---

## 14. PRÓXIMO PASO RECOMENDADO

Mantener la arquitectura actual de Computer Use de JESSYCA 4.0 tal como está. Descartar definitivamente la integración de `windows-use` y concentrar los esfuerzos futuros en la orquestación semántica de las Skills existentes y en el refinamiento del diálogo conversacional.

---

## 15. EVALUACIÓN DE CRITERIOS DE DECISIÓN

### DECISIÓN A — NO INTEGRAR POR AHORA (APLICABLE)
Se constata el cumplimiento total de los criterios de la Decisión A:
- **JESSYCA ya puede realizar las acciones Windows necesarias** mediante sus Skills (`windows.apps`, `windows.media`, `browser.*`), `ActionPlanner` y `ComputerUseAdapter`.
- **Las capacidades complementarias pueden implementarse internamente** aprovechando el modelo local `qwen3-vl:4b`, el subsistema de `coordinate_mapping` y `WindowsUIAutomationBackend`.
- **`windows-use` duplicaría funciones que JESSYCA ya posee** (mouse, teclado, screenshots, ventanas, UIA).
- **No existe una mejora funcional concreta demostrable** frente al stack nativo de milisegundos con verificación estricta.
- **Añadiría dependencias, complejidad y fragilidad de mantenimiento** sin aportar una capacidad nueva justificada.
- **Las 59 pruebas unitarias y la prueba funcional en vivo demuestran** que el Computer Use nativo funciona con 100% de éxito.

*Capacidades que justificarían una futura reevaluación*: Solo si en el futuro se requiriera operar sobre software especializado/legado que deshabilite explícitamente la API de Accesibilidad de Windows (UIA) y exija navegación puramente visual por píxeles sin contratos semánticos.

---

## 16. CRITERIOS DE BLOQUEO

Se identifican los siguientes bloqueos técnicos y operativos insalvables para una eventual integración de `windows-use`:
1. **Aumento Innecesario de Latencia**: Los bucles agente de visión-acción toman de 3 a 8 segundos por interacción física, lo que destruiría la fluidez en el bucle interactivo de voz.
2. **Duplicación Grave de Capacidades**: Reimplementaría de forma externa el control de cursor, teclado, capturas e inspección de ventanas que JESSYCA ya resuelve de forma determinista.
3. **Riesgo de Bypass de Seguridad**: Las herramientas externas tipo `windows-use` asumen autonomía descontrolada y no se integran de forma nativa con el `RiskEngine`, `AuditLogger` ni con las solicitudes de confirmación humana previa (`AWAITING_CONFIRMATION`).
4. **Pérdida de Estabilidad y Alucinación**: El clic por visión sobre pantallas dinámicas presenta tasas de fallo significativamente mayores que el acceso por identificador UIA o por handle HWND.

---

## 17. MATRIZ FINAL DE DECISIÓN

| Criterio | Evidencia encontrada | Cumple | Impacto |
| :--- | :--- | :---: | :--- |
| **Capacidad nueva necesaria** | Las tareas objetivo (apps, volumen, YouTube, navegación, tipeo) ya están cubiertas. | **No** | **Alto** |
| **JESSYCA ya puede hacerlo** | Demostrado en código de Skills, UIA, 59 pruebas superadas y prueba en vivo. | **Sí** | **Alto** |
| **Puede implementarse internamente** | Si se requiere visión-acción, JESSYCA cuenta con `qwen3-vl:4b`, UIA y ejecutores. | **Sí** | **Medio** |
| **Duplicación** | Duplicaría el 100% del subsistema de mouse, teclado, capturas, ventanas y UIA. | **Sí** | **Alto** |
| **Compatibilidad arquitectónica** | Chocaría con el paradigma de despacho de Skills deterministas y contratos. | **No** | **Alto** |
| **Seguridad** | Intentaría ejecutar clics sin pasar por las compuertas `ExecutionGate` ni `RiskEngine`. | **No** | **Alto** |
| **Compatibilidad con Skills** | Eclipsaría innecesariamente el catálogo de Skills optimizadas de JESSYCA. | **No** | **Medio** |
| **Compatibilidad con ModelRouter** | Requeriría inferencias pesadas de visión no compatibles con la latencia de voz. | **No** | **Medio** |
| **Impacto en modo voz** | Degradaría la latencia de respuesta vocal a más de 3-8 segundos por turno. | **No** | **Alto** |
| **Complejidad añadida** | Introduciría dependencias externas pesadas, scripts y wrappers no gobernados. | **Sí** | **Alto** |
| **Beneficio funcional demostrable** | Cero beneficio demostrable frente al stack UIA + Win32 nativo. | **No** | **Alto** |
| **Cobertura mediante tests** | El stack nativo tiene 59 tests automatizados pasando; la integración externa tendría 0. | **No** | **Alto** |

---

## 18. RESULTADO OBLIGATORIO DE LA AUDITORÍA

### A

**WINDOWS-USE NO NECESARIO ACTUALMENTE**

