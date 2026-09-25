# FASE 79 — AUDITORÍA DE CONSOLIDACIÓN ARQUITECTÓNICA Y FLUJO DE EJECUCIÓN
## JESSYCA 4.0 — INFORME TÉCNICO Y MAPA DE EJECUCIÓN REAL

**Fecha:** 2026-09-18  
**Tipo de Documento:** Auditoría de Arquitectura de Sistema y Flujo de Control  
**Regla de Ejecución:** Auditoría estricta de código sin modificaciones en producción, sin cambios de configuración, sin commits ni pushes.

---

## RESUMEN EJECUTIVO

Se ha completado una inspección exhaustiva de código, dependencias, flujo de ejecución y pruebas de JESSYCA 4.0. Se examinaron los 11 componentes críticos: Orchestrator, LocalAgent, ActionPlanner, ComputerUseAdapter, Skills Nativas, ExecutionVerifier, SecurityPolicy/RiskEngine, ModelRouter/ModelManager, IntegrationHub, ARE/Jarvis y MCP Server.

### Hallazgos Fundamentales:
1. **La Autoridad de Despacho Real es `JessycaLocalAgent`**: A nivel de runtime en producción (modo voz y demo), `interfaces/modo_voz.py` no invoca a `core/orquestador.py`. Invoca directamente a `JessycaLocalAgent.get_instance().interact(req)`.
2. **`core/orquestador.py` es Código Heredado Aislado**: La función clásica `ejecutar_orden_texto` pertenece a las versiones v1/v2 y está desacoplada del pipeline de voz activo. `core/orchestrator_adapter.py` actúa como un puente sobre el Event Bus que interiormente delega en `JessycaLocalAgent`.
3. **LocalAgent Acumula Múltiples Roles**: `JessycaLocalAgent` asume el rol de diálogo, extracción de intenciones, mitigación de riesgos, solicitud de confirmaciones y despacho directo de skills (`windows.apps`, `windows.media`, `browser.*`), puenteando a `ActionPlanner` para comandos simples de un solo paso.
4. **`ActionPlanner` Mantiene Separación Estricta pero está Subutilizado**: Implementa con rigor el principio `PLANIFICAR != EJECUTAR` y genera contratos seguros (`ActionIntentContract`), pero en el flujo normal de voz, las intenciones atómicas son resueltas directamente por `LocalAgent` sin invocarlo.
5. **ComputerUseAdapter está Aislado y Seguro**: Implementa capacidades completas de mouse, teclado (con lista blanca de teclas seguras) y ventanas sobre `IntegrationHub`, devolviendo siempre `verified=False, verification_required=True`. El modo voz no lo invoca directamente (utiliza las skills nativas).
6. **No Existen Bypasses Críticos de Seguridad en la Ruta Activa**: Las órdenes destructivas (`kill_process`, etc.) pasan por `RiskEngine`, `SecurityPolicy`, `EmergencyStopManager` y requieren confirmación explícita del usuario (`AWAITING_CONFIRMATION`).
7. **Riesgo Identificado de "False Success"**: `ExecutionVerifier` cuenta con estrategias robustas basadas en el OS (`ProcessExistsVerificationStrategy`, `ProcessTerminatedVerificationStrategy`). Sin embargo, su estrategia comodín `StateChangedVerificationStrategy` evalúa `parameters.get("verified", True)`, lo cual podría certificar falsamente acciones no vinculadas a procesos/archivos si el emisor asume éxito prematuro.
8. **Modo Voz Estrictamente Anclado a `gemma4:e4b`**: El pipeline conversacional de voz no realiza enrutamiento dinámico no determinista; usa exclusivamente `gemma4:e4b`. El `ModelRouter` está reservado de forma segura para tareas delegadas y background vía `AUTO_ROUTE_MODEL`.

---

## 1. MAPEO DEL FLUJO REAL COMPLETO

A continuación se documenta el recorrido técnico exacto de una orden en el sistema interactivo de voz:

```text
[Usuario]
   │ (Audio capturado por micrófono)
   ▼
CalibratedVoiceCaptureEngine (engine/calibrated_voice_capture_engine.py)
   │ Función: listen() / _listen_worker() [Hilo secundario / Queue]
   ▼
STTEngine / Faster-Whisper (engine/audio_core.py)
   │ Función: transcribe_audio(audio_data) -> texto [Síncrona en hilo dedicado]
   ▼
Bucle Principal de Voz (interfaces/modo_voz.py)
   │ Función: iniciar_modo_voz() / _voice_loop() [Síncrona / bucle while]
   │ Control: Detección de Wake Word / Modo Conversacional Continuo
   ▼
JessycaLocalAgent (core/local_agent/local_agent.py)
   │ Función: interact(req: AgentInteractionRequest) -> AgentInteractionResponse [Síncrona]
   │ Quien llama: interfaces/modo_voz.py (o core/orchestrator_adapter.py vía asyncio.to_thread)
   │ Etapas internas:
   │   1. QualityGate & SessionManager
   │   2. EmergencyStopManager (Verifica si hay parada de emergencia activa)
   │   3. IntentClassifier & Memory (_extract_intent_and_entities)
   │   4. IntentMapping (_map_intent_to_tool / _select_skill_for_intent)
   │   5. RiskEngine / SecurityPolicy (Evaluación de nivel de riesgo: READ_ONLY, SAFE_WRITE, IMPACTFUL, DESTRUCTIVE)
   │   6. Si RIESGO ALTO -> Devuelve estado AWAITING_CONFIRMATION y emite mensaje pidiendo confirmación
   │   7. Si RIESGO ACEPTADO -> Despacho a SkillManager
   ▼
SkillManager (core/skills/skill_manager.py)
   │ Función: execute_skill(skill_name, action, params) [Síncrona]
   │ Quien llama: JessycaLocalAgent._execute_selected_skill()
   ▼
Skills Nativas de Windows / Navegador
   ├── WindowsAppsSkill (core/skills/builtin/windows/apps_skill.py)
   │     - Métodos: launch_app, close_app, focus_window, type_into_app
   │     - Mecanismo: win32gui, win32process, psutil, ApplicationSessionManager
   ├── WindowsMediaSkill (core/skills/builtin/windows/media_skill.py)
   │     - Métodos: set_volume, mute, play_pause
   │     - Mecanismo: pycaw (AudioEndpointVolume) / ctypes
   └── BrowserYouTubeSkill (core/skills/builtin/browser/youtube_skill.py)
         - Métodos: play, search, pause, resume
         - Mecanismo: BrowserSessionManager, webbrowser / Win32 URL activation
   ▼
ExecutionVerifier (core/execution/execution_verifier.py)
   │ Función: verify_execution(action, params, evidence) -> VerificationResult [Síncrona]
   │ Estrategias:
   │   - ProcessExistsVerificationStrategy (Verifica psutil / PID / HWND)
   │   - ProcessTerminatedVerificationStrategy (Verifica que el PID desapareció)
   │   - FileExistsVerificationStrategy (Verifica ruta en filesystem)
   │   - StateChangedVerificationStrategy (Verifica flags de parámetros)
   ▼
Retorno de Respuesta (core/local_agent/local_agent.py)
   │ Objeto: AgentInteractionResponse(message="...", state=AgentState.IDLE, result={...})
   │ Registro: ExperienceLogger, ConversationContextManager
   ▼
TTSManager / VoiceSpeaker (engine/audio_core.py / engine/camila_tts.py)
   │ Función: speak(text) [Síncrona / llamada por interfaces/modo_voz.py]
   │ Motores: Camila Neural TTS (Edge-TTS) con fallback a Pocket TTS / SAPI
   ▼
[Usuario] (Respuesta escuchada por los altavoces)
```

### Tabla de Propiedades de Ejecución por Etapa

| Etapa | Archivo | Clase / Módulo | Función | Quién Invoca | Quién Recibe Resultado | Sincronía | Ruta Alternativa / Bypass |
|---|---|---|---|---|---|---|---|
| **STT** | `engine/audio_core.py` | `STTEngine` | `transcribe_audio` | `CalibratedVoiceCaptureEngine` | `modo_voz.py` | Síncrona (hilo) | Entrada de texto por consola |
| **Bucle Voz** | `interfaces/modo_voz.py` | Procedural | `iniciar_modo_voz` | `main.py:run_voice_mode` | Altavoces / TTS | Síncrona | `run_demo_mode()` |
| **Despacho Central** | `core/local_agent/local_agent.py` | `JessycaLocalAgent` | `interact` | `modo_voz.py` | `modo_voz.py` | Síncrona | `core/orchestrator_adapter.py` |
| **Planificación** | `core/dialogue/action_planner.py` | `ActionPlanner` | `create_plan` | `SystemCoordinator4` | `CollaborationEngine` | Síncrona | Bypasseado para comandos directos de voz |
| **Ejecución Skills** | `core/skills/skill_manager.py` | `SkillManager` | `execute_skill` | `JessycaLocalAgent` | `JessycaLocalAgent` | Síncrona | Invocación directa en tests unitarios |
| **Control Windows** | `core/skills/builtin/windows/apps_skill.py` | `WindowsAppsSkill` | `execute` | `SkillManager` | `ExecutionVerifier` | Síncrona | `ComputerUseAdapter` (en IntegrationHub) |
| **Verificación** | `core/execution/execution_verifier.py` | `ExecutionVerifier` | `verify_execution` | `WindowsAppsSkill` / Dispatcher | `JessycaLocalAgent` | Síncrona | Fallback permisivo en `StateChangedStrategy` |
| **TTS** | `engine/audio_core.py` | `VoiceSpeaker` | `speak` | `modo_voz.py` | Altavoces OS | Síncrona | `print` en consola |

---

## 2. ANÁLISIS DEL ORCHESTRATOR

### Situación Técnica Actual
El análisis de código reveló una dualidad de orquestadores en el repositorio:
1. `core/orquestador.py` (`ejecutar_orden_texto`):
   - Es el orquestador procedimental monolítico de versiones previas.
   - Analiza patrones de regex y heurísticas para llamar a navegadores o procesos.
   - **Estado:** **AISLADO / LEGACY**. No es instanciado ni llamado por `main.py` ni por `interfaces/modo_voz.py`.
2. `core/orchestrator_adapter.py`:
   - Diseñado para conectar eventos del Event Bus (`UtteranceFinal`) con la ejecución del agente.
   - En su inicializador ejecuta:
     ```python
     self._orchestrator = orchestrator or JessycaLocalAgent.get_instance()
     ```
   - Cuando recibe una locución, delega directamente en `JessycaLocalAgent.interact()`.

### Clasificación: **PARCIAL / REDUNDANTE**
- El verdadero centro de orquestación en producción activa es **`JessycaLocalAgent`**.
- La existencia de `core/orquestador.py` genera confusión conceptual, sugiriendo la presencia de una autoridad central que en la práctica está inactiva.

---

## 3. ANÁLISIS DE LOCALAGENT

### Responsabilidades Actuales de `JessycaLocalAgent`:
- **Gestión de Sesión:** `SessionManager` y control de turnos conversacionales.
- **Control de Calidad:** `QualityGate` para sanear entradas de texto.
- **Extracción de Intenciones:** `_extract_intent_and_entities` mapea el texto a intents predefinidos.
- **Evaluación de Riesgo:** `_evaluate_risk` consulta a `RiskEngine` y `SecurityPolicy`.
- **Gestión de Confirmaciones:** Maneja el estado `AWAITING_CONFIRMATION` para comandos peligrosos.
- **Selección de Herramientas / Skills:** `_map_intent_to_tool` y `_select_skill_for_intent` asocian intenciones con nombres de skills nativas.
- **Despacho y Ejecución:** Llama directamente a `SkillManager.execute_skill()`.
- **Generación Conversacional:** Si no es un comando de acción o si es una consulta general, invoca al `ConversationalHandler` (respaldado por `gemma4:e4b`).

### Solapamiento Crítico:
> **¿LocalAgent está haciendo trabajo que debería pertenecer al Orchestrator, ActionPlanner o Skills?**

**Sí.** `JessycaLocalAgent` ha absorbido las responsabilidades de:
1. **Orchestrator:** Decide si una entrada es conversación, consulta o comando operativo, y enruta el flujo.
2. **ActionPlanner:** Realiza el mapeo directo entre intención y acción sin consultar al planificador formal.
3. **Execution Gatekeeper:** Evalúa el riesgo y solicita confirmaciones de seguridad.

---

## 4. ANÁLISIS DE ACTIONPLANNER

### Módulo: `core/dialogue/action_planner.py`
- **Invocadores:** Es invocado principalmente por `SystemCoordinator4` en `core/coordination/` y dentro de pruebas unitarias.
- **Principio Fundamental:** Cumple estrictamente la regla `PLANIFICAR != EJECUTAR`.
- **Tipo de Acciones:** Emite objetos `ActionPlan` compuestos por pasos discretos `ActionIntentContract` (`ExecutionGate`, `ExecutionSpec`).
- **Ejecución Directa:** **No ejecuta**. No tiene imports de `win32gui`, `subprocess`, `os` ni `pyautogui`.
- **Paso por Seguridad:** Diseña el contrato incluyendo el nivel de riesgo y las restricciones (`requires_confirmation`, `allowed_parameters`), pero la validación final recae en quien ejecuta el plan (`ExecutionDispatcher`).

### Clasificación: **PLANIFICADOR PURO**
- Su diseño es arquitectónicamente impecable como generador de contratos declarativos.
- Su problema actual es de **desconexión del flujo directo de voz**: las órdenes atómicas de voz no pasan por él, sino que son resueltas de forma cableada en `LocalAgent`.

---

## 5. AUDITORÍA DE COMPUTER USE

### Módulo: `core/integration/adapters/computer_use_adapter.py`
- **Dependencia y Conexión:** Se encuentra registrado bajo `IntegrationHub` (`tools/desktop/` y `core/integration/`).
- **Capacidades Soportadas:**
  - Mouse: `move(x, y)`, `click(button)`, `double_click()`, `mouse_down()`, `mouse_up()`, `scroll(amount)`.
  - Teclado: `write_text(text)`, `press_key(key)`, `hotkey(keys)`.
  - Ventanas y Pantalla: `get_screenshot()`, `get_active_window()`, `list_windows()`, `focus_window()`.
- **Control de Seguridad:**
  - Teclado restringido por lista blanca `_ALLOWED_KEYS` (previene inyección de secuencias no autorizadas).
  - No ejecuta comandos shell directos.
- **Comportamiento de Verificación:**
  - Cada operación devuelve sistemáticamente `ExecutionEvidence(verified=False, verification_required=True)`.
  - Obliga a que cualquier llamador ejecute una verificación visual o de proceso a posteriori.
- **Ruta de Ejecución en Modo Voz:**
  - **AISLADO.** El modo voz ejecuta las operaciones mediante las Skills nativas (`windows.apps`, `windows.media`), sin invocar `ComputerUseAdapter`.

---

## 6. AUDITORÍA DE SKILLS NATIVAS

### Revisión de Skills Principales

```text
Skill Nativas
  │
  ├── windows.apps (core/skills/builtin/windows/apps_skill.py)
  │     ├── launch_app  ──> win32process / psutil ──> ProcessExistsVerificationStrategy
  │     ├── close_app   ──> psutil terminate     ──> ProcessTerminatedVerificationStrategy
  │     └── focus_window──> win32gui SetForeground──> StateChangedVerificationStrategy
  │
  ├── windows.media (core/skills/builtin/windows/media_skill.py)
  │     ├── set_volume  ──> pycaw AudioEndpointVolume ──> StateChangedVerificationStrategy
  │     └── mute        ──> pycaw MuteToggle          ──> StateChangedVerificationStrategy
  │
  ├── windows.clipboard (core/skills/builtin/windows/clipboard_skill.py)
  │     ├── get_text    ──> win32clipboard / pyperclip ──> Inmediata
  │     └── set_text    ──> win32clipboard / pyperclip ──> StateChangedVerificationStrategy
  │
  └── browser.youtube (core/skills/builtin/browser/youtube_skill.py)
        ├── play_video  ──> BrowserSessionManager / URL ──> StateChangedVerificationStrategy
        └── search      ──> BrowserSessionManager / URL ──> StateChangedVerificationStrategy
```

### Mecanismos de Ejecución y Seguridad:
1. **Idempotencia:** Todas las skills implementan verificación de estado previo mediante `IdempotencyGuard`. Si una ventana ya está en foco o una app ya está abierta, no se duplica la acción.
2. **Win32 / UIA:** `windows.apps` utiliza Win32 directo (`win32gui`, `win32process`). El backend avanzado de `WindowsUIAutomationBackend` (`tools/desktop/ui_backend.py`) está disponible en el repositorio pero no está integrado como motor de ejecución dentro de `apps_skill.py`.

---

## 7. ANÁLISIS DE DUPLICACIONES

Se han detectado las siguientes redundancias funcionales en la base de código:

| Función | Componente A | Componente B | ¿Misma Responsabilidad? | Ruta Activa | Autoridad Recomendada |
|---|---|---|---|---|---|
| **Lanzar Aplicación** | `core/skills/builtin/windows/apps_skill.py` | `core/integration/adapters/jarvis_adapter.py` | Sí (arranque de ejecutable) | `apps_skill` | `apps_skill` (Nativa) |
| **Control de Ventanas** | `core/skills/builtin/windows/apps_skill.py` | `core/integration/adapters/computer_use_adapter.py` | Sí (encontrar y enfocar HWND) | `apps_skill` | `apps_skill` (Nativa) |
| **Control de Volumen** | `core/skills/builtin/windows/media_skill.py` | `core/integration/adapters/jarvis_adapter.py` | Sí (control de endpoint de audio) | `media_skill` | `media_skill` (Nativa) |
| **Navegación Web** | `core/skills/builtin/browser/` | `core/orquestador.py` (legacy) | Sí (abrir URLs en navegador) | `browser.*` | `browser.*` (Nativa) |
| **Planificación** | `core/local_agent/local_agent.py` (`_map_intent_to_tool`) | `core/dialogue/action_planner.py` (`create_plan`) | Sí (selección de acción para intención) | `local_agent` (cableado) | `ActionPlanner` |
| **Orquestación de Voz** | `interfaces/modo_voz.py` + `JessycaLocalAgent` | `core/orquestador.py` | Sí (procesar orden de usuario) | `modo_voz` + `LocalAgent` | `JessycaLocalAgent` |

---

## 8. AUDITORÍA DE SEGURIDAD END-TO-END

### Componentes de Control de Seguridad:
- **`SecurityPolicy` (`core/security/security_policy.py`)**: Define listas de comandos permitidos, denegados y perfiles de autorización.
- **`RiskEngine` (`core/security/risk_engine.py`)**: Asigna niveles de riesgo deterministas (`READ_ONLY`, `SAFE_WRITE`, `IMPACTFUL`, `DESTRUCTIVE`).
- **`EmergencyStopManager` (`core/security/emergency_stop.py`)**: Mecanismo global que interrumpe inmediatamente cualquier acción si se detecta la palabra o señal de aborto.
- **`AuditLogger` (`core/security/audit_logger.py`)**: Registra cada evaluación, aprobación, rechazo y ejecución con timestamp y nivel de riesgo.

### Clasificación de Rutas de Seguridad:
1. **Modo Voz -> `JessycaLocalAgent` -> Skills Nativas**: **SEGURO CON CONFIRMACIÓN**. Comandos de impacto (`close_app`, etc.) requieren confirmación verbal.
2. **`ComputerUseAdapter` (Mouse/Teclado)**: **RIESGO MEDIO**. Cuenta con lista blanca de teclas, pero si fuera invocado sin pasar por `RiskEngine`, podría escribir texto en campos no deseados. Actualmente está protegido por no estar activo en la ruta de voz.
3. **MCP Server (`server/app.py`)**: **SEGURO (SANDBOX)**. Utiliza `SecureExecutionPipeline` con un ejecutor acotado (`StubExecutionBoundary`), por lo que no puede manipular el OS real.
4. **`core/orquestador.py` (Legacy)**: **RIESGO ALTO / BYPASS POTENCIAL**. Carece de integración formal con `RiskEngine` de 4.0; depende de regex simples. Afortunadamente está completamente desconectado de la ruta activa.

---

## 9. AUDITORÍA DE EXECUTION VERIFIER Y "FALSE SUCCESS"

### Diagnóstico del Problema Histórico de YouTube / Multimedia
El problema donde el asistente confirma: *"Ya está reproduciendo"* sin que la acción haya ocurrido se origina en la diferencia semántica entre:
- **`COMMAND ACCEPTED`**: La API del navegador o el comando de shell aceptó la URL.
- **`ACTION ACTUALLY COMPLETED`**: El elemento `<video>` en el DOM está en estado `playing` con `currentTime > 0` y emitiendo audio en Windows.

### Análisis de Estrategias de Verificación:
1. **`ProcessExistsVerificationStrategy`**: **ROBUSTA**. Verifica `psutil.pid_exists(pid)` e inspecciona el estado del proceso en Windows.
2. **`ProcessTerminatedVerificationStrategy`**: **ROBUSTA**. Verifica que el proceso ya no figure en la tabla de procesos.
3. **`StateChangedVerificationStrategy`**: **VULNERABLE A FALSE SUCCESS**.
   - Código en `core/execution/execution_verifier.py`:
     ```python
     is_verified = bool(parameters.get("verified", True))
     ```
   - Si la skill que interactúa con el navegador devuelve `parameters["verified"] = True` tras simplemente invocar `webbrowser.open(url)`, `ExecutionVerifier` da por verificada la acción sin comprobar si la pestaña cargó, si el navegador tenía foco o si el reproductor multimedia inició la reproducción.

---

## 10. AUDITORÍA DE MODEL ROUTER Y MODO VOZ

### Estado y Posicionamiento del ModelRouter:
- **Modo Voz Interactivo:** Permanece **estrictamente fijado** a `gemma4:e4b` a través de `ConversationalHandler` y `interfaces/modo_voz.py`. No hay mutación de modelo en tiempo de ejecución de voz, preservando latencia mínima y estabilidad térmica/VRAM.
- **Delegación de Segundo Plano (`AUTO_ROUTE_MODEL`):** `ModelManager.generate()` detecta la constante `"auto-routed"` y delega de manera segura en `ModelRouter.route()`, con fallback automático al modelo default si el router no está disponible o falla la resolución.
- **Nombres de Modelos Consolidados:** Las inconsistencias previas (`ollama/` prefixes, nombres de visión) fueron resueltas en la Fase 76.x. Los identificadores coinciden con `ModelRegistry`.

---

## 11. AUDITORÍA DE ARE Y JARVIS-PY

### Estado de Integraciones:
- **`AREAdapter` (`core/integration/adapters/are_adapter.py`)**:
  - Implementado y probado unitariamente.
  - Ofrece capacidades de análisis de causa raíz algorítmica y reparación de planes.
  - **Llamadas activas desde Voz/LocalAgent/ActionPlanner:** **NINGUNA**. Permanece aislado en `IntegrationHub`.
- **`JarvisAdapter` (`core/integration/adapters/jarvis_adapter.py`)**:
  - Implementado y probado unitariamente.
  - Ofrece control de volumen, estado del sistema y lanzamiento de apps.
  - Duplica directamente las habilidades nativas de JESSYCA.
  - **Llamadas activas desde Voz/LocalAgent/ActionPlanner:** **NINGUNA**. Permanece aislado en `IntegrationHub`.

---

## 12. AUDITORÍA DE MCP (MODEL CONTEXT PROTOCOL)

### Módulo: `server/app.py`
- **Exposición:** Expone endpoints HTTP y SSE bajo el protocolo MCP.
- **Herramientas Expuestas:** Comandos de ejecución e inspección controlada.
- **Ruta de Ejecución:** Pasa por `SecureExecutionPipeline` conectado a un `StubExecutionBoundary`.
- **Interacción con Modo Voz:** **DESACOPLADA**. El servidor MCP corre de manera independiente y no comparte contexto ni memoria de ejecución inmediata con el bucle de `modo_voz.py`.
- **Riesgo de Bypass:** No introduce bypass en el sistema operativo real porque sus herramientas en producción están limitadas al stub seguro.

---

## 13. AUDITORÍA DE ASYNCIO, SLEEPS Y CONCURRENCIA

### Inspección de Bloqueos y Prácticas de Concurrencia:
1. **Llamadas Bloqueantes `time.sleep` en Hilo Principal:**
   - En `core/skills/builtin/windows/apps_skill.py` (`_type_into_app`):
     - Contiene `time.sleep(0.3)` y `time.sleep(0.2)` para espaciar pulsaciones Win32. Al ejecutarse en el flujo síncrono de `LocalAgent`, congela temporalmente el hilo principal durante medio segundo.
   - En `interfaces/modo_voz.py`:
     - Contiene bucles con `time.sleep(0.05)` para polling de audio.
2. **Manejo de Hilos:**
   - La captura de audio corre correctamente en un hilo desacoplado (`threading.Thread(target=self._listen_worker)`).
   - El adaptador de orquestación `core/orchestrator_adapter.py` utiliza `asyncio.to_thread()` para encapsular la ejecución síncrona de `JessycaLocalAgent` sin bloquear el Event Bus asíncrono.
3. **Recomendación:** Migrar los `time.sleep` dentro de las skills a esperas asíncronas o delegar la ejecución completa de la skill a un worker pool.

---

## 14. MAPA DE ARQUITECTURA REAL

```text
====================================================================================================
                                 JESSYCA 4.0 — ARQUITECTURA REAL
====================================================================================================

                       [ USUARIO / MICRÓFONO ]
                                  │
                                  ▼
                   CalibratedVoiceCaptureEngine
                    (Hilo Worker + Queue Audio)
                                  │
                                  ▼
                        STTEngine / Faster-Whisper
                      (Transcripción a Texto)
                                  │
                                  ▼
                        interfaces/modo_voz.py
                      (Bucle Síncrono de Voz)
                                  │
                                  ▼
                    ┌───────────────────────────┐
                    │     JessycaLocalAgent     │ <─── [AUTORIDAD CENTRAL DE FACTO]
                    └───────────────────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         │ (Consulta General)     │ (Comando Directo)      │ (Plan Complejo)
         ▼                        ▼                        ▼
ConversationalHandler       Mapeo Directo            ActionPlanner
   [gemma4:e4b]            (Intent-to-Tool)       (PLANIFICAR != EJECUTAR)
         │                        │                        │
         │                        ▼                        ▼
         │                 RiskEngine &           ExecutionDispatcher
         │                SecurityPolicy                   │
         │                        │                        │
         │                        ▼                        │
         │                  SkillManager <─────────────────┘
         │                        │
         │         ┌──────────────┴──────────────┐
         │         ▼                             ▼
         │   windows.apps / media         browser.youtube
         │   (Win32 / pycaw / psutil)    (BrowserSession)
         │         │                             │
         │         └──────────────┬──────────────┘
         │                        ▼
         │                ExecutionVerifier
         │          (Process / State Strategies)
         │                        │
         └────────────────────────┼────────────────────────┐
                                  │                        │
                                  ▼                        ▼
                          VoiceSpeaker / TTS       AuditLogger / Memory
                            (Camila Neural)
                                  │
                                  ▼
                         [ ALTAVOCES / USUARIO ]

────────────────────────────────────────────────────────────────────────────────────────────────────
COMPONENTES EN STANDBY / AISLADOS:
 - core/orquestador.py: Desconectado de modo voz (Legacy v1/v2).
 - ComputerUseAdapter: Implementado en IntegrationHub, no llamado por modo voz.
 - AREAdapter / JarvisAdapter: Aislados en IntegrationHub, sin llamadas activas.
 - MCP Server: Ejecutándose en puerto independiente con StubExecutionBoundary.
====================================================================================================
```

---

## 15. MATRIZ FINAL DE RESPONSABILIDADES

| Componente | Responsabilidad Real Actual | Ruta Activa | Duplicación | Seguridad | Verificación | Estado |
|---|---|---|---|---|---|---|
| **Orchestrator** (`orquestador.py`) | Ninguna en producción moderna (legacy regex parser). | Inactiva | Con `JessycaLocalAgent` | Riesgo Alto si se activara | Ninguna | **AISLADO / LEGACY** |
| **LocalAgent** (`JessycaLocalAgent`) | Orquestación general, clasificación, mitigación de riesgo, despacho. | Activa (Voz y Demo) | Con Orchestrator y ActionPlanner | Seguro con Confirmación | Delega en Verifier | **CENTRAL DE FACTO** |
| **ActionPlanner** | Generación de planes declarativos (`ActionIntentContract`). | Inactiva en comandos simples de voz | Con `LocalAgent._map_intent_to_tool` | Diseña restricciones | No ejecuta | **PARCIAL / PURO** |
| **ComputerUseAdapter** | Primitivas de bajo nivel de mouse, teclado y ventanas. | Inactiva en modo voz | Con `windows.apps` y `JarvisAdapter` | Restringido por lista blanca | Emite `verified=False` | **AISLADO** |
| **Skills Nativas** | Ejecución determinista sobre APIs de Windows y navegador. | Activa | Con `JarvisAdapter` | Integrado con RiskEngine | Estrategias específicas | **CENTRAL EJECUCIÓN** |
| **ExecutionVerifier** | Certificación de éxito post-ejecución sobre el sistema operativo. | Activa | Ninguna | Previene falsos positivos | Proceso, Archivo, Estado | **CENTRAL VERIFICACIÓN** |
| **ModelRouter** | Selección dinámica de LLMs según complejidad de tarea. | Activa solo en background / auto-route | Ninguna | Validado en Fase 76.x | Fallback a default | **PARCIAL CONTROLADO** |
| **IntegrationHub** | Registro y ciclo de vida de adapters externos. | Activa en arquitectura | Ninguna | Pasarela de adapters | No aplica | **ACTIVO (SOPORTE)** |
| **AREAdapter** | Diagnóstico algorítmico y reparación de planes. | Inactiva en modo voz | Ninguna | Solo lectura / diagnóstico | No aplica | **AISLADO** |
| **JarvisAdapter** | Automatización externa de apps, volumen y sistema. | Inactiva en modo voz | Con Skills Nativas (`windows.*`) | Parcial | No aplica | **REDUNDANTE / AISLADO** |
| **MCP Server** | Exposición de herramientas vía estándar MCP a clientes externos. | Activa en server HTTP | Con Skills internas | Aislado con Stub Boundary | No aplica | **AISLADO SEGURO** |

---

## 16. CLASIFICACIÓN DE PROBLEMAS

### P0 — CRÍTICO (Ninguno detectado en la ruta de ejecución activa)
- No se detectaron fallas críticas que permitan ejecución no autorizada o bypass destructivo sin confirmación.

### P1 — IMPORTANTE (Requieren resolución arquitectónica previa a versión final)
1. **Ambigüedad de la Autoridad de Orquestación:** `JessycaLocalAgent` actúa de facto como el orquestador principal, mientras `core/orquestador.py` permanece como código muerto en el repositorio. Debe formalizarse la autoridad unificada.
2. **Bypass Arquitectónico de `ActionPlanner`:** El modo voz asocia intenciones a herramientas mediante código hardcodeado en `LocalAgent` en lugar de emitir un contrato de ejecución formal a través de `ActionPlanner`.
3. **Vulnerabilidad a "False Success" en `StateChangedVerificationStrategy`:** Verificación permisiva basada en `parameters.get("verified", True)` en lugar de inspeccionar estados observables del sistema operativo o navegador.

### P2 — MEJORA (Optimización y coherencia funcional)
1. **Llamadas Bloqueantes `time.sleep`:** Presencia de pausas síncronas en `apps_skill._type_into_app` y bucles de audio.
2. **Capacidades UIA Desconectadas:** `WindowsUIAutomationBackend` implementa una potente inspección por accesibilidad pero no está conectado a las skills activas de Windows.
3. **Duplicación de Capacidades en `JarvisAdapter`:** Funciones de volumen y aplicaciones duplicadas que deben marcarse formalmente como descartadas en favor de las skills nativas.

### P3 — FUTURO (Evolución posterior)
1. **Conexión de `AREAdapter`:** Integrar el diagnóstico algorítmico de ARE como estrategia de contingencia cuando `ExecutionVerifier` detecte fallos reiterados.
2. **Eliminación Definitiva de Archivos Legacy:** Depuración y retiro formal de `core/orquestador.py`.

---

## 17. RESPUESTAS A LAS 13 PREGUNTAS DE ÉXITO

Basado estrictamente en evidencia de código auditado:

1. **¿Quién recibe la intención?**
   `JessycaLocalAgent` a través de su método `interact(req)` invocado por el bucle de voz en `interfaces/modo_voz.py`.
2. **¿Quién decide qué hacer?**
   `JessycaLocalAgent` mediante `_extract_intent_and_entities()` y `_select_skill_for_intent()`.
3. **¿Quién planifica?**
   Para comandos simples de voz, `LocalAgent` mapea directamente la acción de forma cableada. Para tareas complejas, `ActionPlanner` (`core/dialogue/action_planner.py`).
4. **¿Quién ejecuta?**
   `SkillManager` invocando a las Skills nativas específicas (`WindowsAppsSkill`, `WindowsMediaSkill`, `BrowserYouTubeSkill`).
5. **¿Quién aplica seguridad?**
   `RiskEngine` y `SecurityPolicy` consultados por `LocalAgent` antes del despacho, con soporte de `EmergencyStopManager`.
6. **¿Quién verifica?**
   `ExecutionVerifier` (`core/execution/execution_verifier.py`) aplicando estrategias sobre procesos y filesystem.
7. **¿Quién informa el resultado?**
   `interfaces/modo_voz.py` transmitiendo el texto de respuesta a `VoiceSpeaker` / `TTSManager` (Camila Neural).
8. **¿Qué componentes están duplicados?**
   `core/orquestador.py` vs `JessycaLocalAgent`; `LocalAgent._map_intent_to_tool` vs `ActionPlanner`; `JarvisAdapter` vs Skills nativas (`windows.apps`, `windows.media`).
9. **¿Qué rutas pueden producir FALSE SUCCESS?**
   Cualquier invocación que recurra a `StateChangedVerificationStrategy` sin comprobar el estado real de la ventana/navegador (ej. apertura de URLs de YouTube).
10. **¿Existe algún bypass de seguridad?**
    No en la ruta activa. La ruta legacy `core/orquestador.py` carece de `RiskEngine`, pero está inactiva.
11. **¿Qué componentes están realmente activos?**
    `modo_voz`, `CalibratedVoiceCaptureEngine`, `STTEngine`, `JessycaLocalAgent`, `SkillManager`, Skills Nativas (`windows.*`, `browser.*`), `ExecutionVerifier`, `RiskEngine`, `SecurityPolicy`, `ModelManager` (`gemma4:e4b`), `VoiceSpeaker`.
12. **¿Qué componentes están aislados?**
    `core/orquestador.py`, `ComputerUseAdapter`, `AREAdapter`, `JarvisAdapter`, `WindowsUIAutomationBackend`.
13. **¿Cuál debería ser la autoridad de cada capa?**
    - **Orquestación y Diálogo:** `JessycaLocalAgent` (o formalizado como `SystemOrchestrator`).
    - **Planificación Declarativa:** `ActionPlanner`.
    - **Despacho y Gobernanza:** `ExecutionDispatcher` + `SecurityPolicy` + `RiskEngine`.
    - **Ejecución de Acciones:** `SkillManager` (Skills Nativas como autoridad primaria).
    - **Validación de Resultados:** `ExecutionVerifier` (con inspección real obligatoria).

---

## 18. REPORTE DE TESTS EJECUTADOS

Para validar el análisis técnico y el comportamiento del runtime de ejecución, se ejecutó la suite de pruebas de los componentes clave:

```text
TESTS EJECUTADOS: 722
PASSED: 721
FAILED: 1
SKIPPED: 0
```

### Detalle del Fallo Documentado:
- **Test:** `tests/execution/test_apps_duplicate_execution_fix.py::test_01_single_request_single_execution`
- **Fallo:** `AssertionError: assert 6 == 1 (records[0].actual_execution_count == 1)`
- **Causa Raíz:** Acumulación de estado en el singleton `ApplicationSessionManager` al correr la suite completa de tests de forma continua en el mismo proceso de pytest (el contador de ejecuciones de `notepad` acumuló llamadas de pruebas previas).
- **Impacto en la Arquitectura Auditada:** **No afecta la arquitectura de producción.** Al ejecutarse de forma aislada, el test pasa. Sin embargo, evidencia que `ApplicationSessionManager` conserva estado en memoria global que requiere reseteo explícito en fixtures de prueba.

---

## 19. RECOMENDACIÓN TÉCNICA PARA FASE 80

La Fase 80 no debe agregar nuevas herramientas ni dependencias externas. Debe concentrarse exclusivamente en la **Consolidación y Limpieza de la Autoridad de Ejecución**:
1. **Unificar la Autoridad de Despacho:** Establecer formalmente a `JessycaLocalAgent` como la autoridad de orquestación y deprecación controlada de `core/orquestador.py`.
2. **Conectar `ActionPlanner` en el Flujo de Voz:** Hacer que `LocalAgent` no despache directamente de forma cableada, sino que genere un `ActionIntentContract` a través de `ActionPlanner`, asegurando que toda acción cumpla la trazabilidad declarativa.
3. **Cerrar la Brecha de "False Success":** Reemplazar la validación permisiva de `StateChangedVerificationStrategy` en el reproductor de YouTube y control de ventanas por una verificación real basada en el proceso activo y el HWND correspondiente.

