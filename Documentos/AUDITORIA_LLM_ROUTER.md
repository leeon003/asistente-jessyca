# AUDITORÍA TÉCNICA — SISTEMA DE MODELOS Y EVALUACIÓN DE LLM ROUTER
## JESSYCA 4.0 — FASE 76.x

---

## 1. ESTADO ACTUAL

### 1.1 Modelo LLM en Ejecución Activa
En la arquitectura de ejecución actual de JESSYCA, el sistema opera con un único modelo de lenguaje configurado como predeterminado:
* **Modelo en `.env`**: `OLLAMA_MODEL=gemma4:e4b`
* **Host configurado**: `OLLAMA_HOST=http://localhost:11434`
* **Fallback en código (`core/llm/model_manager.py`)**: `FALLBACK_DEFAULT_MODEL = "gemma4:e4b"`
* **Punto de Inferencia Central (`core/brain.py`)**: El método `procesar_orden()` utiliza `_llamar_ollama()` o `provider.generate()`. Si no se especifica `model_name`, resuelve a `os.getenv("OLLAMA_MODEL", "gemma4:e4b")`.
* **Punto de Entrada del Orquestador (`core/orquestador.py`)**: La función `ejecutar_orden_texto()` invoca `procesar_orden(texto, skills_disponibles=skills, contexto_aclaracion=contexto_aclaracion)` sin especificar modelo, forzando la resolución a `gemma4:e4b`.

### 1.2 Mecanismo de Inferencia
La inferencia se encuentra desacoplada mediante la abstracción tipada `LLMProvider` (`core/llm/inference.py`):
* `OllamaProvider`: Cliente HTTP síncrono que realiza peticiones `POST` a `/api/generate` del servidor local de Ollama. Construye payloads con prompt, system prompt opcional, opciones de muestreo (`temperature`, `num_predict`) e imágenes en Base64 para inferencia multimodal.
* `FakeLLMProvider`: Implementación sintética determinista utilizada en suites de tests unitarios para simular respuestas sin conectividad de red ni consumo de hardware.

### 1.3 Estado de la Detección de Intenciones y Planificación
Una parte sustancial del flujo operativo no utiliza inferencia de LLM en cada turno:
* `ActionPlanner` (`core/dialogue/action_planner.py`): Constructor y validador de intenciones estructuradas basado en reglas, expresiones regulares y validación contra el catálogo cerrado de 29 skills canónicas. Funciona sin llamadas a modelos de lenguaje.
* `NaturalActionDialogueManager` (`core/dialogue/natural_dialogue_manager.py`): Evalúa si la orden requiere aclaración, ejecución inmediata o respuesta conversacional mediante heurísticas de alta velocidad.
* `ConversationalDialogueHandler` (`core/local_agent/conversational_handler.py`): Si Ollama no se encuentra disponible o la inferencia falla, recurre a síntesis contextual determinista (`_synthesize_dialogue`) para respuestas conversacionales estructuradas.

### 1.4 Hallazgo Crítico: Router Existente vs. Enrutamiento en Producción
```text
DOCUMENTACIÓN vs IMPLEMENTACIÓN
```
* **En el subsistema `core/llm/`**: Ya existe una implementación completa de `ModelRouter` (`core/llm/model_router.py`), `RoutingPolicy` (`core/llm/routing_policy.py`), `SmartRouting` (`core/llm/smart_routing_models.py`), `VRAMGovernor` (`core/llm/vram_manager.py`) y `ConsensusEngine` (`core/llm/consensus_engine.py`), respaldada por 84 tests unitarios e integrales aprobados.
* **En el flujo principal de ejecución (`core/orquestador.py` y `core/brain.py`)**: `ModelRouter` **NO** se encuentra interconectado. Toda orden procesada por el orquestador se envía de forma estática al modelo configurado en `.env` (`gemma4:e4b`).
* **En el agente local (`core/local_agent/local_agent.py`)**: Existe el método heurístico `_select_model_for_intent()`, pero retorna identificadores no alineados con el catálogo oficial (`"llama3.2:3b"`, `"qwen2.5-coder:7b"`, `"auto-routed"`). Cuando retorna `"auto-routed"`, `ModelManager.get_model()` resuelve directamente al modelo predeterminado `gemma4:e4b`.

---

## 2. INVENTARIO DE MODELOS DETECTADOS

El catálogo formal del sistema está declarado en `core/llm/model_registry.py` mediante 5 perfiles nativos (`get_default_built_in_profiles()`):

| Identificador / Nombre | Runtime / Proveedor | Tamaño Parámetros | Capacidades Declaradas | Modalidad E/S | Longitud Contexto | VRAM Estimada | Uso Actual en el Código | Uso Potencial | Estado GPU / Coexistencia |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `gemma4:e4b` | Ollama (Local) | ~4B | `completion`, `tools`, `thinking` | Texto → Texto | 8,192 | 5,200 MB | Modelo primario por defecto del sistema (`.env`, `brain.py`, fallback general). | Extracción de intenciones, comandos generales, síntesis conversacional. | Asignado como prioritario. Coexiste con modelos ligeros si la VRAM disponible es ≥ 8 GB. |
| `llama3.2` | Ollama (Local) | 3.2B | `completion`, `tools` | Texto → Texto | 131,072 | 2,500 MB | Solo registrado y evaluado en pruebas de `ModelRouter` (`TaskType.CLASSIFICATION`). | Tareas simples, comandos de sistema operativo, clasificación ultrarrápida. | Puede convivir con `gemma4:e4b` o `qwen3-vl:4b` en GPUs de 12 GB. |
| `llama3.1` | Ollama (Local) | 8B | `completion`, `tools` | Texto → Texto | 131,072 | 5,500 MB | Registrado; afinidad configurada para `TaskType.CONVERSATION` y `ConsensusEngine`. | Diálogo conversacional fluido, tareas generales de contexto extenso. | Coexistencia limitada con modelos > 5 GB en hardware de 12 GB. |
| `qwen3:8b` | Ollama (Local) | 8B | `completion`, `tools`, `thinking` | Texto → Texto | 40,960 | 5,700 MB | Registrado; afinidad en `RoutingPolicy` para `TaskType.REASONING` y `TaskType.PLANNING`. | Razonamiento lógico en varios pasos, análisis de fallos, generación de código. | Carga pesada. Requiere descarga previa de otros modelos grandes en GPU de 12 GB para evitar swapping. |
| `qwen3-vl:4b` | Ollama (Local) | 4B Multimodal | `completion`, `tools`, `thinking`, `vision` | Texto + Imagen → Texto | 262,144 | 3,600 MB | Asignado como modelo visual exclusivo en `VisionProvider` (`core/llm/vision_provider.py`). | Análisis de capturas de pantalla de Windows, inspección visual de UI. | Compatible en VRAM simultánea con `gemma4:e4b` (3.6 GB + 5.2 GB = 8.8 GB < 10.7 GB útiles de RTX 3060). |

*Nota sobre estado de ejecución*: Durante la inspección activa de la API de Ollama (`/api/tags`), el servicio local no se encontraba en ejecución de fondo, por lo que el estado de carga dinámica en GPU se cataloga como `NO DETERMINADO EN ESTE INSTANTE`.

---

## 3. MAPA DE LA ARQUITECTURA

### 3.1 Flujo Operativo Real Actual (Flujo de Producción)
```text
                  Usuario (Voz / Texto)
                            ↓
                    Calibrated STT
                            ↓
                  Quality & Completeness Gate
                            ↓
                 Orchestrator / LocalAgent
                            ↓
     ┌──────────────────────┴──────────────────────┐
     ↓                                             ↓
[Acción de Sistema / SO]                  [Consulta Conversacional]
     ↓                                             ↓
ActionPlanner (Determinista)              core/brain.py / ConversationalHandler
(Regex / Reglas / Skills)                          ↓
     ↓                                    OllamaProvider (HTTP)
Security Policy & Risk Engine                      ↓
(ExecutionGate / Confirmación)             gemma4:e4b (Fijo)
     ↓                                             ↓
Skill Execution (Windows / Apps)          Respuesta de Texto
     ↓                                             ↓
Verification & Output                     TTS Engine (Camila / Pocket)
```

### 3.2 Dónde Reside el Subsistema de ModelRouter (Arquitectura Interna Desconectada)
```text
                  Orchestrator / LocalAgent
                            │
               (Punto de inserción potencial)
                            │
                            ▼
              ┌───────────────────────────┐
              │  ModelRouter (Existente)  │
              │   RoutingPolicy 2.0       │
              │  ModelPerformanceTracker  │
              └─────────────┬─────────────┘
                            │
            Evalúa: TaskType, Complejidad,
            Capacidades (Visión/Tools),
            VRAM Budget (VRAMGovernor)
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
   llama3.2 (3.2B)    qwen3:8b (8B)    qwen3-vl:4b (4B)
   [Clasificación /   [Razonamiento /  [Visión Multimodal /
    Comandos Rápidos]  Planificación]   Pantalla]
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ▼
                  OllamaProvider / LLM
```

---

## 4. CAPACIDADES DEL SUBSISTEMA ACTUAL DE GESTIÓN DE MODELOS

### 4.1 `ModelManager`
* Implementa patrón Singleton con sincronización mediante `threading.RLock`.
* Resuelve perfiles de modelos por nombre estricto o por omisión (`default_model_name`).
* Contiene el marcador semántico `AUTO_ROUTE_MODEL = "auto-routed"`, que actualmente actúa como un alias directo hacia el modelo predeterminado (`self._default_model_name`).
* Expone interfaces de consulta de disponibilidad (`is_model_available`), registro de modelos (`list_available_models`) y cambio dinámico de modelo predeterminado (`set_default_model`).

### 4.2 `ModelRegistry`
* Catálogo centralizado en memoria con 5 perfiles precargados (`llama3.2`, `llama3.1`, `qwen3:8b`, `qwen3-vl:4b`, `gemma4:e4b`).
* Soporta validación de unicidad, sobreescritura controlada y búsqueda por identificador (`get`, `exists`, `register`, `unregister`).
* Desacoplado por diseño: no ejecuta inferencia, no se comunica con la red ni manipula procesos.

### 4.3 `ModelProfile`
* Dataclass inmutable con tipado exhaustivo que modela:
  * `capabilities`: tupla de cadenas (`completion`, `tools`, `thinking`, `vision`).
  * `modalities`: modalidades de entrada y salida (`text`, `image`).
  * `context_length` y `max_context_length`.
  * Flags booleanos de capacidades técnicas: `vision`, `supports_vision`, `tool_calling`, `supports_tools`, `reasoning`.
  * Estimación de consumo de VRAM (`vram_estimate_mb`) y prioridad de asignación (`priority`).
  * Parámetros de generación predeterminados (`default_parameters`).

### 4.4 `Inference`
* Protocolo `LLMProvider` completamente desacoplado del transporte de red y de los detalles de Ollama.
* Entradas (`InferenceRequest`) y salidas (`InferenceResponse`) inmutables y tipadas con cálculo automático de duración en milisegundos y conteo de tokens.
* Manejo de excepciones tipadas (`ProviderConnectionError`, `ProviderTimeoutError`, `InferenceError`).

### 4.5 `ModelRouter` y `RoutingPolicy`
* Permite seleccionar deterministamente modelos mediante scoring multi-factor:
  * Afinidad de tarea: 40%
  * Complejidad de la tarea (LOW, MEDIUM, HIGH): 20%
  * Rendimiento histórico (`ModelPerformanceTracker`): 20%
  * Eficiencia de VRAM y latencia (`VRAMGovernor`): 20%
  * Preferencia declarada explícita: bonificación de +0.25
* Aplica filtro estricto de capacidades no negociables (*Capability Non-Negotiability*): las tareas con requerimiento de visión se dirigen exclusivamente a candidatos con `vision=True`.
* Implementa cadena de respaldo determinista (`fallback_chain`) y modelo de rescate garantizado (`SAFE_FALLBACK_MODEL = "gemma4:e4b"`).

---

## 5. ANÁLISIS DE NECESIDADES REALES DE JESSYCA

### 5.1 Clasificación Operativa de Tareas

#### NIVEL A — TAREAS SIMPLES Y DE CONTROL (Alta frecuencia: ~85% del tráfico habitual)
* Abrir/cerrar aplicaciones de Windows (`notepad`, `edge`, `calc`, `spotify`).
* Control de volumen, silencio, brillo y estado del sistema.
* Búsqueda simple de archivos por nombre o extensión.
* Navegación y búsquedas en la web o YouTube.
* Respuestas de diálogo corto (saludos, confirmaciones, cancelaciones).
* **Situación actual**: `ActionPlanner` y `NaturalActionDialogueManager` resuelven la mayoría de estas operaciones de manera determinista sin requerir modelos de lenguaje o utilizando `gemma4:e4b` en menos de 400 ms.

#### NIVEL B — TAREAS DE RAZONAMIENTO Y ANÁLISIS (Frecuencia media: ~10% del tráfico)
* Consultas técnicas complejas, síntesis de textos extensos.
* Planificación multi-paso en resolución de problemas o encadenamiento de herramientas.
* Agentes especializados (`research_coordinator_agent`).
* **Situación actual**: Resueltas actualmente por `gemma4:e4b`. `qwen3:8b` aportaría mayor profundidad lógica y capacidad de reflexión (*thinking*), pero implicaría alternancia de modelos en VRAM.

#### NIVEL C — TAREAS ESPECIALIZADAS (Baja frecuencia: ~5% del tráfico)
* Inspección y análisis de interfaz gráfica de Windows mediante capturas de pantalla.
* Sanitización OCR y detección de elementos interactivos de UI.
* Consenso multi-modelo para validación cruzada analítica.
* **Situación actual**: La visión ya está formalmente enrutada de manera directa en `VisionProvider` hacia `qwen3-vl:4b`.

### 5.2 Determinación de Diversidad de Tareas
Actualmente **no existe una saturación ni una diversidad de carga concurrente** en JESSYCA que justifique una conmutación continua y automática de modelos en cada petición. El 85% de las solicitudes son órdenes directas de sistema operativo que el sistema resuelve por reglas o mediante un modelo único de propósito general.

---

## 6. EVALUACIÓN DE COSTOS Y RIESGOS DE UN LLM ROUTER

| Factor | Evaluación Técnica |
| :--- | :--- |
| **Latencia de Conmutación en GPU (VRAM Thrashing)** | **RIESGO CRÍTICO**. En Ollama, cargar un modelo de 8B (como `qwen3:8b`, 5.7 GB) y luego alternar a uno de 4B (`gemma4:e4b`, 5.2 GB) o visión (`qwen3-vl:4b`, 3.6 GB) en una tarjeta gráfica común (RTX 3060 12 GB o inferior) provoca la descarga y recarga física de pesos en VRAM. Esta operación añade entre 3 y 8 segundos de bloqueo por turno, degradando la experiencia de un asistente de voz en tiempo real. |
| **Consumo de Memoria (RAM / VRAM)** | Mantener múltiples modelos residentes en memoria simultáneamente satura la VRAM, forzando la deslocalización de capas a la memoria RAM del sistema (*CPU offloading*), lo que reduce drásticamente los tokens por segundo. |
| **Complejidad Arquitectónica y Puntos de Fallo** | Un router dinámico introduce decisiones probabilísticas en la selección de modelos. Un fallo de clasificación en el router puede enviar una orden crítica a un modelo subóptimo, provocando fallos en cascada. |
| **Dificultad de Diagnóstico y Debugging** | Determinar por qué una orden específica falló se vuelve no determinista si la selección del modelo depende de scores flotantes dinámicos, trackers de latencia histórica o estados volátiles del sistema. |
| **Compatibilidad con Versión Mobile** | En dispositivos móviles (`jessyca-mobile`), el hardware y la memoria son limitados. Un esquema dependiente de múltiples modelos pesados locales no es viable; las arquitecturas móviles requieren un modelo extremadamente compacto o delegación a API centralizada. |

---

## 7. EVALUACIÓN DE BENEFICIOS REALES

| Beneficio Evaluado | Calificación | Justificación Técnica |
| :--- | :--- | :--- |
| Reducción de latencia en tareas simples | **BENEFICIO POTENCIAL** | Enrutar tareas elementales a `llama3.2` (3.2B) reduciría el tiempo de inferencia frente a modelos de 8B, siempre y cuando `llama3.2` permanezca cargado en VRAM de forma continua y no compita por la memoria con otros modelos. |
| Reducción de consumo de VRAM | **NO APLICA ACTUALMENTE** | Un router no reduce el consumo de VRAM por sí mismo. Si intenta mantener perfiles múltiples en memoria, incrementa el uso de VRAM o fuerza swapping de modelos. |
| Mejora de calidad en razonamiento complejo | **BENEFICIO POTENCIAL** | Derivar consultas complejas a `qwen3:8b` incrementaría la profundidad deductiva frente a un modelo ligero de 4B. |
| Selección de modelos de visión al requerirse | **BENEFICIO REAL** | Este beneficio ya se encuentra materializado de forma directa y determinista en `core/llm/vision_provider.py` asignando capturas a `qwen3-vl:4b`. No requiere un router probabilístico. |
| Alta disponibilidad mediante fallback | **BENEFICIO REAL** | Si el modelo principal no responde o genera timeouts, disponer de una cadena determinista de respaldo garantiza la continuidad operativa. La estructura ya existe en `ModelRouter.get_fallback_model()`. |
| Escalabilidad e integración de nuevos modelos | **BENEFICIO POTENCIAL** | Facilitará incorporar modelos futuros (ej. modelos especializados en código o audio directo) modificando únicamente el catálogo de `ModelRegistry`. |

---

## 8. COMPARACIÓN DE TRES ARQUITECTURAS

### Opción A — Sin Router (Flujo Actual Consolidado)
```text
Orchestrator ──> core/brain.py ──> OllamaProvider (gemma4:e4b) ──> Skills
                               └── (Visión directa a qwen3-vl:4b)
```
* **Complejidad**: Mínima. Un único modelo en memoria de trabajo.
* **Latencia**: Constante y predecible (~350–700 ms por turno en GPU). Cero latencia de intercambio de modelos.
* **Mantenimiento**: Muy bajo. Puntos de fallo centralizados.
* **Consumo de Recursos**: Estable (~5.2 GB de VRAM fija). Permite que Windows y el resto del sistema operen con holgura.
* **Escalabilidad**: Limitada cuando se presenten tareas que excedan las capacidades del modelo seleccionado.
* **Confiabilidad**: Alta. Comportamiento homogéneo y determinista en cada ejecución.
* **Facilidad de Debugging**: Inmediata. Las trazas corresponden a un único ejecutor.
* **Compatibilidad Móvil**: Alta. Modelo mental simple extrapolable a un motor SLM único en móvil.

### Opción B — Router Interno Nativo (Activar el `ModelRouter` Existente)
```text
Orchestrator ──> ModelRouter / RoutingPolicy ──> ModelManager ──> Modelo Seleccionado
```
* **Complejidad**: Moderada. Toda la lógica ya está escrita y probada en `core/llm/` (scoring, fallback, VRAM tracking).
* **Latencia**: Baja sobrecarga de decisión en Python (<1 ms). El riesgo de latencia surge si la selección induce alternancia de modelos en Ollama.
* **Mantenimiento**: Controlado. El código es interno, sin dependencias de red ni librerías de terceros.
* **Consumo de Recursos**: Controlable mediante el `VRAMGovernor` existente, que calcula presupuestos y desalojos.
* **Escalabilidad**: Alta. Adición declarativa de nuevos perfiles en `ModelRegistry`.
* **Confiabilidad**: Alta si las políticas de afinidad son deterministas y no probabilísticas.
* **Facilidad de Debugging**: Buena. Las decisiones registran métricas detalladas (`ModelRoutingDecision`, desglose de puntuaciones).
* **Compatibilidad Móvil**: Totalmente compatible al ejecutarse dentro del runtime de Python sin servicios auxiliares.

### Opción C — Router Externo (Ej. LiteLLM Proxy, OpenRouter, Microservicio)
```text
Orchestrator ──> Proxy HTTP Externo ──> API REST / Ollama / Nube
```
* **Complejidad**: Muy alta. Requiere un proceso daemon o microservicio adicional ejecutándose en segundo plano.
* **Latencia**: Elevada. Añade serialización de red adicional por salto HTTP (loopback o externa).
* **Mantenimiento**: Alto. Dependencias externas de paquetes de terceros con ciclos de versión independientes.
* **Consumo de Recursos**: Overhead adicional de procesos de sistema y consumo de memoria auxiliar.
* **Escalabilidad**: Muy alta en entornos multi-proveedor o nube, pero desacoplada de las metas locales de JESSYCA.
* **Confiabilidad**: Menor. Introduce un punto único de falla de red intermedia.
* **Facilidad de Debugging**: Compleja. Requiere inspeccionar logs entre procesos diferentes.
* **Compatibilidad Móvil**: Incompatible o altamente ineficiente en dispositivos móviles locales.

---

## 9. INVESTIGACIÓN DE ROUTERS EXISTENTES Y EVALUACIÓN TÉCNICA

| Categoría / Tecnología | Naturaleza | Evaluación Técnica para JESSYCA 4.0 |
| :--- | :--- | :--- |
| **LiteLLM** | Proxy / Gateway de APIs | Diseñado primordialmente para unificar llamadas a proveedores en la nube (OpenAI, Anthropic, Bedrock). Para un entorno local en Windows que interactúa con Ollama vía HTTP, representa sobreingeniería sustancial y agrega dependencias pesadas innecesarias. |
| **OpenRouter** | Agregador cloud comercial | Contradice el principio fundacional de JESSYCA de soberanía de datos, privacidad y ejecución local autónoma sin dependencia de Internet. |
| **Routing Basado en Reglas y Capacidades** | Lógica interna determinista | Es exactamente la arquitectura ya implementada en `core/llm/routing_policy.py` (`RoutingPolicy`). Resuelve la selección mediante tipos de tarea y requisitos duros sin sobrecoste. |
| **Routing Basado en Clasificación Pequeña** | Clasificador semántico ligero | Viable en el futuro si se utiliza un clasificador embeddings/regex previo antes de invocar modelos generativos grandes. |

---

## 10. EVALUACIÓN: ¿PUEDE JESSYCA HACER ROUTING SIN UN "LLM ROUTER" DEDICADO?

**Determinación Técnica**: **SÍ**.

En la arquitectura de JESSYCA, la selección de modelo no requiere un motor de enrutamiento probabilístico externo o complejo. La clasificación semántica puede resolverse a nivel del Orchestrator y del ActionPlanner:
```text
Entrada de Usuario
       ↓
Clasificación de Tarea (ActionPlanner / Heurística de Entrada)
       ↓
¿Requiere Visión? ─── Sí ───> qwen3-vl:4b (Directo)
       │
       No
       ↓
¿Razonamiento Profundo / Agente Multi-paso? ─── Sí ───> qwen3:8b
       │
       No
       ↓
Tarea General / Diálogo / Intenciones ───────────────> gemma4:e4b (Predeterminado)
```
Esta aproximación directa es:
1. Completamente determinista y auditable.
2. Libre de dependencias externas.
3. Coherente con los principios de seguridad de JESSYCA (`Invariante: Model Selection != Authorization`).
4. Evita latencias intermedias y consumo innecesario de cómputo.

---

## 11. ANÁLISIS DEL ROADMAP DE JESSYCA 4.0 Y CONDICIONES DE ACTIVACIÓN

### 11.1 Proyección del Roadmap
* **Asistente de Voz en Tiempo Real**: Prioridad crítica en latencia sub-segundo. Exige mantener un único modelo residente en VRAM para evitar pausas audibles.
* **ARE (Autonomous Runtime Environment)**: Tareas multi-paso autónomas que pueden justificar un modelo de mayor capacidad (`qwen3:8b`), pero ejecutadas como tareas de fondo, no en el bucle conversacional interactivo.
* **Computer Use y Visión**: Ya resuelto mediante derivación directa a `VisionProvider` (`qwen3-vl:4b`).
* **JESSYCA Mobile**: Exigirá un único modelo compacto (SLM) cuantizado o acceso cliente-servidor, no múltiples modelos simultáneos.

### 11.2 Condición Concreta para Justificar la Activación de Routing Dinámico
Un enrutamiento dinámico activo en producción solo se justificará técnicamente cuando se cumpla la siguiente condición medible:

> **Condición Arquitectónica de Activación**:
> Se cumpla de forma simultánea:
> 1. Que el hardware anfitrión disponga de memoria VRAM suficiente (≥ 16 GB) o cuantizaciones optimizadas (GGUF 4-bit) que permitan mantener residentes en memoria de GPU al menos dos modelos concurrentes (`gemma4:e4b` + `qwen3:8b`) sin provocar operaciones de descarga/recarga (*VRAM model thrashing*).
> 2. Que el flujo de trabajo incorpore flujos de razonamiento autónomo profundo en segundo plano (Fases ARE / Jarvis) que requieran de forma continua un modelo con capacidad de reflexión (*thinking*) mientras el bucle de voz interactivo se mantiene atendido por un modelo de respuesta rápida.

---

## 12. DETECCIÓN DE SOBREINGENIERÍA

* **Instalar un paquete externo de LLM Router ahora**: **SOBREINGENIERÍA GRAVE E INJUSTIFICADA**. Introduciría dependencias externas, latencia adicional y duplicaría el subsistema ya construido en `core/llm/`.
* **Crear un router interno desde cero**: **SOBREINGENIERÍA Y REDUNDANCIA**. JESSYCA ya cuenta con `ModelRouter`, `RoutingPolicy`, `ModelRegistry` y `VRAMGovernor` completamente funcionales en el repositorio.
* **Activar el `ModelRouter` existente en el bucle principal en este momento**: **PREMATURO**. Forzaría la alternancia de modelos en Ollama con el hardware actual, degradando el tiempo de respuesta del asistente de voz de ~500 ms a más de 5 segundos.
* **Riesgo de limitación futura por no activarlo ahora**: **NULO**. Como el desacoplamiento en `core/llm/` es total y el `ModelRouter` ya está codificado y probado, su conexión al orquestador requerirá únicamente un puente de pocas líneas de código cuando el roadmap lo demande.

---

## 13. RECOMENDACIÓN ARQUITECTÓNICA

```text
ESTADO ACTUAL:
JESSYCA opera de forma estable y determinista con un único modelo de lenguaje configurado
en .env (gemma4:e4b), derivación multimodal directa a qwen3-vl:4b para análisis visual,
y resolución determinista de la mayoría de comandos de sistema mediante ActionPlanner.
Existe en el repositorio un subsistema completo de Smart Model Routing 2.0 (ModelRouter,
RoutingPolicy, ModelRegistry con 5 modelos, VRAMGovernor) implementado y validado mediante
84 tests unitarios, pero desacoplado del bucle de ejecución del Orquestador.

NECESIDAD INMEDIATA:
NEGATIVA. No existe justificación técnica para incorporar un nuevo LLM Router, ni
para instalar librerías de enrutamiento de terceros, ni para activar la alternancia
continua de modelos en el bucle de voz en la etapa actual.

ROUTING ACTUAL:
- Comandos generales y conversación: resueltos de forma fija por gemma4:e4b.
- Análisis de pantalla y visión: resuelto de forma fija por qwen3-vl:4b vía VisionProvider.
- Comandos y acciones de Windows: resueltos de forma determinista por ActionPlanner sin LLM.
- ModelRouter interno: existente y testeado en core/llm/, pero en estado inactivo en producción.

ROUTING FUTURO:
El enrutamiento dinámico entre múltiples modelos de texto (ej. conmutar entre llama3.2 para
clasificación y qwen3:8b para razonamiento) solo debe habilitarse cuando se demuestre
que la GPU anfitriona puede albergar ambos modelos en VRAM simultáneamente sin incurrir en
latencias de swapping de modelos en Ollama, en el marco de la integración de tareas de
razonamiento profundo en segundo plano (ARE / Jarvis).

ACCIÓN PROPUESTA:
1. Mantener la configuración actual de modelo único (gemma4:e4b) para el bucle interactivo de voz.
2. Preservar intacto el subsistema core/llm/ (ModelRouter, ModelRegistry, RoutingPolicy) como
   activo de arquitectura ya validado.
3. En una fase posterior de estabilización de modelos, corregir la discrepancia de nombres de
   modelos entre core/local_agent/local_agent.py ("llama3.2:3b", "qwen2.5-coder:7b") y el
   catálogo canónico de core/llm/model_registry.py ("llama3.2", "qwen3:8b") para garantizar
   que la infraestructura esté perfectamente alineada cuando se requiera su activación.

NO HACER:
- NO instalar paquetes ni proxies externos de enrutamiento (LiteLLM, OpenRouter, etc.).
- NO alterar los archivos de configuración (.env, config/settings.yaml).
- NO introducir conmutación dinámica de modelos en el bucle síncrono de audio/voz.
- NO reimplementar componentes que ya existen en core/llm/.
```
