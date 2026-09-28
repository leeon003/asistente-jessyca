# JESSYCA — Informe Maestro de Consolidación Arquitectónica

## Fecha: 2026-09-27
## Estado Objetivo: CONTROLLED READY (Audit Only)
## Directiva: Prohibido Modificar Código de Producción o Cambiar Invariantes

---

### 1. Resumen Ejecutivo

Este informe consolida la auditoría estructural y de dependencias del sistema **JESSYCA PC** en `D:\JESSYCA 3.0\asistente-jessyca`. 

Tras haber alcanzado y certificado el estado **`FULL E2E — CONTROLLED READY`** con una regresión global del 100% (3,581 pruebas aprobadas), esta fase determinó con precisión:
1. Qué subsistemas se encuentran en el **flujo activo de producción**.
2. Qué componentes operan en modo **sombra (`SHADOW`)** o **controlado (`CONTROLLED`)**.
3. Qué módulos existen exclusivamente para **retrocompatibilidad (`COMPATIBILITY`)** o **pruebas unitarias (`TEST ONLY`)**.
4. Qué duplicaciones funcionales existen y cuál es el plan riguroso de consolidación futura **sin realizar eliminaciones destructivas en esta fase**.

---

### 2. Mapa y Grafo Integral de Dependencias

```text
                                 [ USUARIO ]
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
      [ CLI ]                 [ Open WebUI ]                [ Mobile API ]
  (Terminal Consola)         (HTTP OpenAI-Compat)         (Android REST API)
          │                           │                           │
          │                   [ WebUI Bridge ]                    │
          │               (interfaces/webui_bridge)               │
          │                           │                           │
          └───────────────────────────┼───────────────────────────┘
                                      │
                                      ▼
                           [ JessycaLocalAgent ]
                         (core/agent/local_agent.py)
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
     [ MEMORIA LOCAL ]                               [ MODEL ROUTER ]
  (MemoryScope.AGENT/SESSION)                  ├── ExperimentalRouter (Shadow/Static)
  *Contexto, NO Autoridad*                     └── ModelRouter 2.0 (Smart Routing)
              │                                               │
              └───────────────────────┬───────────────────────┘
                                      │
                                      ▼
                          [ JDE Runtime Binding ]
                       (core/jde/runtime_binding.py)
                       ★ ÚNICA AUTORIDAD DE DECISIÓN ★
                                      │
                     ┌────────────────┴────────────────┐
                     ▼                                 ▼
             [ TAREA SIMPLE ]                  [ TAREA COMPLEJA / FALLO ]
                     │                                 │
                     │                                 ▼
                     │                        [ ARERuntime (ARE) ]
                     │                      (core/are/runtime.py)
                     │                      - Decompose Task (Kahn DAG)
                     │                      - Blast Radius (BFS)
                     │                      - Failure Diagnosis
                     │                      - Recovery Proposal (Max 2)
                     │                                 │
                     │                     [ AREPlanProposal ]
                     │                   *Propuesta, NO Autorización*
                     │                                 │
                     └────────────────┬────────────────┘
                                      │
                                      ▼
                          [ EVALUACIÓN JDE FINAL ]
                       ├── ALLOW (Continuar)
                       ├── DENY (Bloqueo: Cero Efectos Físicos)
                       └── REQUIRE_REVIEW (Espera Confirmación)
                                      │
                                      ▼
                             [ SECURITY LAYER ]
                       ├── RiskEngine (Nivel de Riesgo)
                       ├── PermissionManager (Listas Blancas)
                       └── ExecutionIdempotencyGuard (Anti-Replay)
                                      │
                                      ▼
                      [ HABILIDADES Y ADAPTADORES ]
        ┌─────────────────────────────┼─────────────────────────────┐
        │                             │                             │
        ▼                             ▼                             ▼
  [ Nativas Windows ]         [ Especializados ]          [ Hub Integración ]
  ├── apps_skill              ├── AnyDoc (Documentos)     ├── ORCA/ADE (Worktree)
  ├── windows_skills          ├── Archify (Diagramación)  ├── Jarvis (Disabled)
  ├── windows_media_skill     └── [Legacy: documents]     └── Computer Use (Disab.)
  ├── files_skills
  └── screenshot_skill
        │                             │                             │
        └─────────────────────────────┼─────────────────────────────┘
                                      │
                                      ▼
                            [ ExecutionBoundary ]
                        (Frontera de Aislamiento OS)
                                      │
                                      ▼
                            [ ExecutionVerifier ]
                         ★ VERIFICACIÓN FÍSICA REAL ★
                       (Anti-False Success Obligatorio)
                                      │
                                      ▼
                           [ ActionReceipt / AUDIT ]
                        - SHA-256 Fingerprint Criptográfico
                        - Trazabilidad Inmutable No Repudiable
```

---

### 3. Auditoría de Módulos Críticos y Duplicaciones

#### 3.1. ARE vs Skill Graph Planner
- **Estado Actual:**
  - **ARE (`core/are/`):** Activo en `JessycaLocalAgent` en modo `CONTROLLED`. Gobierna la descomposición semántica y recuperación de tareas complejas.
  - **Skill Graph Planner (`skills/skill_graph_planner.py`):** Utilizado por `skills/skill_graph_executor.py` (`SkillGraphOptimizer`) y para medición de latencia histórica en `SystemCoordinator4`.
- **Duplicación:** Parcial. ARE es semántico y dinámico; Skill Graph Planner es estático y basado en expresiones regulares.
- **Acción:** `KEEP + CONSOLIDATE LATER`. No eliminar en esta fase para preservar la suite de tests de grafos.

#### 3.2. AnyDoc vs documents_skills
- **Estado Actual:**
  - **AnyDoc (`core/anydoc/`):** Certificado en producción. Soporta 18 formatos con parsing AST, metadatos, sandbox estricto y sellado SHA-256 sin conexión a red.
  - **Documents Skills (`skills/documents_skills.py`):** Manejadores básicos en Python. Presenta falso soporte para DOCX/PDF al intentar abrirlos como texto plano UTF-8.
- **Consumidores de `documents_skills`:** `test_initial_skill_catalog.py`, `test_skill_graph.py` y `real_world_benchmark_100.py`.
- **Acción:** `KEEP + COMPATIBILITY WRAPPER`. Mantener el archivo y redirigir transparentemente su método `ejecutar()` hacia AnyDoc en una fase de refactorización posterior.

#### 3.3. Habilidades Nativas de Windows vs Jarvis Adapter
- **Estado Actual:**
  - **Native Windows Skills:** Cubren de forma segura y completa el ciclo de vida de aplicaciones, audio nativo, ventanas, portapapeles y capturas de pantalla.
  - **Jarvis Adapter (`core/integration/adapters/jarvis_adapter.py`):** Duplica el 100% de las operaciones de apps, audio y portapapeles con menor granularidad y dependencias externas innecesarias (`pyperclip`, `psutil`).
- **Consumidores de Jarvis:** Solo `tests/test_jarvis_adapter.py` y el registro de adaptadores del hub (`JARVIS_ENABLED=False`).
- **Acción:** `KEEP IN CONTROLLED STATE + DEPRECATION CANDIDATE`. Mantener deshabilitado por configuración.

#### 3.4. Model Router 2.0 vs Experimental Router
- **Estado Actual:**
  - **Model Router 2.0 (`core/llm/model_router.py`):** Arquitectura formal Smart Routing 2.0 desacoplada (políticas, registro, VRAM governor, consenso).
  - **Experimental Router (`core/llm/experimental_router.py`):** Monolito heurístico que actualmente recibe las peticiones del agente local operando en modo `STATIC` o `SHADOW`.
- **Acción:** `KEEP BOTH`. En la siguiente fase de optimización LLM, absorber la lógica de `ShadowLogger` dentro de `ModelRouter 2.0` y reemplazar `ExperimentalRouter` por una fachada hacia el router 2.0.

#### 3.5. Computer Use
- **Relación Arquitectónica:**
  - Ubicado en `core/integration/adapters/computer_use_adapter.py`.
  - Interactúa a través de `ExecutionBoundary` y `ExecutionVerifier`.
- **Capacidades:**
  - Duplica parcialmente la inspección de ventanas y capturas de pantalla.
  - Aporta **capacidades únicas**: interacción motriz a nivel de coordenadas de píxeles (`computer_use.mouse_interact`), pulsaciones sintéticas de teclado (`computer_use.keyboard_type`) y el bucle perceptivo-motor (`computer_use.perceive_and_act`).
- **Estado y Riesgo de Bypass:**
  - Se encuentra en modo **`CONTROLLED / DISABLED BY DEFAULT`** (`COMPUTER_USE_ENABLED=False`).
  - No puede generar bypass porque toda invocación requiere pasar por el `IntegrationHub` y la frontera de seguridad `ExecutionBoundary`.
- **Acción:** `KEEP CONTROLLED (NO ACTIVAR)`.

#### 3.6. Open WebUI Bridge
- **Flujo:** Open WebUI -> `WebUIBridge` (`interfaces/webui_bridge/app.py`) -> `JessycaLocalAgent` -> `JDE`.
- **Auditoría de Bypass:**
  - El puente `WebUIBridge` es estrictamente seguro: rechaza accesos sin token, mapea las peticiones a `JessycaRequest` y delega exclusivamente en `JessycaLocalAgent`.
  - **Riesgo Arquitectónico Detectado:** Si la interfaz gráfica de usuario de Open WebUI se configura con una conexión paralela directa al puerto de Ollama (`http://localhost:11434`), el usuario podría seleccionar un modelo local no gobernado, eludiendo a JESSYCA Core.
  - **Clasificación:** `PARTIALLY CONNECTED / BYPASS RISK (EXTERNAL CONFIGURATION)`.
- **Acción:** `DOCUMENT & HARDEN`. Documentar que para producción la conexión directa a Ollama debe estar deshabilitada en la configuración del cliente Open WebUI, exponiendo únicamente la URL de `WebUI Bridge`.

#### 3.7. Mobile API
- **Flujo:** Cliente Android -> `Mobile API` (`interfaces/mobile_api/app.py`) -> `JessycaLocalAgent` -> `JDE`.
- **Auditoría de Bypass:**
  - No existe ninguna ruta paralela ni endpoints de ejecución directa.
  - Toda llamada requiere token en `X-Jessyca-Token` y se transforma en un `JessycaRequest` oficial.
- **Clasificación:** `CONNECTED / ZERO BYPASS`.
- **Acción:** `KEEP AS IS`.

---

### 4. Detección y Clasificación de Código

| Componente / Archivo | Estado en Repo | Consumidores Reales | Clasificación | Riesgo de Deprecación |
| :--- | :---: | :--- | :--- | :---: |
| `core/are/` (ARE) | CONTROLLED | `JessycaLocalAgent`, `hub.py`, Tests | **ACTIVE** | N/A (Núcleo) |
| `skills/skill_graph_planner.py` | CONTROLLED | `skill_graph_executor.py`, Tests | **COMPATIBILITY** | Medio (Usado en executor) |
| `core/anydoc/` (AnyDoc) | CONTROLLED | `JessycaLocalAgent`, Tests | **ACTIVE** | N/A (Núcleo) |
| `skills/documents_skills.py` | CONTROLLED | Catálogo general, Tests, Benchmarks | **COMPATIBILITY** | Bajo (Fácil wrapper) |
| `skills/*_skill.py` (Windows) | CONTROLLED | `JessycaLocalAgent`, Core | **ACTIVE** | N/A (Estándar OS) |
| `core/integration/adapters/jarvis_adapter.py` | DISABLED | Solo tests unitarios (`test_jarvis_adapter.py`) | **UNUSED / TEST ONLY** | Bajo (100% reemplazado) |
| `core/llm/model_router.py` (2.0) | CONTROLLED | `ModelManager`, Tests de Smart Routing | **ACTIVE / TARGET** | N/A (Objetivo futuro) |
| `core/llm/experimental_router.py` | SHADOW | `JessycaLocalAgent` (tráfico shadow) | **SHADOW / ACTIVE** | Medio (Tiene telemetría) |
| `core/integration/adapters/computer_use_adapter.py` | DISABLED | Solo tests (`test_computer_use_adapter.py`) | **CONTROLLED (OFF)** | Nulo (Desactivado) |
| `interfaces/webui_bridge/` | CONTROLLED | Clientes WebUI externos | **ACTIVE** | N/A (Canal oficial) |
| `interfaces/mobile_api/` | CONTROLLED | Clientes Android externos | **ACTIVE** | N/A (Canal oficial) |

---

### 5. Matriz Final de Consolidación Arquitectónica

| Componente | Estado Actual | Consumidores | Nivel de Duplicación | Riesgo de Seguridad | Acción Futura Recomendada |
| :--- | :---: | :--- | :--- | :---: | :--- |
| **ARE** | CONTROLLED READY | `JessycaLocalAgent`, Hub, Tests | Ninguna (Es el motor de razonamiento) | Mínimo (Subordinado a JDE) | **KEEP** |
| **Skill Graph Planner** | COMPATIBILITY | `SkillGraphExecutor`, `SystemCoordinator4`, Tests | Solapamiento con ARE | Mínimo | **KEEP + DEPRECATION PLAN** |
| **AnyDoc** | CONTROLLED READY | Agente principal, Procesamiento Docs | Ninguna (Es el estándar integral) | Mínimo (Sandbox estricto) | **KEEP** |
| **documents_skills** | COMPATIBILITY | Catálogo global, Tests iniciales | Duplicación total con AnyDoc | Medio (Sin sandbox ni hash) | **COMPATIBILITY ONLY (WRAP)** |
| **Windows Skills** | CONTROLLED READY | Agente principal, Core | Ninguna (Son las habilidades base) | Mínimo (ExecutionVerifier) | **KEEP** |
| **Jarvis Adapter** | DISABLED | Tests de integración | Duplicación total con Windows Skills | Mínimo (Deshabilitado) | **DEPRECATION CANDIDATE** |
| **Model Router 2.0** | CONTROLLED READY | `ModelManager`, Tests de enrutamiento | Duplicación temporal con Experimental | Nulo (Sin efectos de SO) | **CONSOLIDATE (TARGET ROUTER)** |
| **Experimental Router**| SHADOW | `local_agent.py`, `conversational_handler` | Duplicación temporal con 2.0 | Nulo (Modo Shadow) | **MIGRATE LATER TO 2.0** |
| **Computer Use** | DISABLED | Tests unitarios | Solapamiento parcial con Windows Skills | Medio si se activa sin JDE | **KEEP (CONTROLLED / OFF)** |
| **Open WebUI Bridge** | CONTROLLED READY | Open WebUI Frontend | Ninguna (Es el bridge oficial) | Medio si WebUI apunta a Ollama| **KEEP + HARDEN CONFIG** |
| **Mobile API** | CONTROLLED READY | Cliente Android | Ninguna (Es la API móvil oficial) | Mínimo (Token requerido) | **KEEP** |

---

### 6. Conclusión y Garantía de Invariantes

La arquitectura de JESSYCA PC presenta una clara separación de responsabilidades:
1. **JDE** es y permanece como la **única autoridad decisoria inmutable**.
2. **ARE** está perfectamente subordinado y provee descomposición semántica y diagnóstico de fallos sin violar los límites de autoridad.
3. Las duplicaciones detectadas (`documents_skills`, `jarvis_adapter`, `skill_graph_planner`, `experimental_router`) están completamente identificadas, clasificadas y contenidas sin generar efectos colaterales adversos ni interferir con la estabilidad del sistema.
4. **Ningún archivo fue eliminado ni modificado en esta fase**, garantizando la preservación estricta de la regresión global y la compatibilidad operativa del sistema.
