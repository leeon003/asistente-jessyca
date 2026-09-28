# JESSYCA PC — MATRIZ Y AUDITORÍA DE INTEGRACIONES
**Fecha:** 2026-09-27  
**Sistema:** JESSYCA PC  
**Alcance:** Evaluación exhaustiva de todas las tecnologías integradas, adaptadores, puentes externos y subsistemas especializados.

---

## 1. MATRIZ DE INTEGRACIONES

| Integración | Módulo / Ubicación | Tipo de Enlace | Gobernanza JDE | Seguridad | Estado Técnico | Evidencia en Repositorio |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| **Archify** | `core/archify/` & `skills/archify_skill.py` | Nativo en Core + Skill | Subordinado | Sandboxed | **PRODUCTION CERTIFIED (ACTIVE)** | `reports/archify_phase3_certification.md`, 76 tests dedicados pasando al 100%. |
| **ORCA + ADE** | `core/orca_ade/` & `lab/orca_ade/` | Nativo en Core + Subagentes | Subordinado | Worktree Isolation | **PRODUCTION CERTIFIED (ACTIVE)** | `reports/orca_ade_phase3_certification.md`, 64 tests dedicados pasando al 100%. |
| **AnyDoc** | `core/anydoc/` & `lab/anydoc/` | Nativo en Core + Skill | Subordinado | Path Sandbox | **PRODUCTION CERTIFIED (ACTIVE)** | `reports/anydoc_phase3_certification.md`, 74 tests dedicados pasando al 100%. |
| **ARE** | `core/integration/adapters/are_adapter.py` | Adaptador en Integration Hub | Subordinado | Contrato de Plan | **CONTROLLED (DISABLED BY CONFIG)** | `tests/test_are_adapter.py` (28/28 tests PASS). Flag `are.enabled=False` en settings. |
| **Jarvis-py** | `core/integration/adapters/jarvis_adapter.py` | Adaptador en Integration Hub | Subordinado | Process Limits | **CONTROLLED (DISABLED BY CONFIG)** | `tests/test_jarvis_adapter.py` (30/30 tests PASS). Flag `jarvis.enabled=False`. |
| **Computer Use**| `core/integration/adapters/computer_use_adapter.py` | Adaptador en Integration Hub | Subordinado | Coordenadas/Failsafe | **CONTROLLED (DISABLED BY CONFIG)** | `tests/test_computer_use_adapter.py` (26/26 tests PASS). Flag `windows_computer_use.enabled=False`. |
| **Open WebUI** | `interfaces/webui_bridge/` | Proxy FastAPI OpenAI-compatible | Externo | Bearer Token Auth | **ACTIVE (JESSYCA-BACKED)** | `interfaces/webui_bridge/app.py` en puerto 8088 con streaming SSE hacia `JessycaLocalAgent`. |
| **Mobile API** | `interfaces/mobile_api/` | Servidor REST FastAPI | Externo | `X-Jessyca-Token` Auth | **ACTIVE (BACKEND OPERACIONAL)** | `interfaces/mobile_api/main.py` en puerto 8765, endpoints `/api/v1/chat`, `/api/v1/health`. |
| **Model Router**| `core/llm/model_router.py` | Core LLM Pipeline | Subordinado | Fallback Chain | **CONTROLLED (SHADOW BY DEFAULT)** | `.env` con `MODEL_ROUTER_MODE=shadow`, 108 tests pasando, umbral 0.80. |
| **Voice Engine**| `services/voice_service.py` | Servicio de Voz Unificado | Integrado | Audio Device Resolver| **ACTIVE** | EdgeTTS (`es-PE-CamilaNeural`) + PocketTTS, Whisper STT local, 80+ tests. |
| **Memory RAG** | `core/memory/` | Motor de Memoria Vectorial | Integrado | Sanitize & De-dup | **ACTIVE** | `LocalVectorStore` con `all-MiniLM-L6-v2`, `ContradictionDetector`, 50+ tests. |
| **Mark-LIV** | Inexistente | N/A | N/A | N/A | **NOT FOUND** | 0 archivos, 0 imports, 0 referencias en todo el árbol de código. |
| **Hermes** | Inexistente | N/A | N/A | N/A | **NOT FOUND** | 0 archivos, 0 imports, 0 referencias en todo el árbol de código. |
| **Sir Thaddeus**| Inexistente | N/A | N/A | N/A | **NOT FOUND** | 0 archivos, 0 imports, 0 referencias en todo el árbol de código. |
| **Fish Audio** | Inexistente | N/A | N/A | N/A | **NOT FOUND** | No implementado. Sustituido por Edge-TTS / Pocket-TTS. |

---

## 2. ANÁLISIS DETALLADO POR INTEGRACIÓN

### 2.1 Archify
- **Capacidades:** Generación determinista de diagramas C4 (Context, Container, Component), diagramas de secuencia, diagramas de clases, diagramas de estado y diagramas de flujo. Exportación a Mermaid, PNG y SVG.
- **Seguridad:** Aislamiento estricto de workspace, validación de rutas contra path traversal y desinfección de sintaxis Mermaid para evitar inyecciones.
- **Gobernanza JDE:** Plenamente integrado y subordinado a la autoridad del JDE. Registrado como capability provider en el core de JESSYCA.
- **Certificación:** Completada Fase 3 con 76 tests de producción pasando sin regresiones.

### 2.2 ORCA + ADE
- **Capacidades:** Creación de tareas de desarrollo asistido, orquestación de sub-agentes en paralelo, aislamiento de código mediante Git worktrees independientes, recopilación estructurada de resultados, revisión de diffs y verificación de estado.
- **Seguridad:** Aislamiento de ramas/carpetas efímeras, control de ejecución de comandos por lista blanca y límites de tiempo por tarea.
- **Gobernanza JDE:** Totalmente subordinado al JDE; ninguna tarea paralela puede ejecutarse o fusionarse en producción sin autorización del JDE.
- **Certificación:** Completada Fase 3 con 64 tests de producción pasando sin regresiones.

### 2.3 AnyDoc (Firecrawl AnyDoc Core)
- **Capacidades:** Conversión offline y sin dependencias de red de 15 formatos (`.docx`, `.xlsx`, `.pptx`, `.pdf`, `.odt`, `.rtf`, `.csv`, etc.) a GitHub-Flavored Markdown. Extracción de tablas limpias, jerarquía de encabezados e inspección de metadatos.
- **Seguridad:** Sandbox estricto de rutas de entrada/salida, límites de tamaño de archivo (máx 50MB por defecto), límites de memoria y timeout de conversión.
- **Gobernanza JDE:** Subordinado al JDE. Registrado como capability provider documental.
- **Certificación:** Completada Fase 3 con 74 tests de producción pasando sin regresiones.

### 2.4 ARE (Agent Reasoning Engine)
- **Realidad Descubierta:** Lejos de ser un componente ausente que deba planearse e implementarse desde cero, ARE **ya se encuentra implementado en el repositorio** en `core/integration/adapters/are_adapter.py`.
- **Capacidades Implementadas:**
  1. `are.decompose_task`: Descomposición de objetivos complejos en grafos dirigidos acíclicos (DAG) de subtareas con dependencias explícitas.
  2. `are.evaluate_plan`: Validación estructural, detección de ciclos y chequeo de precondiciones de planes.
  3. `are.diagnose_failure`: Análisis de causa raíz ante fallos de herramientas con clasificación del error.
  4. `are.recover_plan`: Generación determinista de planes de contingencia y compensación.
- **Batería de Pruebas:** `tests/test_are_adapter.py` contiene 28 pruebas completas que verifican idempotencia, seguridad de inyección, timeouts y gobernanza. **100% PASS (28/28)**.
- **Estado Actual:** `CONTROLLED`, desactivado en `config/settings.py` (`INTEGRATIONS_ADAPTERS["are"]["enabled"] = False`).

### 2.5 Jarvis-py
- **Implementación:** `core/integration/adapters/jarvis_adapter.py`. Provee capacidades `jarvis.get_system_status`, `jarvis.get_clipboard`, `jarvis.set_clipboard`, `jarvis.open_app`, `jarvis.close_app`.
- **Diagnóstico:** Duplica funcionalidad nativa de `skills/windows_skills.py`. No aporta valor único sobre las capacidades nativas de Windows ya certificadas. Desactivado por defecto.

### 2.6 Computer Use / Windows
- **Implementación:** `core/integration/adapters/computer_use_adapter.py`. Automatización basada en GUI (`pyautogui` y `psutil`), captura de pantallas de ventanas específicas y envío de clics/teclas por coordenadas.
- **Diagnóstico:** Útil únicamente cuando una aplicación no tiene interfaz semántica o CLI. Permanece en modo controlado/desactivado por seguridad hasta requerir interacción GUI ciega.

### 2.7 Open WebUI Bridge
- **Implementación:** `interfaces/webui_bridge/app.py`. Servidor FastAPI que expone `/v1/chat/completions` simulando la API de OpenAI.
- **Conexión:** Redirige las solicitudes directamente a `JessycaLocalAgent.interact()`, devolviendo streaming de tokens vía SSE (Server-Sent Events).
- **Veredicto:** Es un puente **JESSYCA-BACKED** completamente funcional, no una conexión directa a Ollama. Open WebUI interactúa con JESSYCA como si fuera un modelo OpenAI.

### 2.8 Mobile API
- **Implementación:** `interfaces/mobile_api/main.py`. Servidor REST FastAPI en el puerto 8765.
- **Endpoints:** `/api/v1/chat`, `/api/v1/health`.
- **Autenticación:** Cabecera `X-Jessyca-Token` validada contra configuración.
- **Veredicto:** El backend móvil está listo y activo; el frontend (Flutter/Android) reside fuera del repositorio principal.

### 2.9 Model Router
- **Implementación:** `core/llm/model_router.py` (Smart Model Routing 2.0).
- **Modelos:** Enrutamiento entre `nvidia/nemotron-mini:latest` (tareas de razonamiento estructurado), `qwen2.5:3b` (general / velocidad) y `gemma2:2b` (fallback ligero).
- **Modo en Configuración:** `MODEL_ROUTER_MODE=shadow` en `.env`. Opera registrando telemetría y comparando sin forzar re-enrutamientos disruptivos.

### 2.10 Tecnologías Inexistentes (Phantoms)
- **Mark-LIV:** Sin registros ni código.
- **Hermes:** Sin registros ni código.
- **Sir Thaddeus:** Sin registros ni código.
- **Fish Audio:** Sin registros ni código (sustituido de facto por Edge-TTS de Microsoft y Pocket-TTS local).
