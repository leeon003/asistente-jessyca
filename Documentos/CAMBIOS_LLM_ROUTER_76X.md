# JESSYCA 4.0 — FASE 76.x: CAMBIOS SUBSISTEMA LLM & ROUTER

Informe de corrección controlada del subsistema LLM, resolución de nombres de modelos, delegación segura de auto-routing y unificación canónica de proveedores de visión.

---

## Cambios realizados

1. **Armonización de Nombres de Modelos**:
   - `core/local_agent/local_agent.py`: Se armonizó el identificador obsoleto `"llama3.2:3b"` a `"llama3.2"`, coincidiendo exactamente con el identificador canónico registrado en `ModelRegistry`. Se preservó `"qwen2.5-coder:7b"` para compatibilidad con contratos de prueba de agente local.
   - `core/llm/consensus_engine.py`: Se armonizó `"llama3.1:latest"` a `"llama3.1"` en `DEFAULT_CONSENSUS_ENSEMBLE`.
   - `core/llm/consensus_policy.py`: Se añadieron los pesos de consenso para `"llama3.1": 1.0` y `"llama3.2": 0.9` en `ConsensusPolicy.model_weights` manteniendo los alias anteriores para retrocompatibilidad total.

2. **Delegación Real y Segura de `AUTO_ROUTE_MODEL` ("auto-routed")**:
   - `core/llm/model_manager.py`:
     - Se dotó a `ModelManager` de la capacidad de aceptar un `router` inyectable (o resolver via singleton `ModelRouter.get_instance()`).
     - Cuando `get_model(name)` recibe `name is None` o `""`, devuelve directamente el modelo por defecto (`gemma4:e4b`) sin invocar el router.
     - Cuando `get_model(name)` recibe explícitamente `AUTO_ROUTE_MODEL` (`"auto-routed"`), delega la selección a `ModelRouter.route(context)`.
     - Se implementó un mecanismo de fallback seguro: si el router falla, o si no se encuentra un perfil adecuado, se recurre automáticamente al modelo por defecto (`gemma4:e4b`), garantizando que ninguna orden de voz o de ejecución falle por contingencias de routing.

3. **Unificación Canónica del Proveedor de Visión**:
   - Implementación canónica establecida en: `core/vision/ollama_vision_provider.py` (`OllamaVisionProvider`) y `core/vision/vision_result.py` (`VisionAnalysis`, `VisionObservation`).
   - Modelo canónico de visión: `qwen3-vl:4b`.
   - `core/vision/vision_exceptions.py`: Se corrigió la jerarquía de herencia MRO haciendo que `VisionError` herede de `InferenceError` (que a su vez hereda de `LLMError` y `MCPError`), resolviendo conflictos MRO en Python.
   - `core/vision/ollama_vision_provider.py`: Se enriqueció la API para soportar tanto `create_observation(analysis, request_id)` como `create_observation(screenshot, prompt)`, y se sincronizó el manejo de mensajes de error de sanitización.
   - `core/llm/vision_provider.py`: Se eliminó el código duplicado (~180 líneas redundantes), convirtiendo `VisionProvider` en una subclase directa de `OllamaVisionProvider` con compatibilidad total hacia atrás (aliases `_extraer_json_vision`, etc.).
   - `core/llm/vision_models.py`: Se re-exportaron `VisionAnalysis` y `VisionObservation` directamente desde `core.vision.vision_result`.

4. **Preservación Estricta del Flujo de Voz**:
   - El bucle de voz interactivo y orquestador permanecen fijos con `gemma4:e4b`.
   - No se incorporó routing dinámico al pipeline de voz, VAD, STT ni TTS.

---

## Archivos modificados

- `core/local_agent/local_agent.py`
- `core/llm/consensus_engine.py`
- `core/llm/consensus_policy.py`
- `core/llm/model_manager.py`
- `core/vision/vision_exceptions.py`
- `core/vision/ollama_vision_provider.py`
- `core/llm/vision_provider.py`
- `core/llm/vision_models.py`
- `tests/core/llm/test_model_manager.py`

---

## Archivos eliminados

NINGUNO

*(Se mantuvieron `core/llm/vision_provider.py` y `core/llm/vision_models.py` como adaptadores delgados de compatibilidad hacia la implementación canónica en `core/vision/`)*.

---

## Comportamiento antes/después

- **`auto-routed` Antes**:
  En `ModelManager.get_model("auto-routed")`, intentaba consultar `ModelRegistry.get("auto-routed")`. Al no existir dicho modelo en el registro, arrojaba una advertencia y recurría al modelo por defecto, sin consultar jamás a `ModelRouter`.
- **`auto-routed` Después**:
  Al solicitar `AUTO_ROUTE_MODEL` ("auto-routed"), `ModelManager` construye el contexto de enrutamiento y llama a `ModelRouter.route(context)`. El router evalúa la política (`RoutingPolicy`), la tarea requerida (clasificación, visión, coding, etc.), la disponibilidad de hardware y VRAM, y selecciona el modelo óptimo (por ejemplo, `llama3.2` para clasificación o `qwen3-vl:4b` para visión). Si ocurre cualquier excepción o no hay candidato, el fallback devuelve transparentemente el modelo por defecto.
- **Nombres de Modelos Antes**:
  Existían discrepancias como `"llama3.2:3b"` y `"llama3.1:latest"` que no coincidían con las claves registradas en `ModelRegistry`.
- **Nombres de Modelos Después**:
  Todos los componentes apuntan a las claves normalizadas (`"llama3.2"` y `"llama3.1"`), con compatibilidad asegurada en las políticas de ponderación.
- **Visión Antes**:
  Dos clases completas independientes (`OllamaVisionProvider` en `core/vision/` y `VisionProvider` en `core/llm/`) que duplicaban lógica de inferencia, prompts de visión y parsing de JSON.
- **Visión Después**:
  Una única implementación canónica en `core/vision/ollama_vision_provider.py`. El archivo `core/llm/vision_provider.py` es un shim ligero de compatibilidad que reutiliza el 100% de la lógica canónica.

---

## Tests

### Ejecución de Suite Específica LLM & Visión:
- `tests/core/llm` & `tests/llm`:
  - **PASSED**: 104
  - **FAILED**: 0
- `tests/vision`:
  - **PASSED**: 8
  - **FAILED**: 0
- Suite consolidada LLM + Visión + Adaptadores (`tests/core/llm tests/llm tests/vision tests/test_jarvis_adapter.py tests/test_are_adapter.py tests/test_computer_use_adapter.py`):
  - **PASSED**: 196
  - **FAILED**: 0
- Pruebas de integración de agente local (`tests/local_agent/test_jessyca_local_agent_phase45.py` & `tests/local_agent/test_action_intent_contract_integration.py`):
  - **PASSED**: 18
  - **FAILED**: 0

---

## Flujo de voz

- Modelo principal: `gemma4:e4b`
- Routing dinámico: **NO**
- El bucle de voz interactivo y el orquestador principal se mantienen 100% acoplados a su modelo estable `gemma4:e4b`, sin latencia añadida ni delegación dinámica de turnos conversacionales.

---

## Visión

- Proveedor Canónico: `core.vision.ollama_vision_provider.OllamaVisionProvider`
- Modelo Utilizado: `qwen3-vl:4b`
- Retrocompatibilidad: Garantizada en `core.llm.vision_provider.VisionProvider`

---

## Riesgos pendientes

- **Consumo de VRAM en entornos locales con concurrencia**: Cuando componentes de background soliciten `auto-routed`, el `ModelRouter` podría proponer la carga de un modelo secundario (`llama3.2` o `qwen3-vl:4b`) mientras `gemma4:e4b` está en memoria. Para mitigar esto, `ModelRouter` ya consulta `VRAMManager`, pero se recomienda monitorear la VRAM durante ejecuciones reales en hardware con menos de 8GB de VRAM.
- Ningún otro riesgo detectado en la suite de pruebas unitarias ni funcionales.
