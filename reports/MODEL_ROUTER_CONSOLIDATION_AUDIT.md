# Auditoría de Consolidación: Model Router 2.0 vs Experimental Router

## Fecha de Auditoría: 2026-09-27
## Estado del Sistema: CONTROLLED READY (Audit Only)

---

### 1. Resumen Ejecutivo

Esta auditoría analiza los dos subsistemas de selección y enrutamiento dinámico de modelos de lenguaje (LLM) que coexisten en el repositorio:
1. **Model Router 2.0 (Smart Model Routing):** `core/llm/model_router.py` (Arquitectura orientada a objetos con `RoutingPolicy`, `ModelRegistry`, `ModelPerformanceTracker`, `VRAMManager` y `ConsensusEngine`).
2. **Experimental Router:** `core/llm/experimental_router.py` (Módulo heurístico introducido en Fase 3/4 que soporta modos `STATIC`, `SHADOW`, `EXPERIMENTAL` y `CONTROLLED`).

El objetivo es determinar cuál de los dos recibe tráfico real en el agente local, cómo interactúan, qué duplicación existe y cuál debe ser la ruta de consolidación futura.

---

### 2. Análisis Comparativo de Arquitectura

| Atributo | Model Router 2.0 (`model_router.py`) | Experimental Router (`experimental_router.py`) |
| :--- | :--- | :--- |
| **Diseño Arquitectónico** | Modular, desacoplado: separación en `ModelRegistry`, `RoutingPolicy`, `ModelPerformanceTracker`, `VRAMManager`. | Monolítico en un único archivo (1,012 líneas) con heurísticas y logging integrados. |
| **Modelos Gestionados** | Perfiles extensibles (`ModelProfile`): Llama 3.2, Qwen 2.5, Gemma 4, Qwen-VL, Nemotron, etc. | Específico y acoplado a la triada: Gemma 4 e4b, Qwen3 8B y Nemotron 3 Ultra. |
| **Modos de Operación** | Determinado por `RoutingPolicy` y métricas de rendimiento histórico. | Modos explícitos: `STATIC` (por defecto), `SHADOW`, `EXPERIMENTAL`, `CONTROLLED`. |
| **Gobernanza de Memoria VRAM**| `VRAMManager` / `vram_manager.py` con estimación de huella de contexto y pesos. | `VRAMGovernor` / `vram_governor.py` integrado. |
| **Motor de Consenso** | `ConsensusEngine` formal para arbitraje entre múltiples modelos en tareas críticas. | No implementa consenso formal. |
| **Telemetría Shadow** | Métricas registradas en `ModelPerformanceTracker`. | `ShadowLogger` y `phase6_logger` con volcado a archivos JSON de telemetría. |
| **Invariante de Seguridad** | No ejecuta herramientas, no concede permisos, no altera `SecurityPolicy`. | No ejecuta herramientas, no declara éxito, no sustituye verificación. |

---

### 3. Tráfico Real y Consumidores en Tiempo de Ejecución

#### 3.1. ¿Quién invoca a `ExperimentalRouter`?
1. **`core/local_agent/local_agent.py` (`JessycaLocalAgent`):**
   - **Línea 64:** `from core.llm.experimental_router import get_experimental_router`.
   - **Línea 129:** `self.experimental_router = get_experimental_router()`.
   - **Línea 439:** `router_selected_model, router_decision = self.experimental_router.route_execution(...)`.
   - **Línea 1668:** Actualiza métricas de telemetría en `self.experimental_router.shadow_logger.update_execution_metrics(...)`.
   - **Comportamiento en Producción:**
     - En la configuración por defecto de producción (`MODEL_ROUTER_ENABLED=False`), `ExperimentalRouter` opera en modo **`STATIC`** o **`SHADOW`**.
     - En modo `STATIC`, devuelve el modelo predeterminado (`gemma4:e4b`) sin alterar el flujo de ejecución.
     - En modo `SHADOW`, registra la decisión recomendada en los logs de sombra sin interferir en el modelo que ejecuta la tarea real.
2. **`core/local_agent/conversational_handler.py`:**
   - **Líneas 18, 68:** Inyecta y consulta `self.experimental_router`.
   - **Línea 120:** Consulta `route_execution` para resolver el modelo de diálogo rápido.

#### 3.2. ¿Quién invoca a `ModelRouter 2.0`?
1. **`core/llm/model_manager.py`:**
   - **Línea 65:** Cuando se solicita explícitamente el pseudo-modelo `"auto-routed"` (`AUTO_ROUTE_MODEL`), `ModelManager` delega la resolución a `ModelRouter.get_instance().route(context)`.
2. **`core/system/system_coordinator.py`:**
   - Referenciado a través del catálogo de modelos en inicialización del validador de grafos.
3. **Suites de Pruebas Extensivas:**
   - `tests/core/llm/test_model_router.py` (Tests unitarios exhaustivos de `ModelRouter` y `RoutingPolicy`).
   - `tests/llm/test_smart_model_routing.py` (Pruebas completas de Smart Model Routing 2.0).
   - `tests/llm/test_nemotron_provider.py` (Fallback determinista).
   - `tests/llm/test_model_performance_learning.py` (Aprendizaje adaptativo).
   - Cobertura total: más de 80 tests unitarios específicos.

---

### 4. Diagnóstico de Duplicación y Brechas

Existe una **duplicación temporal de roles**:
- **Tráfico Front-End del Agente:** El agente `JessycaLocalAgent` está conectado a `ExperimentalRouter` porque durante las Fases 3 y 4 se requería instrumentar el modo `SHADOW` y el logging en disco de recomendaciones de modelos antes de alterar la inferencia de producción.
- **Arquitectura de Dominio LLM:** El subsistema `core/llm/model_router.py` alberga la arquitectura definitiva, desacoplada y formal de Smart Model Routing 2.0, pero no fue cableado como el enrutador primario del agente para evitar riesgos de regresión antes de certificar JDE y ARE.

---

### 5. Clasificación de Estado

| Componente | Estado Real | Consumo en Agente | Cobertura de Pruebas | Riesgo de Regresión |
| :--- | :---: | :---: | :---: | :---: |
| **Model Router 2.0** | `CONTROLLED (READY)` | Vía `ModelManager("auto-routed")` | 84 tests PASS | Bajo (Arquitectura formal) |
| **Experimental Router** | `SHADOW / STATIC (ACTIVE)` | Directo en `local_agent.py` | 40 tests PASS | Medio (Contiene telemetría activa) |

---

### 6. Recomendación Arquitectónica y Hoja de Ruta de Consolidación

**Dictamen:** `KEEP BOTH (NO MODIFICAR CONFIGURACIÓN NI CÓDIGO EN ESTA FASE)`.

1. **Invariante Obligatoria para Fase Actual:**
   - No activar `MODEL_ROUTER_ENABLED=True` ni alterar el modo `STATIC/SHADOW`.
   - No cambiar las importaciones en `local_agent.py`.
2. **Plan de Consolidación para Fase Posterior (Fase de Unificación LLM):**
   - **Paso 1:** Migrar las capacidades útiles de `ExperimentalRouter` (la lógica de `ShadowLogger` y las heurísticas de categorización `TaskCategory`) hacia `core/llm/smart_routing_models.py` y `ModelPerformanceTracker`.
   - **Paso 2:** Hacer que `get_experimental_router()` actúe como un adaptador de compatibilidad (*façade*) delegando en `ModelRouter.get_instance().route_smart()`.
   - **Paso 3:** Una vez verificado que el 100% del tráfico pasa a través de `ModelRouter 2.0` con la misma telemetría de sombra, consolidar los tests y retirar gradualmente el archivo `experimental_router.py`.
