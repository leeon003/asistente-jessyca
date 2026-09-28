# JESSYCA PC — ROADMAP REAL ACTUALIZADO TRAS AUDITORÍA MAESTRA
**Fecha:** 2026-09-27  
**Sistema:** JESSYCA PC  
**Base:** Evidencia empírica de código fuente, configuración y 3,480 tests recopilados  
**Principio Rector:** Construir sobre lo que ya existe y está certificado; no reinventar componentes ni perseguir implementaciones fantasma.

---

## 1. ESTADO REAL DE LAS FASES DEL PROYECTO

### 1.1 COMPLETED / PRODUCTION CERTIFIED
Componentes totalmente implementados, subordinados a seguridad, con suites de pruebas dedicadas y superadas sin regresiones:

1. **JDE Core (JESSYCA Decision Engine):**  
   - Fase 8 completada. Motor determinista, resolución de conflictos, contratos de decisión, receipts y fail-safe (`reports/JDE_PHASE8_CERTIFICATION.md`, 163 tests).
2. **Archify Engine & Skill:**  
   - Fase 3 completada. Generación determinista de diagramas C4, secuencia, clases y Mermaid, exportación vectorial y aislamiento de workspace (`reports/archify_phase3_certification.md`, 76 tests).
3. **ORCA + ADE Engine:**  
   - Fase 3 completada. Orquestación multi-agente en paralelo, aislamiento en Git worktrees, verificación de salida y control estricto de comandos (`reports/orca_ade_phase3_certification.md`, 64 tests).
4. **AnyDoc Core (Firecrawl AnyDoc Integration):**  
   - Fase 3 completada. Conversión e inspección local offline de 15 formatos a GitHub-Flavored Markdown, extracción de tablas y metadatos, sandbox de rutas (`reports/anydoc_phase3_certification.md`, 74 tests).
5. **Security Foundation:**  
   - RiskEngine, PermissionManager, IdempotencyGuard, ExecutionVerifier y ExecutionBoundary (`tests/security/`, `server/`, 150+ tests).
6. **Windows Native Skills:**  
   - Automatización de aplicaciones del OS, multimedia, portapapeles, capturas de pantalla, audio y notificaciones (`skills/windows_skills.py`, 50+ tests).

---

### 1.2 ACTIVE (OPERACIONAL EN TIEMPO DE EJECUCIÓN)
Componentes en ejecución activa en el sistema pero pendientes de vinculación síncrona o gobernanza universal:

1. **JessycaLocalAgent (`agent.py`):** Bucle conversacional interactivo, manejo de sesiones, memoria y despacho de herramientas.
2. **JDEShadowAdapter:** Observador pasivo que registra auditoría de intenciones en cada turno sin bloquear el flujo.
3. **Local Vector Store & Semantic Memory:** Base de datos vectorial con embeddings `all-MiniLM-L6-v2` y detector de contradicciones (`core/memory/`).
4. **Voice Service:** Pipeline de voz híbrido con EdgeTTS (`CamilaNeural`), PocketTTS local offline y Whisper STT (`services/voice_service.py`).
5. **Open WebUI Bridge:** Servidor proxy FastAPI OpenAI-compatible en puerto 8088 con streaming de tokens por SSE (`interfaces/webui_bridge/`).
6. **Mobile API Backend:** Servidor REST FastAPI en puerto 8765 con autenticación por token (`interfaces/mobile_api/`).
7. **Integration Hub:** Registro centralizado de adaptadores externos (`core/integration/hub.py`).

---

### 1.3 CONTROLLED (IMPLEMENTADO / PENDIENTE DE ACTIVACIÓN EN PRODUCCIÓN)
Componentes construidos y con tests unitarios pasando, pero restringidos o desactivados por configuración:

1. **ARE Adapter (`core/integration/adapters/are_adapter.py`):**  
   - **Estado:** 28/28 tests pasando. Implementa descomposición en DAG, evaluación de planes, diagnóstico y recuperación.  
   - **Acción requerida:** Conectar formalmente al ciclo de planificación del agente y activar en `settings.py`.
2. **Model Router 2.0 (`core/llm/model_router.py`):**  
   - **Estado:** 108 tests pasando. Enrutamiento dinámico entre Nemotron, Qwen y Gemma.  
   - **Acción requerida:** Elevar de modo `shadow` a modo activo controlado tras validación de VRAM local.
3. **Computer Use Adapter (`core/integration/adapters/computer_use_adapter.py`):**  
   - **Estado:** 26/26 tests pasando. Automatización por coordenadas y clics vía PyAutoGUI.  
   - **Acción requerida:** Mantener como contingencia de bajo nivel cuando una app Windows no admita control semántico.

---

### 1.4 DO NOT IMPLEMENT / RETIRE FROM ROADMAP (LISTA DE EXCLUSIÓN)
Elementos que **NO deben implementarse** porque ya están cubiertos, son redundantes o representan conceptos inexistentes:

1. **"ARE desde cero" (DO NOT RE-IMPLEMENT):**  
   - Ya está implementado en `core/integration/adapters/are_adapter.py`. No iniciar un nuevo proyecto de razonamiento.
2. **Jarvis-py Integration (RETIRE / DO NOT PURSUE):**  
   - Duplicado funcionalmente por `skills/windows_skills.py`. No aporta valor adicional y agrega complejidad de dependencias.
3. **Documents Skills Legacy (RETIRE):**  
   - `skills/documents_skills.py` es superado completamente por `AnyDoc Core`. Descartar el convertidor legacy.
4. **Mark-LIV (REMOVE FROM ROADMAP):**  
   - 0 archivos en el repositorio. Concepto obsoleto o fantasma.
5. **Hermes (REMOVE FROM ROADMAP):**  
   - 0 archivos en el repositorio. No existe código ni integración iniciada.
6. **Sir Thaddeus / voicecommand / Fish Audio (REMOVE FROM ROADMAP):**  
   - Sustituidos con éxito por el pipeline nativo de EdgeTTS + PocketTTS + Whisper.

---

### 1.5 WHAT ACTUALLY REMAINS (TRABAJO TÉCNICO REAL PENDIENTE)

El plan de trabajo real se ordena estrictamente por dependencias técnicas:

#### Tarea 1: Intercepción Síncrona de JDE en JessycaLocalAgent (P0)
- **Por qué falta:** Actualmente JDE solo observa en modo Shadow dentro de `agent.py`. Para cumplir con "JDE Full Authority", cada turno de ejecución de herramienta debe evaluarse síncronamente antes de invocar la acción.
- **Qué existe actualmente:** `JDEEngine` certificado en Fase 8 (`core/jde/engine.py`) y `JDEShadowAdapter` en `agent.py`.
- **Qué hay que implementar:** Switch condicional en `agent.py` que permita invocar `JDEEngine.evaluate()` de forma bloqueante antes del despacho de herramientas, abortando si el veredicto es REJECT.
- **Riesgos:** Falsos rechazos en comandos de usuario legítimos si la política es excesivamente rígida.
- **Modo inicial:** `CONTROLLED_AUTHORITY`.

#### Tarea 2: Activación y Vinculación de ARE en el Flujo de Tareas (P1)
- **Por qué falta:** `are_adapter.py` está listo y probado (28/28 tests), pero desconectado del agente (`enabled=False`).
- **Qué existe actualmente:** `core/integration/adapters/are_adapter.py` y `tests/test_are_adapter.py`.
- **Qué hay que implementar:** Registrar las capabilities de ARE en `agent.py` o en el orquestador para permitir descomposición de metas multi-paso complejas (`are.decompose_task`) y recuperación automática de planes (`are.recover_plan`).
- **Riesgos:** Sobrecarga de latencia si se invoca descomposición en tareas triviales de un solo paso.
- **Modo inicial:** `CONTROLLED` (solo invocar ante tareas clasificadas como COMPLEJAS).

#### Tarea 3: Unificación del Procesador de Documentos hacia AnyDoc (P2)
- **Por qué falta:** Coexistencia de `skills/documents_skills.py` (legacy) y `core/anydoc/`.
- **Qué existe actualmente:** `core/anydoc/` certificado en Fase 3 con 15 formatos soportados.
- **Qué hay que implementar:** Migrar cualquier referencia de herramientas hacia `AnyDocSkill` y retirar o marcar deprecado `documents_skills.py`.
- **Riesgos:** Ninguno; AnyDoc es un superconjunto estricto.

#### Tarea 4: Test de Certificación E2E de Cadena Completa (P1)
- **Por qué falta:** No hay test que atraviese WebUI/Mobile -> Agent -> JDE Full -> ARE -> ORCA/AnyDoc -> Receipts.
- **Qué existe actualmente:** Pruebas unitarias y de módulo aisladas (3,480 tests).
- **Qué hay que implementar:** Suite E2E de integración (`tests/e2e/test_full_chain_governance.py`).

---

## 2. NEXT TECHNICAL STEP (SIGUIENTE PASO TÉCNICO ÚNICO)

```text
NEXT TECHNICAL STEP:
JDE RUNTIME BINDING — ACTIVACIÓN DE EVALUACIÓN SÍNCRONA DE JDE EN JESSYCALOCALAGENT
```

**Justificación técnica:**  
Antes de activar ARE, ORCA o AnyDoc en el bucle principal de usuario, el árbitro central (`JDEEngine`) debe tener la capacidad real de autorizar o vetar las acciones del agente en tiempo de ejecución, superando el estado actual de mero observador en modo Shadow.
