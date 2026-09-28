# Auditoría de Consumidores: ARE vs Skill Graph Planner

## Fecha de Auditoría: 2026-09-27
## Estado del Sistema: CONTROLLED READY (Audit Only)

---

### 1. Resumen Ejecutivo

Esta auditoría analiza la coexistencia, responsabilidades, consumidores reales y duplicación funcional entre:
1. **ARE (Action Reasoning Engine):** `core/are/` y `core/integration/adapters/are_adapter.py`.
2. **Skill Graph Planner:** `skills/skill_graph_planner.py` y `skills/skill_graph_executor.py`.

El objetivo es determinar qué componente es la autoridad de planificación activa, quién invoca a cada uno en tiempo de ejecución, cuáles son rutas de compatibilidad o de prueba, y definir la recomendación arquitectónica sin eliminar código ni alterar contratos.

---

### 2. Anatomía de Componentes

#### 2.1. ARE (Action Reasoning Engine)
- **Archivos:**
  - `core/are/models.py` (Modelos formales de intención, planes, propuestas y recuperación).
  - `core/are/runtime.py` (`ARERuntime`, orquestador de ciclo de vida subordinado a JDE).
  - `core/integration/adapters/are_adapter.py` (Adaptador de integración del Hub).
- **Responsabilidades:**
  - Descomposición semántica de tareas multi-paso complejas (`are.decompose_task` mediante ordenación topológica con algoritmo de Kahn).
  - Evaluación de viabilidad de planes (`are.evaluate_plan`, cálculo de radio de impacto *blast radius* con BFS inverso).
  - Diagnóstico de fallos de ejecución física (`are.diagnose_failure`, categorización causal de errores).
  - Propuesta de contingencia y recuperación (`are.recover_plan`, respetando el límite estricto de `MAX_RECOVERY_ATTEMPTS = 2`).
- **Límites de Autoridad:**
  - Estrictamente subordinado a JDE.
  - No autoriza ejecución física (`ARE Proposal != Authorization`).
  - No ejecuta herramientas directamente (`tools_executed = 0`).

#### 2.2. Skill Graph Planner
- **Archivos:**
  - `skills/skill_graph_planner.py` (`SkillGraphPlanner`, `SkillGraphOptimizer`).
  - `skills/skill_graph_executor.py` (`SkillGraphExecutor`).
  - `skills/skill_graph_builder.py` (`SkillGraphBuilder`).
  - `skills/skill_graph.py` (`SkillGraph`).
- **Responsabilidades:**
  - Generación de grafos dirigidos acíclicos (DAG) estáticos a partir de plantillas regex hardcodeadas:
    1. Patrón Investigación: `browser.search` -> `browser.read` -> `documents.create`.
    2. Patrón Organización: `files.search` -> `files.organize`.
    3. Patrón Reunión: `documents.read` -> `browser.search` -> `documents.create`.
    4. Fallback genérico: búsqueda léxica de skills en `SkillRegistry`.
  - Optimización determinista de caché (`SkillGraphOptimizer`) con TTL y verificación de firma SHA-256.

---

### 3. Matriz de Capacidades y Comparación

| Capacidad | ARE | Skill Graph Planner | ¿Duplicada? | Consumidor Real | Clasificación | Acción Recomendada |
| :--- | :---: | :---: | :---: | :--- | :--- | :--- |
| **Descomposición Semántica de Metas** | SÍ (DAG dinámico, Kahn) | Parcial (Plantillas regex fijas) | OVERLAP | `JessycaLocalAgent` (ARE) | UNIQUE (ARE) | **KEEP (ARE)** |
| **Cálculo de Blast Radius / Riesgo** | SÍ (BFS inverso de impacto) | NO (Suma escalar de riesgo) | NO | `ARERuntime`, `JDE` | UNIQUE (ARE) | **KEEP (ARE)** |
| **Diagnóstico de Fallo Físico** | SÍ (Análisis de telemetría/causa) | NO (No diagnostica) | NO | `JessycaLocalAgent`, `JDE` | UNIQUE (ARE) | **KEEP (ARE)** |
| **Generación de Propuesta de Replan**| SÍ (Máx. 2 reintentos) | NO (Falla estática) | NO | `JessycaLocalAgent`, `JDE` | UNIQUE (ARE) | **KEEP (ARE)** |
| **Construcción de DAG de Skills Nativas**| SÍ (Grafo de acciones) | SÍ (`SkillGraphBuilder`) | OVERLAP | `SkillGraphExecutor`, Tests | OVERLAP | **CONSOLIDATE** |
| **Caché con Firma Criptográfica** | NO | SÍ (`SkillGraphOptimizer`) | NO | `SkillGraphExecutor` | UNIQUE (Planner) | **KEEP (Planner)** |
| **Integración con JDE Binding** | SÍ (Certificado en Fase 78) | NO (Desconectado de JDE) | NO | `JessycaLocalAgent` | UNIQUE (ARE) | **KEEP (ARE)** |

---

### 4. Auditoría Exhaustiva de Consumidores (Who Calls It?)

#### 4.1. Consumidores de ARE (`core/are/`, `core/integration/adapters/are_adapter.py`)
1. **`core/agent/local_agent.py` (`JessycaLocalAgent`):**
   - **Línea:** Invocación en `_plan_and_execute_complex()` y `_handle_recovery_cycle()`.
   - **Ruta:** `PRODUCTION PATH (CONTROLLED)`.
   - **Semántica:** ARE es el motor formal invocado cuando una intención requiere razonamiento multi-paso o recuperación de fallo.
2. **`core/integration/hub.py`:**
   - **Línea:** Registro en el Integration Hub como adaptador auditado.
   - **Ruta:** `CONTROLLED`.
3. **`tests/e2e/test_full_e2e_integration.py`:**
   - **Pruebas:** E2E-02, E2E-03, E2E-04, E2E-05, ADV-A, ADV-H.
   - **Ruta:** `TEST / E2E CERTIFICATION`.
4. **`tests/are/` y `tests/test_are_adapter.py`:**
   - **Pruebas:** 38 tests en `tests/are/`, 28 tests en `tests/test_are_adapter.py`.
   - **Ruta:** `UNIT / REGRESSION`.

#### 4.2. Consumidores de Skill Graph Planner (`skills/skill_graph_planner.py`)
1. **`core/system/system_coordinator.py` (`SystemCoordinator4`):**
   - **Import:** `from skills.skill_graph_planner import SkillGraphPlanner` (Línea 29).
   - **Instanciación:** `self.planner = SkillGraphPlanner(registry=self.skill_registry)` (Línea 115).
   - **Invocación:** `_graph = self.planner.plan(intent=cleaned_input, inputs=parameters or {})` (Línea 174).
   - **Hallazgo Crítico:** `_graph` se construye únicamente para calcular la métrica `metrics.planning_latency_ms`. El grafo resultante **no se ejecuta en el flujo principal**; la ejecución real se delega a `self.collaboration_engine.execute_collaborative_task(...)`.
   - **Ruta:** `LEGACY / TELEMETRY ONLY`.
2. **`skills/skill_graph_executor.py`:**
   - **Import:** `from skills.skill_graph_planner import SkillGraphOptimizer` (Línea 37).
   - **Invocación:** `SkillGraphOptimizer.optimize_graph(graph, context.cache_entries)`.
   - **Ruta:** `COMPATIBILITY PATH`.
3. **`skills/__init__.py`:**
   - **Línea:** Export público de `SkillGraphPlanner` y `SkillGraphOptimizer`.
   - **Ruta:** `PUBLIC CONTRACT`.
4. **`tests/skills/test_skill_graph.py`:**
   - **Pruebas:** `test_23_e2e_research_graph`, `test_24_e2e_file_organization_graph`.
   - **Ruta:** `TEST ONLY`.

---

### 5. Clasificación y Diagnóstico

- **ARE:** `ACTIVE / PRODUCTION PATH (CONTROLLED)`. Es el motor central de descomposición, planificación y recuperación de tareas complejas gobernado por JDE.
- **Skill Graph Planner:** `COMPATIBILITY / LEGACY`.
  - No recibe tráfico directo de producción en `JessycaLocalAgent`.
  - Su invocación en `SystemCoordinator4` es para medición de latencia histórica.
  - Sin embargo, **NO es código muerto**: exporta `SkillGraphOptimizer` requerido por `SkillGraphExecutor`, y mantiene contratos evaluados por la suite de pruebas `test_skill_graph.py`.

---

### 6. Recomendación Arquitectónica y Hoja de Ruta

**Dictamen:** `KEEP + DEPRECATION PLAN (NO BORRAR)`.

1. **Corto Plazo (Fase Actual):**
   - Mantener `skills/skill_graph_planner.py` sin modificaciones.
   - Garantizar retrocompatibilidad con `test_skill_graph.py` y `SystemCoordinator4`.
2. **Medio Plazo (Consolidación Futura):**
   - Extraer la capacidad única de `SkillGraphOptimizer` (gestión de caché criptográfico de pasos) e integrarla en el pipeline de execution caching de JDE/ARE.
   - Redirigir la telemetría de planificación en `SystemCoordinator4` hacia `ARERuntime`.
   - Marcar formalmente `SkillGraphPlanner` con `@typing.deprecated` o warning de deprecación sin romper importaciones.
