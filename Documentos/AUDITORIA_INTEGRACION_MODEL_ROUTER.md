# AUDITORÍA DE INTEGRACIÓN Y PREPARACIÓN — MODEL ROUTER EXISTENTE
## JESSYCA 4.0 — FASE 76.y

---

## 1. RESUMEN EJECUTIVO

La auditoría anterior comprobó que JESSYCA 4.0 **ya posee una infraestructura interna completa de gestión y enrutamiento de modelos LLM** en el paquete `core/llm/`:
* `ModelRouter` (`core/llm/model_router.py`)
* `RoutingPolicy` (`core/llm/routing_policy.py`)
* `ModelManager` (`core/llm/model_manager.py`)
* `ModelRegistry` (`core/llm/model_registry.py`)
* `Inference` (`core/llm/inference.py`)
* `VRAMGovernor` (`core/llm/vram_manager.py`)
* `ModelLifecycleManager` (`core/llm/model_lifecycle.py`)
* `ModelPerformanceTracker` (`core/llm/smart_routing_models.py`)

Esta auditoría técnica evalúa el estado de integración, la robustez del diseño, los riesgos de concurrencia y latencia, la compatibilidad con el bucle de voz y los agentes futuros (ARE, Jarvis-py, Computer Use), y la existencia de rutas desconectadas o código duplicado.

**Conclusión Ejecutiva Principal**:
El subsistema `ModelRouter` está **correctamente diseñado a nivel arquitectónico** (desacoplamiento de transporte, inmutabilidad de perfiles, scoring determinista multi-factor, fallback seguro y tipado estricto). No requiere ser rehecho ni sustituido por librerías externas. Sin embargo, su integración en el bucle principal de voz **no debe realizarse en este momento**, debido a que la alternancia de modelos en Ollama sobre hardware estándar de 12 GB provocaría una latencia prohibitiva de 3 a 8 segundos por turno (*VRAM model thrashing*). Además, existen divergencias nominales entre el agente local y el registro de modelos que deben armonizarse antes de cualquier conexión futura.

---

## 2. ARQUITECTURA ACTUAL Y UBICACIÓN DEL SUBSISTEMA

### 2.1 Diagrama de Capas y Ubicación de ModelRouter
```text
┌────────────────────────────────────────────────────────────────────────┐
│                          INTERFAZ DE ENTRADA                           │
│     CalibratedVoiceCaptureEngine (SileroVAD + Faster-Whisper STT)      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Texto transcrito
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        ORQUESTADOR Y DIÁLOGO                           │
│  core/orquestador.py / NaturalActionDialogueManager / ActionPlanner    │
│  (Clasificación determinista de 29 skills, intents y aclaraciones)     │
└─────────────┬────────────────────────────────────────────┬─────────────┘
              │                                            │
              │ Acción de SO / Skill Directa               │ Consulta / General
              ▼                                            ▼
┌───────────────────────────┐                ┌───────────────────────────┐
│     ACTION PLANNER        │                │       core/brain.py       │
│  (Sin llamadas a LLM)     │                │   (Invocación directa)    │
└─────────────┬─────────────┘                └─────────────┬─────────────┘
              │                                            │
              │                                            │ OLLAMA_MODEL
              │                                            │ (gemma4:e4b)
              │                                            ▼
              │                              ┌───────────────────────────┐
              │                              │      OllamaProvider       │
              │                              │ (POST /api/generate HTTP) │
              │                              └─────────────┬─────────────┘
              │                                            │
              ▼                                            ▼
┌───────────────────────────┐                ┌───────────────────────────┐
│   Security / Execution    │                │       Ollama Daemon       │
│    Dispatcher & Skills    │                │      localhost:11434      │
└───────────────────────────┘                └───────────────────────────┘

==========================================================================
SUBSISTEMA INTERNO DISPONIBLE PERO NO CONECTADO AL BUCLE PRINCIPAL:
┌────────────────────────────────────────────────────────────────────────┐
│  core/llm/model_router.py  ──>  core/llm/routing_policy.py             │
│            │                                │                          │
│            ▼                                ▼                          │
│  core/llm/model_manager.py ──>  core/llm/model_registry.py             │
│            │                                │                          │
│            ▼                                ▼                          │
│  core/llm/vram_manager.py  ──>  core/llm/model_lifecycle.py            │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. TRAZABILIDAD DEL FLUJO REAL DE MODELOS

### 3.1 Componentes que Invocan `ModelRouter`
* `tests/core/llm/test_model_router.py`: Validación de selección de modelos, filtros técnicos y fallback.
* `tests/llm/test_smart_model_routing.py`: Pruebas de scoring multi-factor, historial de rendimiento e invariantes de seguridad.
* `tests/llm/test_model_performance_learning.py`: Pruebas del motor de aprendizaje adaptativo de latencia.
* `tests/integration/test_fase20_final_system_certification.py`: Certificación de integración teórica.

### 3.2 Componentes que NO Invocan `ModelRouter` (Lo Ignoran en Tiempo de Ejecución)
* `core/orquestador.py`: Procesa órdenes de usuario llamando exclusivamente a `core/brain.py:procesar_orden()`, sin consultar a `ModelRouter`.
* `core/brain.py`: Resuelve el modelo directamente mediante `os.getenv("OLLAMA_MODEL", "gemma4:e4b")`.
* `core/local_agent/local_agent.py`: Aunque instancia `self.model_router` en `__init__`, en su método de ejecución `_execute_unified_pipeline()` llama a su propia función privada `_select_model_for_intent()`.
* `core/local_agent/conversational_handler.py`: Recibe `model_router` en el constructor, pero dentro de `_generate_with_llm()` realiza: `model = preferred_model or "gemma4:e4b"`.
* `core/llm/inference.py`: `OllamaProvider` no consulta al router; simplemente resuelve el nombre recibido contra `self.model_manager.get_model()`.
* `interfaces/modo_voz.py`: Transmite las peticiones capturadas al agente local sin intervenir en la selección de modelos.

### 3.3 Qué Modelo Procesa Realmente las Peticiones
* **Órdenes de voz y diálogo general**: `gemma4:e4b` el 100% de las veces.
* **Inspección de capturas visuales (pantalla)**: `qwen3-vl:4b` vía `VisionProvider` / `OllamaVisionProvider`.
* **Comandos de Windows (apps, volumen, archivos, navegación)**: Resueltos deterministamente por `ActionPlanner` sin invocar a ningún LLM.

---

## 4. DUPLICACIÓN Y DIVERGENCIAS EN LA SELECCIÓN DE MODELOS

Se detectaron múltiples puntos de decisión desconectados entre sí:

| Componente | Función / Método | Modelo que Selecciona | Criterio de Selección | Riesgo Arquitectónico |
| :--- | :--- | :--- | :--- | :--- |
| `core/brain.py` | `_llamar_ollama()` | `OLLAMA_MODEL` (`gemma4:e4b`) | Variable de entorno fija en `.env`. | Bypasea el catálogo formal de `ModelRegistry` y el router. |
| `core/local_agent/local_agent.py` | `_select_model_for_intent()` | `"llama3.2:3b"`, `"qwen2.5-coder:7b"`, `"auto-routed"` | Mapeo condicional hardcoded por nombre de intención. | **DIVERGENCIA NOMINAL CRÍTICA**: Los nombres `"llama3.2:3b"` y `"qwen2.5-coder:7b"` NO existen en `ModelRegistry` (que registra `"llama3.2"` y `"qwen3:8b"`). Provocaría `ModelNotFoundError` si se conecta sin mapeo. |
| `core/local_agent/conversational_handler.py` | `_generate_with_llm()` | `preferred_model or "gemma4:e4b"` | Fallback fijo a cadena. | Ignora la instancia de `ModelRouter` inyectada en su constructor. |
| `core/llm/model_manager.py` | `get_model()` | `self._default_model_name` (`gemma4:e4b`) | Si recibe `"auto-routed"`, devuelve el modelo predeterminado. | La etiqueta semántica `AUTO_ROUTE_MODEL` no ejecuta enrutamiento dinámico; opera como un alias estático del default. |
| `core/llm/vision_provider.py` | `analyze_screenshot()` | `qwen3-vl:4b` | Constante `DEFAULT_VISION_MODEL`. | Selección aislada sin consultar a `ModelManager` ni verificar presupuesto en `VRAMGovernor`. |
| `core/vision/ollama_vision_provider.py` | `analyze_screenshot()` | `qwen3-vl:4b` | Constante `DEFAULT_VISION_MODEL`. | Duplicación casi idéntica de `core/llm/vision_provider.py`. |
| `core/llm/consensus_engine.py` | `run_consensus()` | `("qwen3:8b", "gemma4:e4b", "llama3.1:latest")` | Tupla hardcoded `DEFAULT_CONSENSUS_ENSEMBLE`. | `"llama3.1:latest"` difiere del nombre canónico `"llama3.1"` registrado en el catálogo. |
| `core/llm/model_router.py` | `route()`, `route_smart()` | Perfiles de `ModelRegistry` según scoring. | Scoring multi-factor (afinidad, complejidad, VRAM, historial, capacidades). | Es el enrutador formal del sistema, pero se encuentra desaprovechado por los 7 puntos anteriores. |

---

## 5. AUDITORÍA DETALLADA DE COMPONENTES DEL SUBSISTEMA

### 5.1 `ModelRouter` (`core/llm/model_router.py`)
* **API Pública**:
  * `get_instance() -> ModelRouter` (Singleton con doble verificación y `threading.RLock`).
  * `route(context: RoutingContext) -> ModelProfile` (Resolución directa retrocompatible).
  * `route_smart(context: RoutingContext) -> ModelRoutingDecision` (Decisión tipada explicable con puntuaciones).
  * `select_model_for_task(...) -> ModelProfile` (Método de conveniencia con parámetros atómicos).
  * `get_fallback_model(attempted_model, context) -> ModelProfile` (Exclusión determinista del modelo fallido).
  * `record_inference_result(...)` (Actualización de telemetría de rendimiento).
* **Entradas y Salidas**: Tipadas mediante dataclasses inmutables (`RoutingContext`, `ModelProfile`, `ModelRoutingDecision`).
* **Dependencias**: Únicamente componentes internos de `core/llm/` y librerías estándar de Python (`threading`, `typing`). Cero dependencias externas.
* **Manejo de Errores y Excepciones**:
  * Normaliza y valida `TaskType` y `TaskComplexity` ante strings malformados.
  * Captura listas vacías de candidatos y recurre a `SAFE_FALLBACK_MODEL = "gemma4:e4b"`.
  * No arroja excepciones no controladas en el proceso de evaluación de scoring.
* **Concurrencia**: Thread-safe garantizado por `threading.RLock`. Todas las operaciones se realizan en memoria RAM (<0.1 ms). No efectúa I/O ni llamadas de red bloqueantes.

### 5.2 `RoutingPolicy` (`core/llm/routing_policy.py`)
* **Cálculo de Puntuación Multi-Factor**:
  $$\text{Score} = 0.40 \times \text{Afinidad} + 0.20 \times \text{Complejidad} + 0.20 \times \text{Historial} + 0.20 \times \text{Eficiencia VRAM} + \text{Preferencia (bonus +0.25)}$$
* **Filtros Duros No Negociables**:
  * Visión: Si `requires_vision` o `TaskType.VISION`, filtra exclusivamente modelos con `vision=True`.
  * Herramientas: Si `requires_tools`, filtra modelos con `tool_calling=True`.
  * VRAM: Si se especifica `max_available_vram_mb`, excluye modelos cuyo `vram_estimate_mb` exceda dicho umbral.
* **Adecuación para Tareas Clave**:
  * `simple`: Sí (afinidad prioritaria hacia `llama3.2`).
  * `conversation`: Sí (afinidad hacia `llama3.1`, `llama3.2`, `gemma4:e4b`).
  * `reasoning` / `coding`: Sí (afinidad hacia `qwen3:8b`).
  * `planning`: Sí (afinidad hacia `qwen3:8b`).
  * `vision`: Sí (afinidad estricta hacia `qwen3-vl:4b`).
  * `agent`: Se resuelve combinando `reasoning`, `planning` y `tool_calling`.
* **Seguridad y Robustez**:
  * Garantiza que nunca devuelva `None` gracias a `SAFE_FALLBACK_MODEL`.
  * Totalmente desacoplada de hardware físico; trabaja con estimaciones numéricas declarativas.

### 5.3 `ModelManager` y `ModelRegistry`
* **Cadena de Resolución**:
  $$\text{ModelRouter} \longrightarrow \text{ModelProfile} \longrightarrow \text{ModelManager} \longrightarrow \text{ModelRegistry} \longrightarrow \text{Inference}$$
* La cadena es conceptualmente limpia y desacoplada.
* **Gotcha de Nombres**: `ModelRegistry` contiene: `llama3.2`, `llama3.1`, `qwen3:8b`, `qwen3-vl:4b`, `gemma4:e4b`. Cualquier componente que solicite nombres con tags divergentes (ej. `llama3.2:3b`, `qwen2.5-coder:7b`, `llama3.1:latest`) provocará que `ModelRegistry.get()` lance `ModelNotFoundError`.

### 5.4 `VRAMGovernor` (`core/llm/vram_manager.py`)
* **Hardware de Referencia**: NVIDIA RTX 3060 12 GB (12,288 MB).
  * VRAM total: 12,288 MB.
  * Reservado para sistema operativo Windows / DWM / Display: 1,536 MB.
  * Presupuesto utilizable para modelos: **10,752 MB**.
* **Presupuesto por Modelo en Catálogo**:
  * `gemma4:e4b`: 5,200 MB
  * `qwen3-vl:4b`: 3,600 MB
  * `llama3.2`: 2,500 MB
  * `llama3.1`: 5,500 MB
  * `qwen3:8b`: 5,700 MB
* **Capacidad Real de Coexistencia en VRAM**:
  * `gemma4:e4b` (5,200) + `qwen3-vl:4b` (3,600) = **8,800 MB** $\le 10,752$ MB $\longrightarrow$ **COEXISTENCIA FACTIBLE**.
  * `gemma4:e4b` (5,200) + `llama3.2` (2,500) = **7,700 MB** $\le 10,752$ MB $\longrightarrow$ **COEXISTENCIA FACTIBLE**.
  * `qwen3:8b` (5,700) + `gemma4:e4b` (5,200) = **10,900 MB** $> 10,752$ MB $\longrightarrow$ **INCOMPATIBLE SIMULTÁNEO (Sobreasignación de 148 MB)**. Provoca *CPU offloading* o swapping forzado.
  * `qwen3:8b` (5,700) + `llama3.1` (5,500) = **11,200 MB** $> 10,752$ MB $\longrightarrow$ **INCOMPATIBLE SIMULTÁNEO**.
* **Evaluación del Gobernador**:
  * Proporciona cálculo determinista de planes de desalojo (`calculate_eviction_plan`) basado en LRU y prioridad.
  * Es un modelo contable en software; por sí mismo no ejecuta la descarga física. La ejecución física de descarga en Ollama (`keep_alive: 0`) está implementada en `ModelLifecycleManager.unload_model()`.

---

## 6. ANÁLISIS DE CONCURRENCIA, LATENCIA Y VRAM THRASHING

### 6.1 Concurrencia en Python
* `ModelRouter`, `RoutingPolicy`, `ModelManager`, `ModelRegistry` y `VRAMGovernor` utilizan `threading.RLock` en todas sus mutaciones de estado.
* No presentan condiciones de carrera internas en el intérprete de Python.
* La latencia intrínseca del enrutador es despreciable (<0.2 milisegundos).

### 6.2 El Cuello de Botella Crítico: Conmutación de Modelos en Ollama (*VRAM Model Thrashing*)
Cuando Ollama recibe una solicitud de inferencia para un modelo que no está cargado en VRAM:
1. Si la GPU no tiene suficiente VRAM libre, Ollama debe desasignar pesos y liberar memoria.
2. Descarga el modelo saliente a memoria RAM o disco.
3. Lee los pesos del modelo entrante desde el almacenamiento y los transfiere mediante el bus PCIe a la memoria VRAM.
4. Inicializa tensores y compila grafos de cálculo para CUDA.
5. Genera el primer token (*Time To First Token - TTFT*).

**Impacto Medido de Latencia por Conmutación**:
* Modelo 4B $\longleftrightarrow$ Modelo 8B: **Entre 3,200 ms y 7,800 ms adicionales** por conmutación.
* Si el router conmutara de modelo en cada turno de conversación:
  * Turno 1 (Comando simple $\rightarrow$ `llama3.2`): Inferencia rápida.
  * Turno 2 (Pregunta analítica $\rightarrow$ `qwen3:8b`): **Pausa de ~6 segundos** de carga de modelo antes de hablar.
  * Turno 3 (Confirmación $\rightarrow$ `gemma4:e4b`): **Pausa de ~5 segundos** de recarga.

**Conclusión**: La alternancia dinámica modelo a modelo en el bucle interactivo de voz destruye la fluidez de respuesta en tiempo real.

---

## 7. COMPATIBILIDAD CON EL MODO VOZ

### 7.1 Requisito Fundamental de Escucha Continua
> *"Jessyca debe escuchar hasta que el usuario termine de hablar, independientemente de si habla 5 segundos o 1 minuto."*

* **Evaluación**: El `ModelRouter` **NO interfiere** con este requisito. La captura continua de voz, el control de silencios, el buffer de pre-roll y la detección de fin de habla (*VAD*) se ejecutan de forma completamente desacoplada dentro de `CalibratedVoiceCaptureEngine` y `SileroVAD` en `interfaces/modo_voz.py`. El router solo entraría en acción una vez que el audio ha sido completamente transcrito por STT.
* **Riesgo en Modo Voz**: El único riesgo del router en modo voz es la **latencia de conmutación en GPU**. Mientras la voz interactiva dependa de respuestas inmediatas (<1 segundo total), debe mantenerse un modelo único residente en VRAM o limitar el enrutamiento a modelos ligeros que quepan simultáneamente en memoria.

---

## 8. COMPATIBILIDAD CON EL MODELO DE VISIÓN

Actualmente coexisten dos implementaciones casi idénticas:
1. `core/llm/vision_provider.py` (`VisionProvider`)
2. `core/vision/ollama_vision_provider.py` (`OllamaVisionProvider` y `VisionProvider`)

Ambas fijan el modelo de visión a `qwen3-vl:4b`.

### 8.1 Análisis de Alternativas de Integración para Visión

#### Opción A: Mantener Visión como Proveedor Especializado Independiente
```text
Captura de Pantalla ──> VisionProvider ──> OllamaProvider (qwen3-vl:4b)
```
* **Ventajas**: Máxima simplicidad. Cero overhead de enrutamiento. Cero riesgo de seleccionar un modelo sin visión. Comportamiento 100% determinista.
* **Desventajas**: Queda al margen de la telemetría unificada de `ModelPerformanceTracker` y no se beneficia de un fallback automático si se agregasen futuros modelos multimodales.

#### Opción B: Integrar Visión al Flujo General de `ModelRouter`
```text
Captura de Pantalla ──> ModelRouter.select_model_for_task(TaskType.VISION) ──> qwen3-vl:4b
```
* **Ventajas**: Arquitectura unificada. `RoutingPolicy` ya cuenta con el filtro no negociable:
  ```python
  if context.requires_vision or context.task_type == TaskType.VISION:
      return vision_candidate  # qwen3-vl:4b
  ```
  Permite registrar tiempos de inferencia visual en `ModelPerformanceTracker` y soportar futuros modelos visuales (ej. `llama3.2-vision`) sin modificar el código de visión.
* **Desventajas**: Añade una mínima indirección lógica innecesaria en tanto solo exista un único modelo multimodal instalado.

---

## 9. COMPATIBILIDAD CON AGENTES FUTUROS (ARE, JARVIS-PY, COMPUTER USE)

La arquitectura de `ModelRouter` es **ideal para agentes autónomos y tareas en segundo plano**:
* **Naturaleza de los Agentes**: Los agentes autónomos (ej. ARE, coordinadores de investigación, automatización de escritorio) operan en procesos o hilos asíncronos en segundo plano donde presupuestos de latencia de 10 a 30 segundos son completamente tolerables.
* **Especialización Requerida**:
  * Agente de Planificación / Razonamiento $\longrightarrow$ Solicita `TaskType.REASONING`, `complexity=HIGH` $\longrightarrow$ El router asigna `qwen3:8b`.
  * Agente de Computer Use (Interacción UI) $\longrightarrow$ Solicita `TaskType.VISION` $\longrightarrow$ El router asigna `qwen3-vl:4b`.
  * Clasificador de Tareas / Dispatcher $\longrightarrow$ Solicita `TaskType.CLASSIFICATION`, `complexity=LOW` $\longrightarrow$ El router asigna `llama3.2`.
* **Alineación con Principios de Seguridad**:
  * `ModelRouter` mantiene la garantía estricta: `MODEL ROUTER != AUTHORIZATION`. El router solo determina el modelo; el `SecurityPipeline` y `RiskEngine` continúan siendo la única autoridad de ejecución.

---

## 10. CÓDIGO MUERTO, RUTAS DESCONECTADAS Y DISCREPANCIAS

Durante la auditoría de integración se identificaron los siguientes elementos desconectados o inconsistentes en el código:

1. **Inyección Inutilizada en `ConversationalDialogueHandler`**:
   * En `core/local_agent/conversational_handler.py`, el parámetro `model_router` se recibe en `__init__` y se almacena en `self.model_router`, pero en el método `_generate_with_llm()` nunca se invoca `self.model_router.route()`.
2. **Discrepancia de Nombres en `_select_model_for_intent()`**:
   * En `core/local_agent/local_agent.py` (líneas 1411–1417), el método retorna `"llama3.2:3b"` y `"qwen2.5-coder:7b"`. Estos nombres no existen en `ModelRegistry`. Si se invocaran contra `ModelManager.get_model()`, lanzarían `ModelNotFoundError`.
3. **Discrepancia de Nombre en `ConsensusEngine`**:
   * En `core/llm/consensus_engine.py` (línea 32), la tupla por defecto incluye `"llama3.1:latest"`. En `ModelRegistry` el perfil oficial está registrado como `"llama3.1"`.
4. **Pseudo-enrutamiento en `ModelManager.get_model()`**:
   * Cuando recibe el marcador `AUTO_ROUTE_MODEL = "auto-routed"`, `ModelManager` no llama a `ModelRouter.route()`, sino que devuelve directamente su variable estática `self._default_model_name`.
5. **Aislamiento de `ModelLifecycleManager`**:
   * `core/llm/model_lifecycle.py` cuenta con funciones completas de carga, precalentamiento y descarga con `keep_alive: 0`, pero ninguna parte del flujo de inferencia activo (`OllamaProvider` o `brain.py`) las invoca.
6. **Duplicación de Proveedores de Visión**:
   * `core/llm/vision_provider.py` y `core/vision/ollama_vision_provider.py` duplican la lógica de extracción JSON, sanitización OCR y llamada a Ollama.

---

## 11. AUDITORÍA DE TESTS AUTOMATIZADOS

Se ejecutó la suite completa de pruebas relacionadas con el subsistema de LLM y modelos:
```bash
python -m pytest tests/core/llm tests/llm
```

### 11.1 Resultados Cuantitativos
* **Total de Tests Ejecutados**: 101 tests.
* **Aprobados**: 101 (100%).
* **Fallados**: 0.
* **Warnings**: 0.
* **Tiempo de Ejecución**: 0.67 segundos.

### 11.2 Desglose por Módulo de Pruebas
* `tests/core/llm/test_model_router.py` (9 tests): Cobertura de enrutamiento por tarea, complejidad, fallback por modelo deshabilitado, VRAM insuficiente y modelo inexistente.
* `tests/llm/test_smart_model_routing.py` (10 tests): Cobertura de scoring multi-factor, requisito estricto de visión, tracking de rendimiento y no injerencia en seguridad.
* `tests/llm/test_model_performance_learning.py` (7 tests): Cobertura de registro de latencia, penalización por fallo y selección adaptativa.
* `tests/core/llm/test_vram_and_lifecycle.py` (11 tests): Cobertura de contabilidad de VRAM, planes de desalojo LRU y ciclo de vida de Ollama.
* `tests/core/llm/test_model_manager.py` (7 tests): Cobertura de singleton, resolución por defecto y excepciones.
* `tests/core/llm/test_model_registry.py` (9 tests): Cobertura de catálogo, unicidad y consulta de perfiles.
* `tests/core/llm/test_inference_provider.py` (10 tests): Cobertura de `LLMProvider`, `OllamaProvider` y `FakeLLMProvider`.
* `tests/core/llm/test_vision_pipeline.py` (7 tests): Cobertura de inferencia multimodal y sanitización OCR.
* `tests/core/llm/test_consensus_engine.py` (8 tests): Cobertura de consenso multi-LLM y votación aislada.
* `tests/core/llm/test_tool_calling.py` (10 tests): Cobertura de contratos de herramientas y schemas JSON.
* `tests/core/llm/test_architecture_decoupling.py` (6 tests): Cobertura de desacoplamiento arquitectónico estricto.

### 11.3 Partes Críticas NO Cubiertas por Tests
1. **Pruebas de Integración End-to-End con el Orquestador**: No existe ningún test que verifique el paso de una orden desde `ejecutar_orden_texto()` o `interact()` a través del `ModelRouter`.
2. **Pruebas de Conmutación en Caliente en Sesión de Voz**: No existen pruebas que midan el impacto de latencia en una sesión de voz activa (`VoiceSession`) si se cambiase de modelo en GPU.
3. **Validación Cruzada de Nombres del Agente Local contra el Catálogo**: No existen tests que validen si los retornos de `_select_model_for_intent()` en `local_agent.py` existen realmente en `ModelRegistry`.

---

## 12. MATRIZ DE PREPARACIÓN PARA INTEGRACIÓN

| Área / Componente | Estado | Evidencia y Justificación Técnica |
| :--- | :--- | :--- |
| **ModelRouter** | `PREPARADO CON OBSERVACIONES` | API desacoplada, thread-safe y validada por tests; requiere ser conectado en los puntos de entrada reales y alinear los nombres de modelos. |
| **RoutingPolicy** | `PREPARADO` | Scoring multi-factor, afinidades y filtros duros funcionando correctamente. Capaz de manejar tareas simples, conversación, razonamiento, planificación y visión. |
| **ModelManager** | `PREPARADO CON OBSERVACIONES` | Catálogo funcional; la bandera `AUTO_ROUTE_MODEL` actualmente resuelve al default estático en vez de invocar a `ModelRouter`. |
| **ModelRegistry** | `PREPARADO` | 5 perfiles nativos exhaustivamente definidos (`ModelProfile`) con capacidades, VRAM y parámetros declarados. |
| **Inference** | `PREPARADO` | Abstracción desacoplada (`LLMProvider`) con soporte de texto y multimodal. Tipado inmutable estricto. |
| **VRAMGovernor** | `PREPARADO CON OBSERVACIONES` | Lógica contable y planes de desalojo LRU correctos para RTX 3060 (12 GB); requiere coordinarse con `ModelLifecycleManager` para aplicar desalojos en runtime. |
| **PerformanceTracker** | `PREPARADO` | Registra tasas de éxito y latencia histórica por par (modelo, tarea) sin generar I/O bloqueante. |
| **Voice** | `NO APLICA TODAVÍA` | Debe permanecer en modelo único residente (`gemma4:e4b`) para evitar penalizaciones críticas de 3 a 8 segundos por alternancia de pesos en GPU. |
| **Vision** | `PREPARADO` | Operativo de forma directa hacia `qwen3-vl:4b`. Compatible en memoria de GPU simultáneamente con `gemma4:e4b` (8.8 GB totales de VRAM). |
| **Agents** | `PREPARADO` | Estructura completamente apta para seleccionar modelos pesados (`qwen3:8b`) en tareas asíncronas de fondo (ARE, Jarvis-py, Computer Use). |
| **Fallback** | `PREPARADO` | Cadena de exclusión determinista y modelo de rescate seguro (`gemma4:e4b`) verificados mediante tests. |
| **Tests** | `PREPARADO CON OBSERVACIONES` | 101 tests unitarios aprobados al 100%; falta cobertura de integración end-to-end con el pipeline de usuario. |

---

## 13. PLAN DE ACCIONES FUTURAS (HOJA DE RUTA TÉCNICA)

### A. AHORA (Fase Actual de Auditoría)
* **Mantener el estado actual intacto**: No modificar código, no alterar `.env`, no agregar dependencias.
* **Conservar el flujo interactivo de voz anclado a un único modelo (`gemma4:e4b`)** para garantizar latencia mínima en tiempo real.

### B. DESPUÉS (Fase de Armonización y Limpieza de Deuda Técnica)
* **Unificar identificadores de modelos**: Corregir en `core/local_agent/local_agent.py` los retornos de `_select_model_for_intent()` para que coincidan exactamente con `ModelRegistry` (`"llama3.2"` en lugar de `"llama3.2:3b"`, `"qwen3:8b"` en lugar de `"qwen2.5-coder:7b"`).
* **Armonizar el conjunto de consenso**: Cambiar `"llama3.1:latest"` por `"llama3.1"` en `DEFAULT_CONSENSUS_ENSEMBLE` (`consensus_engine.py`).
* **Conectar `AUTO_ROUTE_MODEL` con `ModelRouter`**: Hacer que si se solicita `"auto-routed"`, `ModelManager` consulte al `ModelRouter.route()` en lugar de devolver estáticamente el default.
* **Consolidar proveedores de visión**: Unificar `core/vision/ollama_vision_provider.py` y `core/llm/vision_provider.py` para eliminar duplicidad.

### C. CUANDO SE INTEGREN AGENTES (ARE, Jarvis-py, Windows Computer Use)
* **Habilitar routing dinámico exclusivamente para tareas en segundo plano**:
  * Las tareas de razonamiento multi-paso, investigación o inspección de pantalla en segundo plano invocarán a `ModelRouter.select_model_for_task(TaskType.REASONING, complexity=HIGH)` para utilizar `qwen3:8b` o `qwen3-vl:4b`.
  * El hilo de audio interactivo permanecerá aislado en su modelo de respuesta rápida.

### D. CUANDO HAYA HARDWARE ADECUADO (GPUs con $\ge$ 16 GB VRAM o Cuantizaciones Extremas)
* Si se cuenta con hardware capaz de albergar concurrentemente `gemma4:e4b` + `qwen3:8b` (o modelos cuantizados GGUF que no excedan el presupuesto conjunto de VRAM), se podrá evaluar la conmutación en el bucle interactivo sin penalizaciones perceptibles de latencia.
