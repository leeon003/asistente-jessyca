# JESSYCA PC — INVENTARIO COMPLETO DE COMPONENTES
**Fecha:** 2026-09-27  
**Sistema:** JESSYCA PC  
**Alcance:** Módulos de Core, Skills, Adapters, Memory, Voice, Interfaces, Security, LLM, CLI  
**Total Tests Recopilados en el Repositorio:** 3,480  

---

## 1. TABLA MAESTRA DE COMPONENTES

| Componente | Ubicación | Función | Estado | Integrado al Core | JDE | Seguridad | Tests | Certificación |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **JessycaLocalAgent** | `agent.py` | Agente orquestador local de turnos de diálogo y despacho de herramientas | **ACTIVE** | SÍ | Parcial (Shadow) | SÍ | 10 | PASS |
| **JDE Core** | `core/jde/engine.py` | Motor de decisión determinista, resolución de conflictos y mitigación fail-safe | **PRODUCTION CERTIFIED** | SÍ | Autoridad Nativa | SÍ | 163 | Fase 8 Full Authority |
| **JDEShadowAdapter** | `core/jde/adapter.py` | Adaptador observador pasivo para registrar decisiones sin bloquear el flujo | **ACTIVE** | SÍ | Shadow | SÍ | 25 | PASS |
| **Archify Core** | `core/archify/` | Motor de diagramación C4, Mermaid, secuencia, clases y renderizado vectorial | **PRODUCTION CERTIFIED** | SÍ | Subordinado | SÍ | 76 | Fase 3 Active |
| **Archify Skill** | `skills/archify_skill.py` | Exposición de generación e inspección de diagramas para el agente | **PRODUCTION CERTIFIED** | SÍ | Subordinado | SÍ | 15 | Fase 3 Active |
| **ORCA + ADE Core** | `core/orca_ade/` | Orquestación multi-agente aislada mediante Git worktrees y verificación de salida | **PRODUCTION CERTIFIED** | SÍ | Subordinado | SÍ | 64 | Fase 3 Active |
| **AnyDoc Core** | `core/anydoc/` | Motor offline de conversión e inspección de 15 formatos documentales a GFM | **PRODUCTION CERTIFIED** | SÍ | Subordinado | SÍ | 74 | Fase 3 Active |
| **ARE Adapter** | `core/integration/adapters/are_adapter.py` | Descomposición de tareas, evaluación de planes, diagnóstico y recuperación | **CONTROLLED** | Parcial (Hub) | Subordinado | SÍ | 28 | Fase 76.4 Controlled |
| **Jarvis Adapter** | `core/integration/adapters/jarvis_adapter.py` | Estado de sistema, clipboard y gestión de procesos heredada de Jarvis-py | **CONTROLLED / DISABLED** | Parcial (Hub) | Subordinado | SÍ | 30 | Fase 76.2 Controlled |
| **Computer Use Adapter**| `core/integration/adapters/computer_use_adapter.py` | Control de mouse/teclado por coordenadas y captura de ventanas vía PyAutoGUI | **CONTROLLED / DISABLED** | Parcial (Hub) | Subordinado | SÍ | 26 | Fase 76.3 Controlled |
| **Integration Hub** | `core/integration/hub.py` | Registro centralizado, gobernanza y enrutamiento de adaptadores externos | **ACTIVE** | SÍ | Subordinado | SÍ | 20 | PASS |
| **RiskEngine** | `core/security/risk_engine.py` | Evaluación determinista de riesgo de comandos y parámetros (0.0 a 1.0) | **PRODUCTION CERTIFIED** | SÍ | SÍ | Nativo | 45 | PASS |
| **PermissionManager** | `core/security/permission_manager.py` | Control de acceso basado en roles y niveles de privilegio (L0 a L3) | **PRODUCTION CERTIFIED** | SÍ | SÍ | Nativo | 35 | PASS |
| **IdempotencyGuard** | `core/security/idempotency_guard.py` | Prevención de ejecución duplicada mediante tokens UUID, hash y ventanas TTL | **PRODUCTION CERTIFIED** | SÍ | SÍ | Nativo | 25 | PASS |
| **ExecutionVerifier** | `core/security/execution_verifier.py` | Verificación post-ejecución para evitar confirmaciones falsas de éxito | **PRODUCTION CERTIFIED** | SÍ | SÍ | Nativo | 30 | PASS |
| **ExecutionBoundary** | `server/execution_boundary.py` | Contención y límites de ejecución de procesos y comandos en el backend | **PRODUCTION CERTIFIED** | SÍ | SÍ | Nativo | 35 | PASS |
| **MemoryManager** | `core/memory/memory_manager.py` | Gestión unificada de memoria de trabajo, corto y largo plazo | **ACTIVE** | SÍ | N/A | SÍ | 15 | PASS |
| **LocalVectorStore** | `core/memory/vector_store.py` | Base de datos vectorial local con embeddings `all-MiniLM-L6-v2` | **ACTIVE** | SÍ | N/A | SÍ | 12 | PASS |
| **ContradictionDetector**| `core/memory/contradiction_detector.py` | Detección de inconsistencias entre memoria histórica y nuevos hechos | **ACTIVE** | SÍ | N/A | SÍ | 10 | PASS |
| **ModelRouter 2.0** | `core/llm/model_router.py` | Enrutamiento inteligente de modelos (Nemotron / Qwen / Gemma) según intención | **CONTROLLED** | SÍ | Parcial | SÍ | 68 | Fase 6 Controlled |
| **ExperimentalRouter**| `core/llm/experimental_router.py` | Motor de enrutamiento experimental por complejidad y heurísticas de VRAM | **LAB** | SÍ | Shadow | SÍ | 40 | Fase 4 Lab |
| **VoiceService** | `services/voice_service.py` | Pipeline de voz con EdgeTTS (`CamilaNeural`), PocketTTS y Whisper STT | **ACTIVE** | SÍ | N/A | SÍ | 85 | PASS |
| **AudioDeviceManager**| `services/audio_device_manager.py` | Detección, selección y resolución dinámica de dispositivos de audio en Windows | **ACTIVE** | SÍ | N/A | SÍ | 38 | PASS |
| **Windows Skills** | `skills/windows_skills.py` | Habilidades nativas de Windows (apps, media, screenshot, clipboard, audio) | **PRODUCTION CERTIFIED** | SÍ | Subordinado | SÍ | 50+ | PASS |
| **Browser Skill** | `skills/browser_skill.py` | Automatización de navegador y reproducción/búsqueda web | **ACTIVE** | SÍ | Subordinado | SÍ | 16 | PASS |
| **Documents Skills** | `skills/documents_skills.py` | Lectura básica de documentos (reemplazado funcionalmente por AnyDoc) | **OVERLAPPING / LEGACY**| SÍ | Subordinado | SÍ | 10 | PASS |
| **WebUI Bridge** | `interfaces/webui_bridge/` | Servidor FastAPI OpenAI-compatible (puerto 8088) para conectar Open WebUI | **ACTIVE** | SÍ | Externo | SÍ | 15 | PASS |
| **Mobile API** | `interfaces/mobile_api/` | Servidor FastAPI (puerto 8765) con autenticación por token para app móvil | **ACTIVE** | SÍ | Externo | SÍ | 10 | PASS |
| **Command Server** | `server/server.py` | Daemon de servicios de comandos Windows con autenticación y límites | **ACTIVE** | SÍ | SÍ | SÍ | 25 | PASS |
| **CLI REPL** | `main.py` | Interfaz interactiva de consola con soporte de modos `--text`, `--voice` | **ACTIVE** | SÍ | SÍ | SÍ | 10 | PASS |
| **Mark-LIV** | Inexistente | N/A | **NOT FOUND** | NO | NO | NO | 0 | Inexistente |
| **Hermes** | Inexistente | N/A | **NOT FOUND** | NO | NO | NO | 0 | Inexistente |
| **Sir Thaddeus** | Inexistente | N/A | **NOT FOUND** | NO | NO | NO | 0 | Inexistente |
| **Fish Audio** | Inexistente | N/A | **NOT FOUND** | NO | NO | NO | 0 | Inexistente |

---

## 2. DISTRIBUCIÓN POR ESTADOS

- **PRODUCTION CERTIFIED:** 9 componentes (JDE Core, Archify Core, Archify Skill, ORCA+ADE Core, AnyDoc Core, RiskEngine, PermissionManager, IdempotencyGuard, Windows Skills).
- **ACTIVE:** 11 componentes (JessycaLocalAgent, JDEShadowAdapter, Integration Hub, MemoryManager, LocalVectorStore, ContradictionDetector, VoiceService, AudioDeviceManager, WebUI Bridge, Mobile API, Command Server).
- **CONTROLLED:** 3 componentes (ARE Adapter, Jarvis Adapter, ModelRouter 2.0).
- **LAB:** 1 componente (ExperimentalRouter).
- **OVERLAPPING / LEGACY:** 1 componente (Documents Skills).
- **DISABLED (en settings):** 2 componentes (Jarvis Adapter, Computer Use Adapter).
- **NOT FOUND:** 4 componentes (Mark-LIV, Hermes, Sir Thaddeus, Fish Audio).
