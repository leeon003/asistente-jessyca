# JESSYCA 4.0 — FASE 1: AUDITORÍA DE MÓDULOS DUPLICADOS Y REDUNDANTES

**Fecha:** 16 de Octubre de 2026  
**Rama:** `feature/jessyca-4-agent`  
**Objetivo:** Identificar con evidencia estricta los módulos duplicados, responsabilidades solapadas y subsistemas redundantes, proponiendo un plan de consolidación seguro respaldado por pruebas de regresión.

---

## 1. INVENTARIO DE DUPLICIDADES CONFIRMADAS

### 1.1. Orquestación: `core/orquestador.py` vs `core/local_agent/local_agent.py`
- **Diagnóstico:**
  - `core/orquestador.py` contiene `ejecutar_orden_texto(texto)` y `procesar_orden(texto)`. Es una reliquia procedimental v1/v2 basada en expresiones regulares (`if "abre" in texto:`).
  - `core/local_agent/local_agent.py` (`JessycaLocalAgent`) es el orquestador real y cognitivo de producción, gobernado por `RiskEngine`, `PermissionManager`, `JDEAuthorityGate` e integrado con Ollama y el motor de intenciones SAI.
- **Evidencia de Consumo:**
  - `interfaces/modo_voz.py`: Invoca **exclusivamente** a `JessycaLocalAgent`.
  - `interfaces/modo_texto.py`: Invoca a `JessycaLocalAgent` como flujo principal, pero mantiene a `ejecutar_orden_texto` en una cláusula de respaldo (`except Exception:`).
  - Pruebas unitarias: `tests/test_orquestador_clarification.py` y `tests/test_consolidation_phase10.py` aún testean `core/orquestador.py`.
- **Plan de Consolidación:**
  - Eliminar el bloque de fallback a `core/orquestador.py` en `interfaces/modo_texto.py` y reemplazarlo por un manejo de error gobernado dentro de `JessycaLocalAgent`.
  - Migrar las aserciones de aclaración contextual hacia `test_conversational_handler.py`.
  - Aislar `core/orquestador.py` para retiro en Fase 2.

---

### 1.2. Seguridad: `core/seguridad.py` vs Arquitectura Central de Seguridad
- **Diagnóstico:**
  - `core/seguridad.py` (52 líneas) implementa `requiere_confirmacion()`, `confirmar_con_usuario()` y `registrar_auditoria()`.
  - En JESSYCA 3.0/4.0 la seguridad se encuentra formalmente unificada y distribuida en:
    - `core/risk_engine.py` (`RiskEngine` modular con 8 reglas de evaluación y niveles `SAFE`, `WARNING`, `DANGEROUS`, `CRITICAL`).
    - `core/permission_manager.py` (`PermissionManager` con toma de decisiones deterministas `ALLOW`, `REQUIRE_CONFIRMATION`, `DENY`).
    - `core/jde/authority.py` (`JDEAuthorityGate` para control de modos y privilegios).
    - `core/execution/execution_verifier.py` (Anti-False Success).
- **Evidencia de Consumo:**
  - `core/seguridad.py` es consumido **única y exclusivamente** por `core/orquestador.py`. Ningún otro archivo en todo el proyecto lo importa.
- **Plan de Consolidación:**
  - Al consolidar `core/orquestador.py`, `core/seguridad.py` queda con cero consumidores y podrá retirarse formalmente sin ningún impacto en la arquitectura de seguridad real.

---

### 1.3. Planificación: `core/planner.py` vs `core/planning/` vs `SaiIntentEngine`
- **Diagnóstico:**
  - `core/planner.py`: Contiene `AIPlanner`, `ExecutionPlan` y `SubTask`. Genera planes textuales y ordenación con el algoritmo de Kahn.
  - `core/planning/`: Módulo moderno (`PlanningEngine`, `PlanBuilder`, `PlanExecutor`, `PlanValidator`), pero sin enlace en el pipeline activo.
  - `core/intent/sai_intent_engine.py`: Motor implementado en Fase 0 que descompone comandos naturales compuestos en pasos estructurados (`PlannedSubgoal`) y llamadas nativas a herramientas.
- **Evidencia de Consumo:**
  - `core/planner.py` es consumido por `core/executor.py` y suites de prueba topológica (`test_planner_topological.py`).
  - `core/planning/` solo es consumido por sus propias pruebas unitarias (`tests/planning/test_planning_engine.py`).
- **Plan de Consolidación:**
  - Unificar la definición de pasos compuestos en el modelo formal de submetas de SAI (`PlannedSubgoal` / `ExecutionPlan`).
  - Dirigir `core/executor.py` hacia el planificador unificado y retirar `core/planner.py` y `core/planning/` de forma sincronizada.

---

### 1.4. Automatización de Aplicaciones: `skills/apps.py` vs `skills/apps_skill.py`
- **Diagnóstico:**
  - `skills/apps.py` (135 líneas): Implementa `AbrirAplicacion` y `CerrarAplicacion` leyendo `config/apps.yaml`.
  - `skills/apps_skill.py` (499 líneas): Implementa `WindowsAppsSkill` (`windows.apps`), que incluye autodescubrimiento en registro de Windows, verificación por HWND con Win32, integración con `ExecutionVerifier`, guardas de idempotencia, y control seguro de escritura con `pyautogui.FAILSAFE = True` y `EmergencyStopManager`.
- **Evidencia de Consumo:**
  - `skills/apps.py` solo se exporta en `skills/__init__.py` en un diccionario de compatibilidad v1 (`"abrir_aplicacion": AbrirAplicacion()`).
  - Todo el flujo del agente principal, `ExecutionDispatcher` y las pruebas e2e consumen `WindowsAppsSkill`.
- **Plan de Consolidación:**
  - Reemplazar las instancias de `AbrirAplicacion` en el diccionario de compatibilidad para que deleguen internamente en `WindowsAppsSkill`.
  - Retirar `skills/apps.py` una vez verificada la compatibilidad de retroalimentación.

---

### 1.5. Búsqueda de Archivos: `skills/archivos.py` vs `skills/files_skills.py`
- **Diagnóstico:**
  - `skills/archivos.py` (56 líneas): Implementa `BuscarArchivo` con `os.walk` recursivo sin comprobación de rutas críticas.
  - `skills/files_skills.py` (828 líneas): Implementa `WindowsFilesSkill` con `FilesSearchSkill`, `FilesReadSkill`, `FilesCreateSkill`, etc., con bloqueo estricto de rutas críticas de Windows (`_is_path_critical`), protección de credenciales y límites de seguridad.
- **Evidencia de Consumo:**
  - `skills/archivos.py` solo está registrado en el diccionario v1 de `skills/__init__.py`.
  - El sistema de producción utiliza `skills/files_skills.py`.
- **Plan de Consolidación:**
  - Mapear `"buscar_archivo"` hacia `FilesSearchSkill` en `skills/__init__.py`.
  - Marcar `skills/archivos.py` como obsoleto sin consumidores activos.

---

### 1.6. Automatización de Escritorio: `tools/desktop/` vs `skills/apps_skill.py` / `core/desktop/`
- **Diagnóstico:**
  - `tools/desktop/` contiene 12 archivos con executors para `pywinauto`, manipulación de ventanas y OCR.
  - `skills/apps_skill.py` y `core/desktop/driver_protocol.py` proveen ejecución directa mediante Win32 API y PyAutoGUI con verificación de evidencia.
- **Evidencia de Consumo:**
  - `tools/desktop/` **SÍ tiene consumidores reales**: `server/pipeline.py` (línea 55), `core/application_session_manager.py` (líneas 28-29) y `core/desktop_synchronization.py` (línea 23).
  - No puede eliminarse en esta fase porque rompería componentes en ejecución del servidor.
- **Plan de Consolidación:**
  - Desacoplar gradualmente `application_session_manager.py` y `server/pipeline.py` hacia `NativeWindowsDriver` y `WindowsAppsSkill`.
  - Mantener `tools/desktop/` como `ACTIVO / LEGADO` hasta completar la migración de la API del servidor.

---

## 2. MATRIZ DE RIESGO DE RETIRO Y PROCEDIMIENTO DE AISLAMIENTO

| Componente Candidato | Riesgo de Rotura | Consumidores Residuales | Procedimiento de Mitigación Previo al Retiro |
| :--- | :--- | :--- | :--- |
| `core/seguridad.py` | Nulo (aislado) | `core/orquestador.py` | Se retirará simultáneamente con `core/orquestador.py`. |
| `core/orquestador.py` | Bajo | `interfaces/modo_texto.py` (fallback) | Reemplazar fallback por `JessycaLocalAgent.get_instance().interact()`. |
| `skills/apps.py` | Nulo | `skills/__init__.py` (alias v1) | Redirigir alias a `WindowsAppsSkill`. |
| `skills/archivos.py` | Nulo | `skills/__init__.py` (alias v1) | Redirigir alias a `WindowsFilesSkill`. |
| `core/planner.py` | Medio | `core/executor.py` | Migrar `core/executor.py` a submetas estructuradas de SAI. |
| `core/planning/` | Bajo | Pruebas aisladas | Certificar que `SaiIntentEngine` cubre todos los casos de uso. |

### Regla Inmutable de la Fase 1
**Ningún archivo ha sido eliminado físicamente en esta fase.** Todos los componentes redundantes han sido identificados con sus consumidores reales y clasificados para su posterior consolidación controlada.
