# JESSYCA 4.0 — FASE 1: AUDITORÍA DE DEPENDENCIAS Y COMPONENTES

**Fecha:** 16 de Octubre de 2026  
**Rama:** `feature/jessyca-4-agent`  
**Entorno:** Windows 10/11 Pro (Host Local) | Python 3.11.9  
**Objetivo:** Estudio exhaustivo del grafo de dependencias, importaciones reales, consumidores, nivel de riesgo y clasificación formal de los componentes bajo auditoría.

---

## 1. MATRIZ DE CLASIFICACIÓN DE COMPONENTES

| Componente | Existencia | Importaciones Reales | Consumidores Principales | Rol en JESSYCA | Compatibilidad Agente 4.0 | Clasificación Formal |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`core/local_agent/`** | Confirmada (11 archivos) | `core.memory`, `core.dialogue`, `core.execution`, `core.intent` | `interfaces/modo_voz.py`, `interfaces/modo_texto.py`, `server/pipeline.py` | Núcleo de orquestación reactiva, diálogo, contexto y despacho del asistente. | Plena (Autoridad operativa de facto). | **ACTIVO** |
| **`core/jde/`** | Confirmada (18 archivos) | `core.audit_logger`, `core.event_bus`, `core.execution` | `local_agent.py`, `authority.py`, pruebas JDE canarias y adversariales | Motor de decisiones deterministas, compuertas de autoridad (SHADOW/CANARY/FULL) e invariantes. | Plena (Gobernanza constitucional). | **ACTIVO** |
| **`core/planner.py`** | Confirmada (1 archivo) | `dataclasses`, `typing` | `core/executor.py`, `core/__init__.py`, tests legacy (`test_planner.py`, `test_planner_topological.py`) | Planificador v1/v2 basado en descomposición heurística de texto y ordenamiento de Kahn. | Obsoleta (No utilizado por `local_agent.py` moderno). | **LEGADO UTILIZADO** |
| **`core/planning/`** | Confirmada (6 archivos) | `core.planning.plan_models`, `core.planning.plan_validator` | `core/__init__.py`, `tests/planning/test_planning_engine.py` | Motor de planes estructurados `PlanningEngine`, `PlanBuilder`, `PlanExecutor`. | Parcial (Sin consumidores en pipeline de producción). | **EXPERIMENTAL** |
| **`core/orquestador.py`** | Confirmada (1 archivo) | `core.seguridad`, `skills` | `interfaces/modo_texto.py` (fallback secundario), `tests/test_orquestador_clarification.py` | Orquestador procedural v1 monolítico con regex simples. | Desacoplado del agente moderno. | **LEGADO UTILIZADO** |
| **`core/seguridad.py`** | Confirmada (1 archivo) | `logging`, `skills.base_skill` | Exclusivamente `core/orquestador.py` | Validador simple v1 de riesgo (1, 2, 3) y prompt de consola `s/n`. | Incompatible con RiskEngine 4.0. | **LEGADO UTILIZADO** |
| **`core/integration/adapters/`** | Confirmada (5 archivos) | `pyautogui`, `psutil`, `win32gui`, `core.execution` | `IntegrationHub`, `skills/computer_use_skill.py`, `core/are/runtime.py` | Adaptadores de interoperabilidad para CUA, ARE, Jarvis y Mobile. | Plena (Gobernado bajo hub). | **ACTIVO** |
| **`tools/desktop/`** | Confirmada (12 archivos) | `pywinauto`, `pyautogui`, `win32gui`, `psutil` | `server/pipeline.py`, `core/application_session_manager.py`, `desktop_synchronization.py` | Herramientas de automatización de interfaz gráfica, OCR e inspección visual. | Alta (Parcialmente redundante con `apps_skill.py`). | **ACTIVO / LEGADO** |
| **`skills/`** | Confirmada (48 archivos) | Sistema Windows, Win32, PyCaw, Subprocess | `local_agent.py`, `skill_registry.py`, `ExecutionDispatcher` | Catálogo canónico de habilidades operativas de JESSYCA (apps, archivos, media, browser). | Plena (Capa de ejecución oficial). | **ACTIVO** |
| **`core/memory/`** | Confirmada (14 archivos) | SQLite, ChroamDB/vector, `core.profile` | `local_agent.py`, `user_profile_manager.py`, `e2e` tests | Motor de memoria a largo plazo, memoria episódica, semántica y detección de contradicciones. | Plena (Memoria persistente unificada). | **ACTIVO** |
| **`core/execution/`** | Confirmada (9 archivos) | `psutil`, `win32gui`, `hashlib`, `time` | Todos los adaptadores, skills, JDE y LocalAgent | Verificación real de ejecución (`ExecutionVerifier`), idempotencia (`IdempotencyGuard`) y anti-false success. | Plena (Garantía crítica del sistema). | **ACTIVO** |

---

## 2. ANÁLISIS DETALLADO POR COMPONENTE

### 2.1. `core/local_agent/`
- **Función:** Es el punto focal del agente interactivo. Gestiona el ciclo completo de diálogo con el usuario (texto y voz), integración con el motor de intenciones SAI, selección de agentes/skills, resolución de aclaraciones contextuales y síntesis de respuestas (`ResponseSynthesizer`).
- **Llamadas y Consumo:** Invocado directamente por `interfaces/modo_voz.py` y como vía primaria en `interfaces/modo_texto.py` y `server/pipeline.py`.
- **Procesos y Recursos:** Hilos de diálogo asíncronos, acceso a memoria vectorial y SQLite, conexión con Ollama.
- **Veredicto:** **ACTIVO** (Pilar central irremplazable).

### 2.2. `core/jde/`
- **Función:** JESSYCA Decision Engine. Es la autoridad constitucional del sistema. Gobierna los estados (`AWAITING_CONFIRMATION`, `EXECUTING`, `COMPLETED`, `DENIED`), los contratos de transición de autoridad (`SHADOW` -> `CANARY` -> `LIMITED` -> `FULL`) y los recibos criptográficos inmutables.
- **Llamadas y Consumo:** Conectado a `local_agent.py`, `ExecutionDispatcher` y verificado en 331 pruebas de regresión.
- **Veredicto:** **ACTIVO** (Pilar de seguridad central).

### 2.3. `core/planner.py`
- **Función:** Generación de `ExecutionPlan` mediante análisis heurístico y ordenamiento topológico (Kahn).
- **Consumo Real:** Consumido únicamente por `core/executor.py` y tests históricos (`test_planner.py`, `test_planner_topological.py`).
- **Problema:** No se comunica con `local_agent.py`. El flujo real de JESSYCA 4.0 planifica secuencias compuestas a través de `SaiIntentEngine` y `SubgoalSynthesizer`.
- **Veredicto:** **LEGADO UTILIZADO** (Candidato a retiro en fases posteriores tras migrar `core/executor.py`).

### 2.4. `core/planning/`
- **Función:** Arquitectura alternativa de planificación estructurada (`PlanningEngine`, `PlanBuilder`, `PlanExecutor`, `PlanValidator`).
- **Consumo Real:** No tiene consumidores en el código de producción activo; solo está referenciado en `core/__init__.py` y probado en `tests/planning/test_planning_engine.py`.
- **Veredicto:** **EXPERIMENTAL** (Código aislado sin impacto en runtime).

### 2.5. `core/orquestador.py`
- **Función:** Orquestador procedural v1 que utiliza expresiones regulares para disparar skills v1 (`abrir_aplicacion`, `cerrar_aplicacion`, `buscar_archivo`).
- **Consumo Real:** Se mantiene únicamente como bloque de respaldo (`except Exception: respuesta = ejecutar_orden_texto(texto)`) en `interfaces/modo_texto.py` y en pruebas unitarias dedicadas (`test_orquestador_clarification.py`).
- **Riesgo:** Si se ejecutara en lugar de `local_agent.py`, eludiría la compuerta de `RiskEngine` y `PermissionManager`.
- **Veredicto:** **LEGADO UTILIZADO** (Requiere formalización de deprecación y reemplazo de fallback en `modo_texto.py`).

### 2.6. `core/seguridad.py`
- **Función:** 52 líneas de código con funciones elementales (`requiere_confirmacion`, `confirmar_con_usuario`, `registrar_auditoria`) que escriben en `logs/auditoria.log`.
- **Consumo Real:** Exclusivamente invocado por `core/orquestador.py`.
- **Veredicto:** **LEGADO UTILIZADO** (Será retirado en conjunto con `core/orquestador.py`).

### 2.7. `core/integration/adapters/`
- **Función:** Provee adaptadores auditados (`ComputerUseAdapter`, `AREAdapter`, `JarvisAdapter`, `MobileControlAdapter`) subordinados a `IntegrationHub`.
- **Consumo Real:** Activo en `skills/computer_use_skill.py`, `core/are/runtime.py` y suites de prueba de computación gráfica.
- **Veredicto:** **ACTIVO**.

### 2.8. `tools/desktop/`
- **Función:** Suite de bajo nivel para automatización de escritorio mediante `pywinauto`, manipulación de ventanas, OCR y captura de pantalla.
- **Consumo Real:** Importado por `server/pipeline.py`, `core/application_session_manager.py` y `core/desktop_synchronization.py`.
- **Veredicto:** **ACTIVO / LEGADO** (Posee solapamiento con `skills/apps_skill.py`, pero sus consumidores activos en el servidor impiden su retiro inmediato).

### 2.9. `skills/`
- **Función:** Conjunto oficial de habilidades nativas (`apps_skill.py`, `files_skills.py`, `windows_skills.py`, `browser_skills.py`, etc.).
- **Consumo Real:** Núcleo de herramientas invocado por `local_agent.py` y orquestadores.
- **Veredicto:** **ACTIVO**.

### 2.10. `core/memory/`
- **Función:** Almacenamiento persistente, memorias a largo plazo, perfil de usuario y control de expiración.
- **Consumo Real:** Invocado por `local_agent.py` y módulos de personalización.
- **Veredicto:** **ACTIVO**.

### 2.11. `core/execution/`
- **Función:** Motor de verificación real (`ExecutionVerifier`), prevención de falsos positivos y control de idempotencia (`IdempotencyGuard`).
- **Consumo Real:** Transversal a toda acción con impacto en el sistema.
- **Veredicto:** **ACTIVO**.
