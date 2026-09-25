# AUDITORÍA TÉCNICA — INTEGRACIÓN ARE + JARVIS-PY EN JESSYCA 4.0 (FASE 77)

**Fecha de Auditoría**: Septiembre 2026  
**Estado de Modificaciones**: NINGUNA (Fase exclusiva de Inspección, Trazabilidad y Diagnóstico)  
**Objetivo**: Evaluar con rigor técnico el estado real, dependencias, trazabilidad, seguridad, modelo de memoria y nivel de duplicación de los módulos externos adaptados (ARE y Jarvis-py) dentro del ecosistema de JESSYCA 4.0.

---

## 1. RESUMEN EJECUTIVO

La inspección integral del código fuente confirma que:
1. **JESSYCA es el Núcleo Único y Soberano**: Ni ARE ni Jarvis-py funcionan como agentes autónomos independientes en el sistema. Están encapsulados bajo el patrón `IntegrationAdapter` dentro del subsistema `core/integration/`.
2. **Aislamiento Total del Flujo de Producción**: Tanto `AREAdapter` como `JarvisAdapter` se encuentran en estado **AISLADO**. Ningún turno de voz interactivo, comando de consola ni solicitud del `JessycaLocalAgent` delega actualmente tareas a estos adapters en tiempo de ejecución.
3. **Alto Nivel de Duplicación en Jarvis-py**: De las 5 capacidades empaquetadas en `JarvisAdapter`, 4 (`system_status`, `volume_control`, `clipboard`, `app_control`) son duplicados directos de skills nativas de JESSYCA (`windows.media`, `windows.apps`, `windows.clipboard`), ofreciendo menor nivel de verificación y menor observabilidad que el Core nativo.
4. **Valor Técnico Específico en ARE**: `AREAdapter` aporta algoritmos analíticos puros (detección de ciclos mediante el algoritmo de Kahn, cálculo de radio de impacto *blast radius* con BFS inverso y estrategias de contingencia), aunque carece de integración con el motor de inferencia LLM y con el planificador nativo `SkillGraphPlanner`.
5. **Cero Impacto en Voz y LLM**: Ni ARE ni Jarvis-py tienen dependencias con Ollama, no seleccionan modelos, no interfieren con `gemma4:e4b` y no consumen VRAM.

---

## 2. ESTADO REAL DE ARE

- **Ubicación**: [core/integration/adapters/are_adapter.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/are_adapter.py)
- **Clasificación General**: **AISLADO**
- **Arquitectura Interna**: Implementación basada en estructuras de datos puras de Python (`TaskNode`, `TaskGraph`) sin librerías externas pesadas ni llamadas a red.
- **Capacidades Declaradas**:
  1. `are.decompose_task` [READ_ONLY]: Descomposición sintáctica y heurística de objetivos en grafos acíclicos dirigidos (DAG) con ordenamiento topológico (Kahn).
  2. `are.evaluate_plan` [READ_ONLY]: Validación estructural del grafo (detección de ciclos y dependencias huérfanas).
  3. `are.diagnose_failure` [READ_ONLY]: Análisis de causa raíz y cálculo de radio de impacto (*blast radius*) aguas abajo mediante BFS inverso.
  4. `are.recover_plan` [SAFE]: Síntesis de estrategias de contingencia (`ABORT`, `SKIP`, `RETRY`, `ALTERNATIVE_BRANCH`, `ASK_USER`).
- **Capacidades Activas en Producción**: **NINGUNA**. El planificador en ejecución real sigue siendo `SkillGraphPlanner` y el `ActionPlanner` nativo de JESSYCA.
- **Capacidades Disponibles pero Desconectadas**: Las 4 capacidades están completamente implementadas y pasan 28 pruebas unitarias, pero no están conectadas a `JessycaLocalAgent` ni a `SystemCoordinator4`.
- **Ejecución de Herramientas**: ARE **NO** ejecuta herramientas ni toca el sistema operativo. Solo emite esquemas de DAG con identificadores de acciones recomendadas.
- **Verificación**: Cumple el principio `EXECUTE -> VERIFY -> REPORT` (`verified=False` por defecto; la verificación física recae en el Core).
- **Recuperación de Errores**: Sí, a nivel de síntesis de estrategia estructurada.
- **Memoria y Contexto**: **NINGUNA**. Totalmente sin estado (*stateless*). No dispone de historial ni base vectorial.
- **Uso de LLM / Ollama**: **NINGUNO**. Todo el razonamiento actual es algorítmico y heurístico. No consume tokens ni modelos de Ollama.
- **Interacción con ModelManager / ModelRouter**: No implementada actualmente.
- **Duplicación con JESSYCA**:
  - Duplica parcialmente `SkillGraphPlanner` / `SkillGraph` ([skills/skill_graph.py](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/skill_graph.py)), que ya cuenta con ordenamiento topológico y validación de ciclos para skills nativas.

---

## 3. ESTADO REAL DE JARVIS-PY

- **Ubicación**: [core/integration/adapters/jarvis_adapter.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/jarvis_adapter.py)
- **Versión Adaptada**: v3.5.2 (Shaan-alpha/jarvis-py)
- **Clasificación General**: **AISLADO / DUPLICADO**
- **Dependencias**: `psutil`, `pyperclip`, `pyautogui` (opcional), `subprocess`.
- **Capacidades Declaradas**:
  1. `jarvis.system_status` [READ_ONLY]: Lectura de telemetría de CPU y batería vía `psutil`.
  2. `jarvis.volume_control` [SAFE]: Subida, bajada y muteo de volumen vía `pyautogui.press("volume...")`.
  3. `jarvis.clipboard` [SAFE]: Lectura y escritura en portapapeles con `pyperclip`.
  4. `jarvis.workspace_files` [WARNING]: Listado, lectura, escritura y búsqueda en `%LOCALAPPDATA%/jarvis/workspace`.
  5. `jarvis.app_control` [WARNING]: Apertura vía `os.startfile` y cierre forzado con `taskkill /f /im`.
- **Capacidades Activas en Producción**: **NINGUNA**. No hay llamadas desde `JessycaLocalAgent`, `Orchestrator` ni el bucle de voz.
- **Planificación**: **INEXISTENTE**. Solo atiende operaciones atómicas de paso único.
- **Verificación**: No auto-certifica ejecuciones físicas (`verified=False, verification_required=True`).
- **Memoria Propia**: Solo persistencia de archivos de texto en la carpeta aislada del workspace. Cero memoria semántica o conversacional.
- **Interacción con LLM / Ollama / ModelRouter**: **NINGUNA**. No hace llamadas a modelos ni interactúa con `ModelManager`.
- **Duplicaciones Críticas con JESSYCA**:
  - `jarvis.volume_control` duplica `skills.windows_media_skill` (`windows.media`).
  - `jarvis.app_control` duplica `skills.apps` (`windows.apps`), la cual es significativamente superior al poseer monitoreo de handles HWND, guardas de idempotencia y verificación de procesos.
  - `jarvis.clipboard` duplica `skills.windows_skills` (`windows.clipboard`) y `core.clipboard_security`.
  - `jarvis.system_status` duplica los módulos de diagnóstico interno de JESSYCA.

---

## 4. MAPA DE INTEGRACIÓN Y ARQUITECTURA

### Arquitectura Teórica Diseñada (Integration Hub)
```text
JESSYCA Core (LocalAgent / Coordinator)
    ↓
IntegrationHub (get_integration_hub())
    ↓
IntegrationSecurityBoundary (RiskLevel, Permissions, Path Traversal)
    ↓
[Registry] ────┬───────────────────────┬────────────────────────┐
               ↓                       ↓                        ↓
          AREAdapter             JarvisAdapter         ComputerUseAdapter
         (are.decompose)       (jarvis.volume)       (computer_use.mouse)
               ↓                       ↓                        ↓
      Algoritmo Kahn/BFS        Scripts SO/psutil         PyAutoGUI/Win32
               ↓                       ↓                        ↓
      Result (verified=False) Result (verified=False)  Result (verified=False)
               └───────────────────────┼────────────────────────┘
                                       ↓
                             Fallback Nativo / Core
                                       ↓
                             ExecutionVerifier (Core)
```

### Arquitectura Real en Ejecución (Flujo en Vivo)
```text
Usuario (Voz/Texto)
    ↓
CalibratedVoiceCaptureEngine (STT faster-whisper)
    ↓
JessycaLocalAgent.interact()
    ↓
DialogueManager / ActionIntentContract
    ↓
SkillManager.execute_skill()  o  SystemCoordinator4.execute_user_request()
    ↓                                   ↓
Skills Nativas JESSYCA           SkillGraphPlanner (Nativo)
(windows.apps, browser, etc.)           ↓
    ↓                            CollaborationEngine
ExecutionVerifier / IdempotencyGuard    ↓
    ↓                            Security Policy / Tools
VoiceSpeaker (Camila / Pocket TTS)
```
**Observación**: `IntegrationHub`, `AREAdapter` y `JarvisAdapter` se encuentran desacoplados del flujo real de ejecución. Existen como subsistemas listos y probados, pero desconectados del despachador principal.

---

## 5. FLUJO DE EJECUCIÓN REAL (TRAZABILIDAD PASO A PASO)

### Caso A: ¿Qué sucede si llega una orden que teóricamente debería usar ARE?
1. El usuario dice: *"Busca los reportes financieros, resúmelos y guárdalos en un documento."*
2. El audio se procesa por STT y se normaliza en `JessycaLocalAgent`.
3. El agente evalúa la intención (`_resolve_intent_and_slots`).
4. Al detectar una orden compleja o combinada, el agente delega en `SystemCoordinator4.execute_user_request()`.
5. `SystemCoordinator4` invoca directamente `SkillGraphPlanner.plan()`.
6. El planificador interno genera un grafo de skills nativas de JESSYCA y lo despacha a `CollaborationEngine`.
7. **ARE NUNCA ES INVOCADO**. El `AREAdapter` permanece inerte en memoria.

### Caso B: ¿Qué sucede si llega una orden de abrir una aplicación o ajustar volumen?
1. El usuario dice: *"Abre el bloc de notas"* o *"Sube el volumen"*.
2. `JessycaLocalAgent` identifica `intent="open_application"` o `intent="volume_up"`.
3. `JessycaLocalAgent` despacha inmediatamente a `self.skill_manager.execute_skill("windows.apps", ...)` o `"windows.media"`.
4. La skill nativa interactúa con el sistema operativo y produce evidencias para `ExecutionVerifier`.
5. **JARVIS-PY NUNCA ES INVOCADO**. Ni `jarvis.app_control` ni `jarvis.volume_control` son consultados.

---

## 6. RELACIÓN CON MODEL MANAGER

| Componente | ¿Utiliza ModelManager? | ¿Cómo interactúa? | Impacto en Producción |
| :--- | :---: | :--- | :--- |
| **ARE** | **NO** | No posee referencias ni llamadas a `ModelManager`. Su lógica es 100% algorítmica. | Nulo |
| **Jarvis-py** | **NO** | No posee referencias ni llamadas a `ModelManager`. Opera con comandos OS directos. | Nulo |
| **JESSYCA Core** | **SÍ** | Administra `gemma4:e4b`, `llama3.2`, `qwen3:8b` y perfiles de hardware. | Núcleo soberano |

---

## 7. RELACIÓN CON MODEL ROUTER

- **¿ARE o Jarvis-py seleccionan modelos por su cuenta?**: **NO**.
- **¿Existe lógica duplicada de selección de modelos?**: **NO**.
- **¿Podrían utilizar `AUTO_ROUTE_MODEL` sin afectar el modo voz?**:
  **SÍ**. Si en el futuro `ARE` requiriera un modelo LLM para síntesis explicativa de contingencias o razonamiento profundo, podría solicitar:
  ```python
  model = model_manager.get_model(AUTO_ROUTE_MODEL, context=RoutingContext(task_type=TaskType.REASONING))
  ```
  Esto delegaría al `ModelRouter` para asignar un modelo secundario (`llama3.2` o `qwen3:8b`), mientras el bucle de voz interactivo de JESSYCA continúa fijo y sin interrupción en `gemma4:e4b`.

---

## 8. SEGURIDAD

### Evaluación de la Frontera de Seguridad
- Cuando las integraciones se ejecutan a través de `IntegrationHub.execute_capability()`, la clase `IntegrationSecurityBoundary` valida rigurosamente:
  - Nivel de riesgo (`RiskLevel.READ_ONLY`, `SAFE`, `WARNING`, `DANGEROUS`, `CRITICAL`).
  - Permisos asignados al adapter.
  - Sanitización de parámetros (evitando inyecciones o parámetros maliciosos).
  - En `JarvisAdapter`, `_resolve_safe_path` previene ataques de *Path Traversal* fuera del workspace asignado.

### Riesgos Identificados
> [!WARNING]
> **RIESGO DE INTEGRACIÓN (Invocación Directa de Adapters)**:
> Si cualquier componente en el futuro instancia o llama directamente a `adapter.execute()` omitiendo el `IntegrationHub`, se eludiría la evaluación de `IntegrationSecurityBoundary`.
> **Mitigación**: Debe garantizarse por diseño que el `IntegrationHub` sea el único punto de entrada autorizado para cualquier invocación de adapters externos.

> [!WARNING]
> **RIESGO DE INTEGRACIÓN (Comandos Forzados en Jarvis)**:
> La función `jarvis.app_control` para la acción `close` ejecuta:
> `subprocess.run(["taskkill", "/f", "/im", image])`
> Un `/f` (cierre forzado) destruye procesos sin guardar datos no guardados del usuario. La skill nativa de JESSYCA `windows.apps` implementa cierre suave mediante mensajes de ventana de Windows (`WM_CLOSE`), lo cual es infinitamente más seguro.

---

## 9. MEMORIA

- **ARE**: Totalmente carente de memoria. Sin base de datos, sin archivos, sin vector store.
- **Jarvis-py**: No dispone de memoria contextual ni semántica. Únicamente persiste archivos en disco si se le ordena explícitamente escribir en su carpeta local.
- **JESSYCA**:
  - `ConversationContextManager` (contexto conversacional, slots, seguimiento de turnos).
  - `ExperienceLogger` y `LearningEngine` (aprendizaje episódico, registro de correcciones del usuario y fallos).
  - `LocalVectorStore` (almacenamiento vectorial semántico local).
- **Conclusión**: **No existen sistemas paralelos de memoria**. JESSYCA conserva la autoridad exclusiva sobre el aprendizaje y el contexto.

---

## 10. TABLA COMPARATIVA DE DUPLICACIÓN DE CAPACIDADES

| Capacidad | JESSYCA Core | ARE (Adapter) | Jarvis-py (Adapter) | Nivel de Duplicación | Veredicto Técnico |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **LLM** | `gemma4:e4b`, `llama3.2`, `qwen3:8b` vía `ModelManager` | No tiene | No tiene | NINGUNA | JESSYCA es la única autoridad de LLM. |
| **Planning** | `SkillGraphPlanner`, `ActionPlanner`, DAG nativo | DAG con Kahn y detección de ciclos | No tiene | PARCIAL / ESTRUCTURAL | ARE aporta cálculo de radio de impacto; JESSYCA ya tiene DAG de skills. |
| **Tool Use** | 48+ Skills nativas en `SkillRegistry` | Solo emite planes sin ejecutar | 5 scripts atómicos | DUPLICADO | Las herramientas de Jarvis son subconjuntos de skills nativas. |
| **Windows Control** | `windows.apps`, `windows.media`, `windows.clipboard` | No tiene | App control, volumen, portapapeles | ALTA DUPLICACIÓN | Jarvis duplica herramientas nativas con menor nivel de seguridad. |
| **Browser** | 5 Skills (`open`, `search`, `navigate`, `read`, `youtube`) | No tiene | No tiene | NINGUNA | Exclusivo de JESSYCA. |
| **Vision** | `OllamaVisionProvider` (`qwen3-vl:4b`) | No tiene | No tiene | NINGUNA | Exclusivo de JESSYCA. |
| **Memory** | ContextManager, ExperienceLogger, VectorStore | No tiene | Solo archivos de workspace | NINGUNA | Exclusivo de JESSYCA. |
| **Verification** | `ExecutionVerifier`, `IdempotencyGuard`, Evidencias | Validación estática de grafos | No tiene (`verified=False`) | NINGUNA | Exclusivo de JESSYCA. |
| **Error Recovery** | `core/recovery/`, replanificación en `CollaborationEngine` | Diagnóstico de causa raíz y *blast radius* | Try/catch elemental | COMPLEMENTARIO | El análisis de radio de impacto de ARE aporta valor analítico. |
| **Security** | SecurityPolicy, RiskEngine, PermissionManager, AuditLogger | Metadatos de riesgo estáticos | Filtro de path traversal | NINGUNA | Exclusivo de JESSYCA. |
| **Skills** | Sistema modular formal (48 skills, sandboxing) | No tiene | 5 capacidades empaquetadas | PARCIAL | Jarvis son herramientas empaquetadas. |
| **Model Routing** | `ModelRouter`, `RoutingPolicy`, `VRAMManager` | No tiene | No tiene | NINGUNA | Exclusivo de JESSYCA. |

---

## 11. WINDOWS USE / COMPUTER USE

### Estado Actual sin Instalar `windows-use`
JESSYCA ya dispone de:
1. Control de Aplicaciones (`windows.apps` nativo): Apertura, localización de procesos, foco de ventanas y cierre controlado.
2. Control de Ventanas (`ComputerUseAdapter.window_interact`): Minimizar, maximizar, restaurar, enfocar.
3. Control de Teclado (`ComputerUseAdapter.keyboard_interact`): Escritura y atajos de teclado restringidos a una lista blanca de seguridad.
4. Control de Ratón (`ComputerUseAdapter.mouse_interact`): Movimiento, clic, doble clic y scroll validados contra límites de pantalla.
5. Capturas de Pantalla (`windows.screenshot` y `ComputerUseAdapter.observe_desktop`).
6. Navegación Web Completa (`browser.*` con perfiles reales y control multimedia).
7. Interacción Visual Multimodal (`OllamaVisionProvider` con `qwen3-vl:4b`).

### Justificación Técnica sobre una Futura Integración de `windows-use`
> [!IMPORTANT]
> **NO SE JUSTIFICA instalar `windows-use` en su estado actual.**  
> `ComputerUseAdapter` ya cubre la interacción básica por coordenadas (mouse/teclado/ventanas). La única razón técnica que justificaría incorporar una tecnología de *Computer Use* avanzada en el futuro sería si aporta **Inspección Semántica del Árbol de Accesibilidad de Windows (UI Automation / UIA)**, permitiendo interactuar con controles mediante nombres y roles accesibles (`hacer clic en botón 'Guardar'`) en lugar de depender de coordenadas `(x, y)` frágiles o inferencias visuales lentas de pantalla completa.

---

## 12. RIESGOS IDENTIFICADOS

1. **Riesgo de Destrucción de Datos con Jarvis `taskkill /f`**: La implementación de cierre en Jarvis fuerza la muerte del proceso, lo que puede provocar pérdida de documentos no guardados. Debe priorizarse siempre la skill nativa `windows.apps`.
2. **Latencia por Invocaciones Dobles**: Si un planificador intentara encadenar `SkillGraphPlanner` y `AREAdapter`, se duplicaría el tiempo de planificación sin ganancia observable en órdenes simples.
3. **Bypass Teórico si se elude el Hub**: Llamadas directas al adapter sin pasar por `IntegrationHub` eludirían el `IntegrationSecurityBoundary`.

---

## 13. CAPACIDADES FALTANTES

1. **Inspección UIA Semántica**: Falta un puente de UI Automation nativo para identificar controles accesibles de Windows sin recurrir a clics ciegos por coordenadas.
2. **Conexión de Diagnóstico de ARE con `CollaborationEngine`**: La capacidad `are.diagnose_failure` tiene un excelente algoritmo de radio de impacto (*blast radius*), pero actualmente no está conectada para asistir a JESSYCA cuando falla un grafo de ejecución compuesto.

---

## 14. CAMBIOS RECOMENDADOS (FASES FUTURAS)

1. **Conectar selectivamente `are.diagnose_failure`**: Exponer esta capacidad exclusivamente como un asesor de diagnóstico ante fallos en ejecuciones multi-etapa dentro de `CollaborationEngine` o `ExecutionVerifier`.
2. **Mantener `JarvisAdapter` como fallback secundario o deprecación controlada**: Dado que el 80% de sus capacidades duplican skills nativas de JESSYCA con inferior arquitectura, no debe conectarse al bucle principal de voz ni sustituir a `windows.apps` o `windows.media`.
3. **Forzar invariante de llamada a través del Hub**: Asegurar mediante tipos o decoradores que ningún componente pueda instanciar adapters directamente sin pasar por `IntegrationHub.execute_capability()`.

---

## 15. CAMBIOS QUE NO DEBERÍAN HACERSE

- **NO** reemplazar `SkillGraphPlanner` por ARE.
- **NO** reemplazar las skills nativas `windows.apps`, `windows.media` o `windows.clipboard` por Jarvis-py.
- **NO** conectar ARE ni Jarvis-py al bucle interactivo de voz.
- **NO** instalar el repositorio completo de Jarvis-py ni el de ARE.
- **NO** instalar `windows-use` sin antes definir una necesidad de accesibilidad UIA comprobable.
- **NO** permitir que adapters externos llamen directamente a modelos LLM evadiendo a `ModelManager`.

---

## 16. TESTS REALIZADOS

Se ejecutó la suite completa de pruebas relacionadas con adapters, integración, seguridad y LLM:

| Archivo / Suite de Pruebas | PASSED | FAILED | SKIPPED |
| :--- | :---: | :---: | :---: |
| `tests/test_are_adapter.py` | 28 | 0 | 0 |
| `tests/test_jarvis_adapter.py` | 30 | 0 | 0 |
| `tests/test_computer_use_adapter.py` | 26 | 0 | 0 |
| `tests/test_integration_hub.py` | 20 | 0 | 0 |
| `tests/core/llm` | 15 | 0 | 0 |
| `tests/test_security.py` | 10 | 0 | 0 |
| `tests/test_security_policy.py` | 4 | 0 | 0 |
| `tests/test_risk_engine.py` | 5 | 0 | 0 |
| **TOTAL CONSOLIDADO** | **138** | **0** | **0** |

*(Nota: En la suite extendida previa de LLM y Visión se validaron adicionalmente 104 pruebas unitarias sin fallos)*.

---

## 17. CONCLUSIÓN TÉCNICA

- **ARE** está implementado como un componente **AISLADO** de razonamiento estructurado; su valor reside exclusivamente en sus algoritmos analíticos de grafos y diagnóstico de impacto (*blast radius*). No interfiere en la latencia ni en la voz.
- **Jarvis-py** está implementado como un componente **AISLADO y ALTAMENTE DUPLICADO**. Sus funciones operativas ya son cubiertas de forma más segura y trazable por las skills nativas de JESSYCA.
- **JESSYCA 4.0** mantiene absoluta integridad arquitectónica: el bucle de voz interactivo y la toma de decisiones están 100% protegidos, desacoplados y respaldados por sus propios motores nativos.

---

## 18. PRÓXIMO PASO RECOMENDADO

Mantener ARE y Jarvis-py aislados en su capa de adapters. En la siguiente fase, si se requiere optimizar la resiliencia en fallos de tareas complejas, evaluar la vinculación puntual de `are.diagnose_failure` al subsistema de recuperación de errores (`core/recovery/`), sin modificar el orquestador principal ni el flujo de voz.
