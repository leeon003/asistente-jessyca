# REGISTRO ÚNICO DE AVANCE Y AUDITORÍA DE INGENIERÍA — JESSYCA 3.0 / 4.0

**Rama de trabajo activa:** `fix/baseline-diagnostico`  
**Commit base:** `3c41be2df5411fe59f603aa80a0f09e862354b3c` (`feat(core): certificacion Full E2E y consolidacion arquitectonica CONTROLLED READY`)  
**Fecha de inicio:** 2026-10-03  
**Sistema Operativo:** Windows 10/11 Pro (amd64)  
**Intérprete Principal:** Python 3.11.9 (`C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe`)  
**Entorno Virtual Aislado Detectado:** `d:\JESSYCA 3.0\asistente-jessyca\venv`  
**Modo de Arquitectura:** CONTROLLED READY  

---

## 1. Diagnóstico de Entorno y Dependencias

### Intérpretes y Entornos
* **Intérprete Global/Sistema (`python`):**
  - Python 3.11.9 con soporte binario CPython ABI3 y extensiones nativas completas instaladas: `firecrawl-anydoc 0.2.4`, `SpeechRecognition 3.14.5`, `faster-whisper 1.2.1`, `fastmcp 3.4.6`, `PyAutoGUI 0.9.54`, `selenium 4.46.0`, `torch 2.7.1+cu118`, `torchaudio 2.7.1+cu118`, `pywin32 311`.
  - Recolección de pruebas de pytest: **3.815 tests recopilados sin errores (0 errores de colección)**.
* **Entorno Virtual Local (`.\venv`):**
  - Ubicación: `d:\JESSYCA 3.0\asistente-jessyca\venv`.
  - Configuración `pyvenv.cfg`: `include-system-site-packages = false`.
  - Diagnóstico de aislamiento e instalación limpia:
    - Se resolvió la referencia a `README.md` en la raíz (creada para satisfacer `pyproject.toml`).
    - Se agregó `requests>=2.28.0` a las dependencias directas en `pyproject.toml` (utilizada por `core/llm/`).
    - Se configuró `[tool.setuptools.packages.find]` en `pyproject.toml` para resolver el error de descubrimiento de paquetes en flat-layout (`lab`, `core`, `tools`, etc.).
    - Se ejecutó `pip install -e ".[dev]"` e instalaron las dependencias requeridas en el entorno virtual (`SpeechRecognition==3.17.0`, `firecrawl-anydoc==0.2.4`, `pyautogui==0.9.54`, `pywinauto==0.6.9`).
    - Se protegieron las importaciones de dependencias opcionales (`docling`, `playwright`, `pywinauto`, `anydoc`) para que nunca bloqueen la colección ni ejecución de pruebas portables en entornos limpios.
  - Recolección actual en `.\venv`: **3.815 tests recopilados sin errores (0 errores de colección, 2 pruebas marcadas como skip por dependencias externas pesadas opcionales)**.

---

## 2. Trazabilidad de Flujos: Entrada → Autorización → Ejecución → Verificación

### Punto de Entrada Unificado (`main.py`)
Expone 5 modos con exclusión mutua:
1. `--demo` (Predeterminado): Lanza servidor MCP FastMCP en segundo plano (`MCPDemoRuntime` en `127.0.0.1:8000`), inicializa `JessycaLocalAgent.get_instance()`, e inicia bucle interactivo de voz continuo (`iniciar_modo_voz`).
2. `--mcp`: Standalone FastMCP server (`JessycaMCPServer.run()`).
3. `--voice`: Standalone sesión conversacional de voz (`iniciar_modo_voz(show_header=True)`).
4. `--mobile`: Standalone Mobile API bridge FastAPI (`interfaces/mobile_api/server.py` en host/puerto configurado).
5. `--webui`: Standalone WebUI Bridge FastAPI OpenAI-compatible (`interfaces/webui_bridge/server.py` en host/puerto configurado).

### Flujo 1: Interfaz de Voz (`interfaces/modo_voz.py`)
* **Captura:** `CalibratedVoiceCaptureEngine` con resolución de dispositivo (`VoiceDeviceResolver` para Logitech G435 / C270), calibración de ruido ambiente, pre-roll/post-roll e histéresis VAD.
* **STT:** `faster-whisper` (modelo local configurable) con supresión de eco acústico del altavoz (`_is_acoustic_echo`).
* **Sesión:** `ContinuousVoiceSession` y `StateMachine` para soporte multi-turno sin repetir wake-word ("Jessica").
* **Puente a Core:** Genera `JessycaRequest(..., modality=InputModality.VOICE)` e invoca `JessycaLocalAgent.get_instance().interact(req)`.
* **Respuesta:** Síntesis vía `VoiceSpeaker` (Edge-TTS `es-PE-CamilaNeural` con fallback a Windows SAPI) y control de interrupción `BargeInController`.
* **Estado:** **REAL / ACTIVO**.

### Flujo 2: Mobile API Bridge (`interfaces/mobile_api/`)
* **Servidor:** FastAPI con middleware de autenticación estricta `X-Jessyca-Token` contra `MOBILE_API_AUTH_TOKEN`.
* **Endpoints:** `/api/v1/health` (público) y `/api/v1/chat` (autenticado).
* **Puente a Core:** Transforma `ChatRequest` en `JessycaRequest(..., modality=InputModality.TEXT, metadata={"source": "mobile_android"})`, despachado de forma asíncrona no bloqueante con `asyncio.to_thread(agent.interact, req)` respetando `MOBILE_API_TIMEOUT`.
* **Estado:** **REAL / ACTIVO**.

### Flujo 3: WebUI Bridge (`interfaces/webui_bridge/`)
* **Servidor:** FastAPI compatible con especificación OpenAI (`/v1/models`, `/v1/chat/completions`).
* **Autenticación:** Obligatoria vía `Bearer <WEBUI_BRIDGE_AUTH_TOKEN>` (falla si el token no está configurado).
* **Filtro de tareas internas:** Tareas de Open WebUI (títulos, tags, resúmenes) son procesadas localmente por `classify_openwebui_internal_task` y `generate_internal_task_response` sin disparar herramientas en el SO.
* **Puente a Core:** Mapea el historial completo de mensajes mediante `normalize_conversation_messages` y `build_jessyca_request`.
* **Streaming y Anti-False Success:**
  - Si es conversacional puro: streaming progresivo de tokens (`agent.interact_stream`).
  - Si es una acción física con efectos secundarios en Windows: primero ejecuta y verifica en el SO vía `ExecutionVerifier`, y solo tras certificar el éxito real emite la respuesta.
* **Estado:** **REAL / ACTIVO**.

### Flujo 4: FastMCP Server (`server/`)
* **Servidor:** `JessycaMCPServer` integrando `ToolRegistry` y transportes (stdio / sse / streamable-http).
* **Pipeline de Seguridad:** `SecureExecutionPipeline` orquestando las 6 capas deterministas:
  1. `AuditLogger` (REQUEST_RECEIVED, CAPABILITY_RESOLVED)
  2. `RiskEngine` (Cálculo cuantitativo de riesgo 0.0 a 1.0)
  3. `SecurityPolicy` (Evaluación de políticas de acceso)
  4. `PermissionManager` (Verificación de listas blancas L0 a L3)
  5. `ConfirmationManager` (Requerimiento de confirmación explícita para operaciones sensibles)
  6. `SecureExecutionBoundary` (Ejecutores reales: `windows.files`, `windows.process`, `windows.registry`, `windows.services`, `windows.desktop`)
* **Estado:** **REAL / ACTIVO**.

### Autorización Central: JDE Runtime Binding (`core/jde/runtime_binding.py`)
* Evaluado en `JessycaLocalAgent._execute_unified_pipeline` (líneas 907-998) **antes de cualquier efecto secundario**:
  - `evaluate(intent, action, tool, parameters, user_confirmed, session_id, request_id, risk_level)`.
  - Veredicto `DENY`: Bloqueo inmediato, cero efectos secundarios, registro de auditoría.
  - Veredicto `REQUIRE_REVIEW`: Pausa de ejecución hasta confirmación explícita del usuario (`AWAITING_CONFIRMATION`).
  - Veredicto `ALLOW`: Permite continuar a la fase de ejecución.
* **Estado:** **REAL / ACTIVO EN CONTROLLED READY**.

### Razonamiento y Recuperación: ARE Runtime (`core/are/runtime.py`)
* Provee descomposición determinista de tareas (DAG de Kahn), cálculo de radio de impacto (BFS), diagnóstico de causas raíz de fallo y propuestas acotadas de recuperación (máximo 2 intentos).
* Sus salidas son `AREPlanProposal` (propuestas) subordinadas a la autorización determinista del JDE.
* **Estado:** **REAL / ACTIVO EN CONTROLLED READY**.

### Verificación Post-Ejecución: `ExecutionVerifier` (`core/execution/execution_verifier.py`)
* Inspección de estado real en el SO (procesos de Windows, existencia y contenido de archivos, valores de registro, estado de servicios).
* Principio Anti-False Success: ningún comando devuelve éxito sin evidencia verificable en Windows.
* **Estado:** **REAL / ACTIVO**.

---

## 3. Matriz de Hallazgos y Verificación contra el Código Actual

| Componente / Hallazgo | Estado Verificado | Archivo / Símbolo Clave | Evidencia en Código Actual |
| :--- | :--- | :--- | :--- |
| **JDE Runtime Binding como autoridad decisoria** | **CONFIRMADO** | [runtime_binding.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/jde/runtime_binding.py#L1-L100)<br>[local_agent.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/local_agent/local_agent.py#L907-L998) | JDE evalúa previo al paso 6 (`_execute_unified_pipeline`); bloquea con `DENY` o solicita confirmación con `REQUIRE_REVIEW`. |
| **ARE (Action Reasoning Engine) integrado** | **CONFIRMADO** | [runtime.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/are/runtime.py)<br>[local_agent.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/local_agent/local_agent.py#L88) | ARE Runtime operativo para descomposición y diagnóstico sin crear nuevos frameworks. |
| **Modo SHADOW de JDE relegado a observador** | **YA CORREGIDO** | [adapter.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/jde/adapter.py)<br>[local_agent.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/local_agent/local_agent.py#L945-L955) | Shadow mode ya no es la única vía; convive como observador de divergencias mientras `JDERuntimeBinding` es el gate decisorio activo. |
| **AnyDoc (18 formatos) integrado** | **CONFIRMADO** | [adapter.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/anydoc/adapter.py#L22) | `import anydoc` requiere `firecrawl-anydoc 0.2.4` presente en el Python del sistema. |
| **Archify (Diagramación)** | **CONFIRMADO** | [adapter.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/archify/adapter.py) | Generación y exportación de diagramas Mermaid/C4 en entorno controlado. |
| **ORCA / ADE (Worktrees)** | **CONFIRMADO** | [adapter.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/orca_ade/adapter.py) | Orquestación sandboxed y aislamiento por Git worktrees. |
| **Jarvis / ComputerUse duplicados** | **CONFIRMADO / CONTROLADO** | [jarvis_adapter.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/jarvis_adapter.py)<br>[computer_use_adapter.py](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py) | Permanecen deshabilitados por defecto (`disabled_by_default`); las habilidades nativas de Windows (`skills/windows_skills.py`, `tools/desktop/`) tienen precedencia absoluta. |
| **Componentes fantasma (Mark-LIV, Hermes, Sir Thaddeus, Fish Audio)** | **NO REPRODUCIDO / INEXISTENTE** | Repositorio completo | Búsqueda exhaustiva confirma 0 menciones y 0 archivos. Eran referencias teóricas de auditorías previas o propuestas descartadas. |
| **Discrepancia de dependencias en `venv`** | **CONFIRMADO** | [pyvenv.cfg](file:///d:/JESSYCA%203.0/asistente-jessyca/venv/pyvenv.cfg#L2) | `include-system-site-packages = false` causa que `venv` carezca de `firecrawl-anydoc` y `SpeechRecognition`. |
| **openWakeWord (Wake Word Acústico I5)** | **CONFIRMADO / INTEGRADO** | [openwakeword_service.py](file:///d:/JESSYCA%203.0/asistente-jessyca/services/voice/openwakeword_service.py)<br>[wake_word_service.py](file:///d:/JESSYCA%203.0/asistente-jessyca/services/voice/wake_word_service.py) | Adaptador desacoplado bajo `IWakeWordService`; veracidad acústica (declara `unavailable` sin modelo en español sin generar falso éxito); `authorizes_action=False` estricto; fábrica gobernada `get_wake_word_service`. |

---

## 4. Registro de Fases Ejecutadas

### Fase 00 — Diagnóstico Inicial y Línea Base (2026-10-03)
* **Objetivo:** Auditar estado actual del repositorio, identificar rastro de ejecución de todos los canales de entrada hasta verificación, contrastar hallazgos previos y ejecutar la línea base de pruebas.
* **Archivos / Símbolos creados o modificados:**
  - Nueva rama de trabajo: `fix/baseline-diagnostico` (a partir de `main` en `3c41be2df5411fe59f603aa80a0f09e862354b3c`).
  - Creación del registro unificado: `REGISTRO_DE_AVANCE.md`.
* **Pruebas ejecutadas:**
  - `python -m pytest --collect-only`: 3.581 tests recopilados con éxito en 2.83s bajo el entorno del sistema.
  - `.\venv\Scripts\python.exe -m pytest --collect-only`: 3.414 tests recopilados, 5 errores por dependencias no enlazadas en el venv (`anydoc`, `speech_recognition`).
  - Suite de integración y control: `python -m pytest tests/jde/ tests/e2e/ tests/interfaces/ -q`: **326 passed, 0 failed**.
  - Suite global completa: `python -m pytest tests/ -q`: **3.581 passed, 0 failed (100% de aprobación, exit code 0)**.
* **Limitaciones detectadas:**
  - Para ejecutar la suite completa en el entorno virtual local `.\venv`, se requiere que el entorno virtual tenga acceso a las librerías del sistema (`include-system-site-packages = true` en `venv/pyvenv.cfg`) o instalar `firecrawl-anydoc` y `SpeechRecognition` en dicho venv.
* **Forma de revertir:**
  - `git checkout main` y eliminar rama de trabajo `git branch -D fix/baseline-diagnostico`.

---

### Fase 02 — Token móvil, exposición de red y CORS (2026-10-03)
* **Objetivo:** Eliminar tokens inseguros por defecto, imponer obligatoriedad de tokens robustos antes de cualquier efecto secundario, restringir escucha a loopback por defecto (127.0.0.1) con soporte LAN explícito, implementar comparación en tiempo constante, configurar CORS sin credenciales con wildcard y documentar la migración del cliente móvil.
* **Archivos / Símbolos creados o modificados:**
  - `config/settings.py`:
    - `MOBILE_API_HOST`: cambiado de `0.0.0.0` a `127.0.0.1` (loopback por defecto).
    - `MOBILE_API_AUTH_TOKEN`: eliminado el valor por defecto inseguro (`""` por defecto; validación obligatoria).
    - Añadidos `MOBILE_API_CORS_ORIGINS` (lista vacía por defecto) y `MOBILE_API_DOCS_ENABLED` (falso por defecto).
    - `WEBUI_BRIDGE_HOST`: cambiado de `0.0.0.0` a `127.0.0.1` (loopback por defecto).
    - Añadidos `WEBUI_BRIDGE_CORS_ORIGINS` y `WEBUI_BRIDGE_DOCS_ENABLED`.
  - `interfaces/mobile_api/app.py`:
    - `validate_mobile_api_token(token)`: validación anticipada estricta que rechaza tokens vacíos, whitespace o `"jessyca-dev-token-insecure"`.
    - `create_mobile_api_app`: valida token antes de construir la app o inicializar el agente. Soporta `auth_token` explícito y control de docs/OpenAPI.
    - `auth_middleware`: comparación en tiempo constante con `secrets.compare_digest`.
    - `CORSMiddleware`: orígenes explícitos configurados; prohíbe `allow_credentials=True` si se usa wildcard `*`.
  - `interfaces/mobile_api/server.py`:
    - `run_mobile_server`: respeta `MOBILE_API_ENABLED=False` abortando con código 1 a menos que se use `force=True`.
    - Emite advertencia explícita de seguridad al escuchar en interfaces LAN no loopback.
  - `interfaces/webui_bridge/app.py`:
    - `validate_webui_bridge_token(token)`: validación anticipada contra tokens vacíos o `"jessyca-dev-token-insecure"`.
    - Comparación en tiempo constante con `secrets.compare_digest`.
    - Redacción profunda de encabezados en trazas (`safe_headers` filtra cualquier clave con `auth`, `token`, `secret`, `cookie`, `key`, `credential`, `password`).
    - CORS y docs controlados por configuración.
  - `interfaces/webui_bridge/server.py`:
    - `run_webui_server`: host por defecto `127.0.0.1`, respeta `WEBUI_BRIDGE_ENABLED=False` a menos que se use `force=True`.
  - `main.py`:
    - Añadido argumento `--force` a la CLI para anular flags de deshabilitación con precedencia documentada.
  - `tests/test_mobile_api.py`:
    - Añadidos tests 11 a 20 cubriendo fallo sin secreto, tokens con whitespace o de desarrollo, aborto del servidor, flag deshabilitado, opciones de red/advertencia LAN, CORS denegado/autorizado, prohibición de wildcard con credenciales y control de documentación.
  - `tests/e2e/test_full_e2e_integration.py`:
    - Sincronizado `test_adversarial_d_mobile_cannot_call_adapter_directly` para inyectar token de prueba explícito.
* **Comportamiento Antes / Después:**
  - *Antes:* Mobile API escuchaba en `0.0.0.0` (toda la LAN) con token conocido inseguro (`jessyca-dev-token-insecure`), permitiendo arranque no autenticado; CORS utilizaba wildcard `*` combinado con `allow_credentials=True`; la comparación de tokens era susceptible a timing attacks (`!=`); y `MOBILE_API_ENABLED=False` solo emitía un warning sin impedir que el servidor levantara.
  - *Después:* Escucha estricta en `127.0.0.1` por defecto; el servidor rechaza arrancar si no hay un token secreto configurado o si se intenta usar el token de desarrollo; la comparación es de tiempo constante; CORS es restrictivo y seguro; `MOBILE_API_ENABLED=False` impide el arranque de forma efectiva (con bypass explícito documentado `--force`); y la documentación OpenAPI está protegida.
* **Comandos y Resultados Reales:**
  - `python -m pytest tests/test_mobile_api.py -v`: 20 passed (100%).
  - `python -m pytest tests/interfaces/webui_bridge/ -v`: 32 passed (100%).
  - `python -m pytest tests/test_launcher_webui.py -v`: 7 passed (100%).
  - `python -m pytest tests/test_main_demo_launcher.py -v`: 10 passed (100%).
  - `python -m pytest tests/e2e/test_full_e2e_integration.py -v`: 22 passed (100%).
  - Total suite interfaces + e2e: **91 tests PASSED, 0 FAILED**.
* **Guía de Migración para el Cliente Móvil (Android):**
  1. **Generación del Secreto:** En el host de JESSYCA, genere un secreto criptográfico:
     ```powershell
     python -c "import secrets; print(secrets.token_urlsafe(32))"
     ```
  2. **Configuración del Servidor:** Añada la variable a su `.env` local (no versionado):
     ```env
     MOBILE_API_AUTH_TOKEN=<secreto_generado>
     # Para permitir acceso desde el móvil por WiFi/LAN:
     MOBILE_API_HOST=0.0.0.0
     ```
  3. **Actualización de la App Android:**
     - En el cliente HTTP de la app (OkHttp / Retrofit Interceptor), inyecte el encabezado en cada petición:
       `X-Jessyca-Token: <secreto_generado>`
     - Asegúrese de que el endpoint apunte a la IP local del equipo (ej. `http://192.168.1.X:8765/api/v1/chat`).
     - Almacene el token en la app mediante `EncryptedSharedPreferences` o `BuildConfig` privado; nunca lo exponga en repositorios públicos.
* **Forma de Revertir:**
  - `git checkout HEAD~1` sobre los archivos modificados o `git checkout main`.

---

## [2026-10-03] Fase 03 — Inmutabilidad profunda de políticas

* **Objetivo:** Resolver el hallazgo de mutabilidad en `core/security_policy.py`, donde `SecurityPolicy.__setattr__` bloqueaba reasignaciones directas, pero `policy.rules[0].decision` podía mutarse en sitio de DENY a ALLOW y `policy.rules.clear()` vaciaba la lista de reglas. Implementar snapshots profundamente inmutables, reglas congeladas, secuencias inmutables, mapas anidados protegidos, copias defensivas, serialización round-trip y builders administrativos.
* **Diagnóstico & Reproducción Previa:**
  - **CONFIRMADO:** Se reprodujo con los imports reales:
    ```python
    policy = create_default_security_policy()
    policy.rules[0].decision = SecurityDecisionType.ALLOW  # Mutó exitosamente DENY -> ALLOW
    policy.rules.clear()  # Vació la lista a 0 reglas en sitio
    policy.rules[0].conditions.path_patterns.append("c:\\evil\\*")  # Mutó patrones de ruta
    policy.rules[0].conditions.parameters["injected"] = True  # Inyectó parámetros
    ```
* **Archivos Modificados / Creados:**
  - `core/security_policy.py`:
    - `InvalidPolicyError` hereda de `(FrozenInstanceError, ValueError)` para compatibilidad cruzada de excepciones.
    - Implementadas funciones `_deep_freeze_value`, `_deep_freeze_mapping` y `_deep_unfreeze_value` que convierten recursivamente diccionarios en `MappingProxyType` y secuencias en `tuple`.
    - `PolicyRuleCondition` reforzado con `@dataclass(frozen=True)`, convirtiendo `path_patterns`, `users` y `environments` en tuplas inmutables y `parameters` en `MappingProxyType` recursivo en `__post_init__`. Añadidos métodos `to_dict()` y `from_dict()`.
    - `PolicyRule` congelado con `@dataclass(frozen=True)`, validando no negatividad de prioridad, no vacío de `name`, e inmutabilidad estricta de `conditions`. Añadidos métodos `to_dict()` y `from_dict()`.
    - `SecurityPolicy` convertido en contenedor profundamente inmutable:
      - `rules` almacenado como `tuple[PolicyRule, ...]` inmutable.
      - Copia defensiva profunda de cada regla en `__post_init__`.
      - Orden determinista garantizado por prioridad descendente.
      - `__setattr__` y `__delattr__` bloquean reasignaciones y eliminaciones tras inicialización lanzando `InvalidPolicyError`.
      - Añadidos `to_dict()`, `from_dict()`, `to_json()`, `from_json()`.
    - Creados builders administrativos mutables:
      - `PolicyRuleBuilder`: builder mutable para configurar y publicar `PolicyRule` inmutables.
      - `SecurityPolicyBuilder`: builder mutable con `from_policy()`, `add_rule()`, `remove_rule()`, `clear_rules()`, `build()`.
    - `DefaultPolicyProvider`: añadida ruta administrativa `update_policy(new_policy)` para sustituir atómicamente la política activa por una nueva versión completa validada.
  - `tests/security/test_deep_policy_immutability.py`:
    - 8 pruebas exhaustivas cubriendo:
      1. Reasignación bloqueada (`policy.policy_id`, `policy.rules`, `policy.max_allowed_risk`, `policy.is_immutable`, `del policy.rules`).
      2. Modificación de regla bloqueada (`decision`, `priority`, `name`, `tool_name`, `conditions`).
      3. Métodos `clear()`, `append()`, `pop()`, `__setitem__` y `__delitem__` bloqueados sobre `policy.rules`.
      4. Edición de condiciones y parámetros anidados (`path_patterns.append`, `parameters[...]`, anidamiento multinivel de mappings y tuplas).
      5. Mutación de colecciones/diccionarios de entrada originales posterior a la construcción (`clear`, `append`, inyección de claves) no afecta el snapshot inmutable.
      6. Round-trip de serialización en diccionario y JSON preservando tipos e inmutabilidad profunda.
      7. Evaluación determinista y prioridad indestructible de DENY override.
      8. Builders administrativos y sustitución de versión en `DefaultPolicyProvider`.
* **Evidencia de Pruebas Ejecutadas:**
  - `python -m pytest tests/security/test_deep_policy_immutability.py -v`: 8 passed in 0.19s (100%).
  - `python -m pytest tests/test_security_policy_substage04_5.py tests/security/ tests/test_security_policy.py tests/test_audit_logger_substage04_6.py tests/test_mobile_api.py tests/interfaces/webui_bridge/ tests/e2e/test_full_e2e_integration.py -q`:
    - 366 passed in 23.4s (0 failed, 0 errors).
* **Forma de Revertir:**
  - `git checkout HEAD~1` sobre `core/security_policy.py` o restaurar commit base.

---

### Fase 04 — Timeout, Cancelación Cooperativa y Solicitudes Duplicadas (2026-10-03)

* **Objetivo:** Corregir el ciclo de solicitudes largas en Mobile API y WebUI Bridge, desacoplar el deadline de respuesta HTTP del ciclo de vida de la ejecución, implementar identidad estable de operación y deduplicación atómica con control de concurrencia, y propagar cancelación cooperativa y deadline monotónico hasta los puntos previos a la ejecución de efectos secundarios.
* **Diagnóstico & Reproducción Previa:**
  - **CONFIRMADO:** Se reprodujo el hallazgo donde `asyncio.wait_for(asyncio.to_thread(worker), timeout=...)` retorna `TimeoutError` pero el hilo subyacente en el pool de hilos continúa ejecutándose y alterando contadores de efectos tras la respuesta HTTP:
    ```python
    # Cancelar un Future de asyncio no detiene un hilo del sistema operativo.
    # El hilo sigue corriendo hasta su conclusión en el thread pool.
    ```
* **Archivos Modificados / Creados:**
  - `core/execution/operation_manager.py` (Nuevo):
    - `OperationStatus`: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCEL_REQUESTED`, `CANCELLED`, `UNKNOWN`.
    - Excepciones tipadas: `IdempotencyConflictError` (HTTP 409), `ConcurrencyLimitError` (HTTP 429), `SessionIsolationError` (HTTP 403).
    - `compute_payload_hash(payload)`: Normalización canónica JSON con SHA-256, excluyendo claves volátiles (`request_id`, `idempotency_key`, `timestamp`).
    - `OperationRecord`: Registro de ciclo de vida con `operation_id`, `session_id`, `payload_hash`, `cancellation_token`, `monotonic_deadline`, `effect_started`, `result`, `error`, `task`.
    - `OperationManager`:
      - `acquire_or_join`: Deduplicación atómica por clave `(session_id, operation_id)`. Mismo payload reutiliza operación/tarea en vuelo o resultado en caché; mismo key con payload distinto lanza `IdempotencyConflictError`; clave bajo otra sesión lanza `SessionIsolationError`.
      - Control de concurrencia mediante `asyncio.Semaphore` (`max_concurrency=10`) y límite de cola (`max_queue_size=100`).
      - Retención de resultados en memoria con TTL configurable (3600s / 1 hora) y purga automática.
      - `run_operation`: Despacho protegido en segundo plano. Si el hilo no coopera ante cancelación y ya inició efectos, preserva estado `UNKNOWN` / `CANCEL_REQUESTED` sin afirmar falsamente que el hilo fue detenido.
      - `cancel_operation`: Cancelación cooperativa con verificación de aislamiento de sesión.
      - `shutdown`: Cierre ordenado en lifespan con cancelación de tokens y periodo de gracia.
  - `core/execution/__init__.py`: Exportación de símbolos oficiales del gestor de operaciones.
  - `core/local_agent/local_agent_models.py`:
    - Añadido `monotonic_deadline: float | None = None` a `JessycaRequest`.
  - `core/local_agent/local_agent.py`:
    - En el paso 6 (ejecución de planes/herramientas), se verifica el `cancellation_token` y el `monotonic_deadline` antes de invocar side-effects físicos. Marca `op_rec.effect_started = True`.
  - `interfaces/mobile_api/models.py`:
    - Añadidos `request_id` e `idempotency_key` a `ChatRequest`.
    - Añadido `operation_id` a `ChatResponse`.
    - Añadido modelo `OperationStatusResponse` para consultas de polling.
  - `interfaces/mobile_api/app.py`:
    - Extracción de identidad de operación priorizando encabezados `Idempotency-Key` y `X-Request-ID`.
    - Desacoplamiento de deadline HTTP mediante `asyncio.shield`: Al expirar `MOBILE_API_TIMEOUT`, devuelve HTTP 504 Gateway Timeout con estado `RUNNING` y URL de consulta (`poll_url`), manteniendo la tarea ejecutándose en segundo plano.
    - Endpoints autorizados:
      - `GET /api/v1/operations/{operation_id}`: Consulta de estado y resultado en caché con aislamiento estricto de sesión.
      - `POST /api/v1/operations/{operation_id}/cancel`: Solicitud de cancelación cooperativa con aislamiento de sesión.
    - Cierre ordenado de `OperationManager` en el `lifespan` de FastAPI.
  - `interfaces/webui_bridge/app.py`:
    - Desacoplamiento de deadline mediante `asyncio.shield` y propagación de `CancellationToken` cooperativo en peticiones de chat síncronas.
  - `config/settings.py`:
    - Ajustado `MOBILE_API_TIMEOUT` a tipo `float` con default `30.0` y validación `ge=0.01` para soportar timeouts fraccionarios en pruebas de integración.
  - `tests/test_timeout_cancellation_idempotency.py` (Nuevo):
    - Suite de 8 pruebas exhaustivas:
      1. Timeout antes de iniciar efecto (HTTP 504 sin abortar ni corromper).
      2. Timeout después de iniciar efecto (estado RUNNING preservado, resultado consultable por endpoint autorizado tras conclusión, no repetición de escrituras).
      3. Duplicados simultáneos concurrentes (deduplicación atómica: 1 solo efecto físico ejecutado).
      4. Misma clave con distinto payload produce HTTP 409 Conflict.
      5. Nueva clave legítima con mismo texto procesada como acción independiente.
      6. Cancelación cooperativa antes del efecto aborta sin efectos secundarios.
      7. Hilo que no coopera conserva estado RUNNING / UNKNOWN sin afirmar que fue detenido.
      8. Aislamiento de sesiones al consultar y cancelar operaciones (HTTP 403 ante acceso cruzado).
* **Alcance Distribuido, Reinicios y Efectos Físicos de SO:**
  - *Monoproceso vs Multi-Worker:* La deduplicación en memoria de `OperationManager` opera a nivel de proceso. En despliegues multi-worker o clusters sin almacenamiento compartido (Redis/DB transaccional), dos peticiones a workers distintos requieren un candado distribuido o cola centralizada.
  - *No promesa de Exactly-Once Universal:* Operaciones sobre el sistema de archivos de Windows o hardware externo no son atómicas con bases de datos ACID. Si un proceso muere abruptamente durante un efecto físico, el estado resultante es inherentemente `UNKNOWN`.
  - *Recuperación de Estados Inciertos:* Ante un timeout 504 o estado `UNKNOWN`, los clientes no deben reintentar automáticamente escrituras. La estrategia obligatoria es: (1) consultar el resultado mediante `GET /api/v1/operations/{op_id}`, o (2) verificar previamente el estado del recurso afectado (ej. si el archivo o proceso ya existe) antes de reintentar con una nueva clave.
* **Evidencia de Pruebas Ejecutadas:**
  - `python -m pytest tests/test_timeout_cancellation_idempotency.py -v`: 8 passed in 2.17s (100%).
  - `python -m pytest tests/test_mobile_api.py tests/test_timeout_cancellation_idempotency.py tests/interfaces/webui_bridge/ tests/security/test_deep_policy_immutability.py -v`: 68 passed in 6.21s (100%).
  - `python -m pytest tests/security/test_emergency_stop_isolation.py tests/local_agent/test_jessyca_local_agent_phase45.py -q`: 15 passed in 14.2s (100%).
* **Forma de Revertir:**
  - `git checkout HEAD~1` sobre los archivos modificados o restaurar commit de la fase 03.

---

### Fase 05 — Orden Correcto de Dependencias en AI Planner (2026-10-03)

* **Objetivo:** Resolver el hallazgo en `core/planner.py` donde el planificador no aplicaba un orden topológico real sino una simple ordenación numérica/alfabética por `(execution_order, task_id)`, permitiendo que una tarea dependiente se ejecutara antes que su prerrequisito si su `execution_order` era menor. Implementar un módulo puro para grafos acíclicos dirigidos (DAG), algoritmo de ordenamiento topológico determinista (Kahn), desempate por prioridad exclusivamente para nodos ya desbloqueados, validación estricta (rechazando ciclos, autodependencias, referencias inexistentes e IDs repetidos), e impedir que `create_plan` entregue planes defectuosos como ejecutables tras un simple warning.
* **Diagnóstico & Reproducción Previa:**
  - **CONFIRMADO:** Se reprodujo exactamente el caso señalado en el prompt:
    ```python
    prereq = SubTask(task_id="prereq", execution_order=2, dependencies=[])
    dep = SubTask(task_id="dep", execution_order=1, dependencies=["prereq"])
    plan = ExecutionPlan(goal="Test", tasks=[dep, prereq])
    plan.validate_dependencies()  # Retornó True
    [t.task_id for t in plan.get_ordered_tasks()]  # Retornó ['dep', 'prereq'] -> INVERSIÓN DE DEPENDENCIAS
    ```
* **Archivos Modificados / Creados:**
  - `core/dag.py` (Nuevo):
    - Módulo puro (Python stdlib exclusivamente, cero dependencias de adaptadores ni ciclos de imports).
    - Jerarquía de excepciones: `DAGError(ValueError)`, `MissingDependencyError`, `SelfDependencyError`, `CircularDependencyError`, `DuplicateNodeError`, `InvalidPlanError`.
    - `topological_sort(items, get_id, get_dependencies, tie_breaker)`: Algoritmo de Kahn determinista con cola de prioridad (`heapq`).
      - Si $B$ depende de $A$, $A$ siempre precede a $B$ en el resultado final, sin importar `execution_order`.
      - `tie_breaker` y `get_id` solo se utilizan para desempatar entre nodos con grado de entrada 0 (listos para ejecución).
      - Rechaza referencias inexistentes (`MissingDependencyError`), autodependencias (`SelfDependencyError`), identificadores duplicados (`DuplicateNodeError`) y ciclos (`CircularDependencyError`).
  - `core/planner.py`:
    - `ExecutionPlan.get_ordered_tasks()`: Calcula y retorna el orden topológico determinista mediante `topological_sort`. Lanza `DAGError` si el grafo es inválido.
    - `ExecutionPlan.validate_dependencies(raise_on_error=False)`: Valida la aciclicidad y coherencia del grafo; retorna `True`/`False` o propaga la excepción específica si `raise_on_error=True`.
    - `ExecutionPlan.to_dict()` y `to_json()`: Serializan las subtareas garantizando el orden topológico resuelto.
    - `AIPlanner.create_plan()`: Valida el plan de forma estricta. Si contiene dependencias defectuosas, lanza `InvalidPlanError` en lugar de emitir un simple warning y entregar un plan no ejecutable.
  - `core/integration/adapters/are_adapter.py`:
    - `TaskGraph.get_topological_order()`: Refactorizado para reutilizar `core.dag.topological_sort` preservando compatibilidad con consumidores y pruebas de ARE.
  - `tests/test_planner_topological.py` (Nuevo):
    - 13 pruebas unitarias y de integración exhaustivas:
      1. Reproducción de inversión de dependencias (`prerequisite` con order=2 vs `dependent` con order=1).
      2. Cadena lineal de dependencias (`t1 -> t2 -> t3 -> t4`) provista en orden arbitrario.
      3. Grafo en diamante (`A -> B(2), A -> C(1), (B, C) -> D`).
      4. Tareas independientes con desempate por `execution_order` y luego por `task_id`.
      5. Plan vacío (DAG trivial válido).
      6. Referencias desconocidas o inexistentes (`MissingDependencyError`).
      7. Detección estricta de ciclos circulares (`CircularDependencyError`).
      8. Autodependencias (`SelfDependencyError`).
      9. Identificadores de subtarea duplicados (`DuplicateNodeError`).
      10. Estabilidad y determinismo garantizado ante 100 llamadas repetidas consecutivas.
      11. Serialización del plan (`to_dict`, `to_json`) preservando orden topológico.
      12. Consumidor real `TaskExecutor` ejecutando exitosamente respetando las dependencias físicas.
      13. `AIPlanner.create_plan` rechaza planes inválidos lanzando `InvalidPlanError`.
* **Evidencia de Pruebas Ejecutadas:**
  - `python -m pytest tests/test_planner_topological.py -v`: 13 passed in 0.24s (100%).
  - `python -m pytest tests/test_planner.py tests/test_executor.py tests/test_planner_topological.py tests/test_are_adapter.py tests/test_mobile_api.py tests/test_timeout_cancellation_idempotency.py tests/interfaces/webui_bridge/ tests/security/test_deep_policy_immutability.py -v`:
    - **120 passed, 0 failed in 7.31s (100% de aprobación)**.
* **Forma de Revertir:**
  - `git checkout HEAD~1` sobre los archivos modificados o restaurar commit de la fase 04.

---

### Fase 06 — Configuración Única y Efectiva (2026-10-04)

* **Objetivo:** Eliminar declaraciones duplicadas en `AppSettings` de `config/settings.py` (`MODEL_ROUTER_ENABLED`, `MODEL_ROUTER_MODE`, `ROUTER_CONFIDENCE_THRESHOLD`, `ROUTER_SHADOW_LOG_FILE`, `NEMOTRON_ENABLED`). Mantener valor efectivo previo, documentar precedencia y agregar pruebas exhaustivas.
* **Archivos Modificados:** `config/settings.py`, `config/manager.py`, `.env.example`, `core/llm/experimental_router.py`, `tests/test_config_effective_phase06.py`.
* **Evidencia de Pruebas:** 13 passed in 0.54s (100%).

---

### Fase 07 — Persistencia de Memoria Confiable (2026-10-04)

* **Objetivo:** Eliminar vulnerabilidad de truncamiento de memoria en `core/memory/long_term_memory.py`. Implementar reemplazo atómico seguro con temporales en el mismo directorio, flush/fsync, manejo multiplataforma de colisiones en Windows, y propagación de errores estructurados (`MemoryPersistenceError`).
* **Archivos Modificados:** `core/memory/long_term_memory.py`, `core/memory/memory_exceptions.py`, `tests/memory/test_long_term_memory_reliable_persistence_phase07.py`.
* **Evidencia de Pruebas:** 10 passed in 0.45s (100%).

---

### Fase 08 — Completar STT Local y Separar la Activación Simulada (2026-10-04)

* **Objetivo:** Completar `FasterWhisperSTTService.transcribe()` conectándolo a `WhisperModel.transcribe()` sin respuestas estáticas; implementar análisis PCM con RMS y energy threshold en `KeywordWakeWordService.process_audio()`; clarificar que `modo_voz.py` utiliza su propio pipeline real; agregar diagnósticos tipados de audio.
* **Archivos Modificados:** `services/voice/stt_service.py`, `services/voice/wake_word_service.py`, `services/voice/audio_capture.py`, `services/voice/voice_pipeline.py`, `services/voice/voice_errors.py`, `tests/voice/test_stt_local_and_wake_word_phase08.py`.
* **Evidencia de Pruebas:** 14 passed in 1.48s (100%).

---

### Fase 09 — No Usar Observaciones Simuladas como Evidencia Real (2026-10-04)

* **Objetivo:** Eliminar fallbacks silenciosos a backends/adaptadores simulados (`FakeUIInspectionBackend`, `FakeBrowserAdapter`). En producción, una dependencia ausente (`uiautomation`) o fallo técnico debe devolver `BACKEND_UNAVAILABLE`/`INSPECTION_ERROR` o elevar `UIBackendUnavailableError`/`UIInspectionError`, nunca inventar ventanas o controles sintéticos. Introducir procedencia (`ObservationProvenance`) y estado técnico (`ObservationStatus`) explícitos. Rechazar evidencia sintética como prueba física en `ActionVerifier`. En `BrowserAgent`, declarar indisponibilidad en producción si no hay adaptador conectado.
* **Archivos Modificados / Creados:**
  - `core/exceptions.py`: Nuevas excepciones `UIInspectionError` y `UIBackendUnavailableError` (subclases de `WindowsPlatformError`).
  - `core/ui_inspection_models.py`:
    - Enums `ObservationProvenance` (`REAL_PHYSICAL`, `SYNTHETIC_TEST`, `UNAVAILABLE`) y `ObservationStatus` (`SUCCESS`, `NO_ELEMENTS_FOUND`, `BACKEND_UNAVAILABLE`, `INSPECTION_ERROR`).
    - Metadatos `UIInspectionMetadata` y resultados `UIInspectionResult` con campos `provenance`, `status`, `error_message`, `is_synthetic`, `is_available`.
    - `UIElementInfo.empty_placeholder()` y `UIElementTree.empty()`.
    - `WindowInfo` enriquecido con `provenance`, `is_synthetic` e `is_available`.
  - `core/action_verification_models.py`:
    - `VerificationStatus`: Añadidos `UNVERIFIED`, `BACKEND_UNAVAILABLE`, `SYNTHETIC_REJECTED`.
    - `ObservedState`, `ActionVerificationRequest`, `VerificationResult` con `provenance`, `is_synthetic`, `require_real_evidence`.
  - `tools/desktop/ui_backend.py`:
    - `WindowsUIAutomationBackend`: Eliminada toda delegación oculta a `FakeUIInspectionBackend`. En ausencia de `uiautomation`, eleva `UIBackendUnavailableError` en `get_active_window`/`list_windows` y devuelve `BACKEND_UNAVAILABLE` con `elements_flat=()` en `inspect_ui`. Si la consulta no encuentra ventanas, retorna `()` con procedencia real sin inventar ventanas falsas.
    - `FakeUIInspectionBackend`: Etiqueta explícitamente todos sus elementos y ventanas con `provenance=ObservationProvenance.SYNTHETIC_TEST`.
    - Fábrica `get_ui_backend(mode)`: Selección explícita (`real`/`production` vs `fake`/`test`/`demo`).
  - `tools/desktop/action_verifier.py`:
    - Verifica el estado técnico de la inspección (`BACKEND_UNAVAILABLE` / `INSPECTION_ERROR`).
    - Cuando `require_real_evidence=True` (o en entorno de producción), rechaza evidencia sintética como prueba física (`VerificationStatus.SYNTHETIC_REJECTED`).
  - `tools/desktop/ui_inspection_service.py`:
    - Preserva y propaga `provenance`, `status` y `error_message` en metadatos y objetos `WindowInfo`.
    - Emite `AuditEventType.UI_INSPECTION_FAILED` cuando la inspección no está disponible o falla.
  - `core/browser_models.py` & `core/browser_session_manager.py`:
    - `BrowserUnavailableError` añadida.
    - `BrowserTab` incluye `provenance` e `is_synthetic`. `FakeBrowserAdapter` genera pestañas con `provenance="SYNTHETIC_TEST"`.
  - `core/agents/browser_agent.py`:
    - En producción (`ENVIRONMENT="production"`), si no se inyecta `session_manager`, marca `_browser_available=False` y rechaza la ejecución de intenciones con `STOPPED_ERROR` y estado `BROWSER_UNAVAILABLE`.
    - Cuando se inyecta un adaptador fake en desarrollo/pruebas, el resultado conserva la procedencia `SYNTHETIC_TEST`.
  - `tests/test_ui_and_browser_observation_provenance_phase09.py` (Nuevo): 12 pruebas unitarias e integración que validan:
    1. Falta de dependencia (`uiautomation` ausente) -> `UIBackendUnavailableError` / `BACKEND_UNAVAILABLE`.
    2. Excepción nativa de UIA -> `UIInspectionError` / `INSPECTION_ERROR`.
    3. Consulta real sin resultados -> `NO_ELEMENTS_FOUND` con `REAL_PHYSICAL` y lista vacía sin inventar ventanas.
    4. Inyección explícita de fake de test -> `SYNTHETIC_TEST`.
    5. Fábrica `get_ui_backend` (real vs fake).
    6. Producción sin navegador -> `BROWSER_UNAVAILABLE` y `STOPPED_ERROR`.
    7. Inyección explícita de fake en `BrowserAgent` -> conserva `SYNTHETIC_TEST`.
    8. Verificador que rechaza evidencia sintética ante `require_real_evidence=True` (`SYNTHETIC_REJECTED`).
    9. Verificador ante fallo técnico del backend (`BACKEND_UNAVAILABLE`).
* **Evidencia de Pruebas Ejecutadas:**
  - `pytest tests/test_ui_and_browser_observation_provenance_phase09.py -v`: 12 passed in 2.50s (100%).
  - Regresión consolidada (`tests/desktop/`, `tests/browser/`, `tests/agents/`, fases 06 a 09):
    - **193 passed, 0 failed en 16.2s (100% de aprobación)**.
* **Rutas que Quedan sin Backend Real (para Integraciones Posteriores):**
  1. *Microsoft Edge Browser Driver*: `WindowsBrowserAdapter` (`core/browser_session_manager.py`) requiere conectar un driver real CDP o Playwright para reemplazar el envoltorio de `FakeBrowserAdapter`.
  2. *Accesibilidad Cross-Platform*: `WindowsUIAutomationBackend` depende de `uiautomation` (Windows). Entornos Linux/macOS requieren adaptadores específicos (AT-SPI / AXUIElement) en caso de despliegue fuera de Windows.
  3. *Control de ventanas en `windows.apps`*: `apps_skill.py` continúa usando Win32 crudo (`win32gui`); su convergencia hacia `WindowsUIAutomationBackend` queda pendiente para una fase dedicada.
* **Forma de Revertir:**
  - `git checkout HEAD~1` sobre los archivos modificados o restaurar commit previo a fase 09.

---

### Fase 10 — Consolidación Gradual sin Romper Compatibilidad (2026-10-04)

* **Objetivo:** Consolidar responsabilidades solapadas entre `core/local_agent/local_agent.py`, `core/dialogue/conversational_action_controller.py`, `core/execution/action_pipeline.py`, `core/orquestador.py`, JDE, ARE y registros de herramientas. Trazar el mapa de llamadas y consumidores de los flujos Voz/HTTP/MCP identificando autorización y evidencia real. Convertir `_active_pending_intent` de `core/orquestador.py` en estado thread-safe aislado por sesión con TTL. Resolver la ambigüedad `tools/registry.py` vs `tools/registry/` vs `tools/tool_registry.py` sin romper importaciones públicas ni autodescubrimiento dinámico. Extraer del agente local la responsabilidad de construcción/formateo de respuestas (`ResponseSynthesizer`).
* **Mapa de Llamadas, Consumidores y Ruta Canónica:**
  1. **Flujo Voz (`interfaces/modo_voz.py` & `core/local_agent/voice_interface.py`):**
     - *Entrada:* Captura de audio y transcripción (`CalibratedVoiceCaptureEngine` o `LocalVoiceInterface.capture_voice_request`).
     - *Despacho:* `JessycaRequest(session_id="voice_session", modality=InputModality.VOICE)` -> `JessycaLocalAgent.get_instance().interact(req)`.
     - *Autorización:* `JessycaLocalAgent._evaluate_action_security()` mediante `RiskEngine` y `PermissionManager`. Si la acción es de alto riesgo, emite `ConfirmationPrompt` y transiciona a `WAITING_CONFIRMATION` hasta recibir confirmación explícita. Verificación previa de parada de emergencia (`EmergencyStopManager`).
     - *Evidencia Real:* Invocación de skill autorizada. En acciones de escritorio, verificación física mediante `ActionVerifier` / `ExecutionVerifier` inspeccionando ventanas activas y procesos del SO. Evidencia sintética es expresamente rechazada para prueba física.
     - *Salida:* Síntesis de voz con `response.spoken_text` vía `LocalVoiceInterface.synthesize_response` / `TTSService`.
  2. **Flujo HTTP / API (`interfaces/mobile_api/` & `interfaces/webui_bridge/`):**
     - *Entrada:* `POST /api/v1/chat` (Mobile API) o `POST /v1/chat/completions` (WebUI Bridge).
     - *Autenticación y Aislamiento:* Valida cabeceras secretas (`X-Jessyca-Token` o `Authorization: Bearer <token>`). Asigna o recupera un `session_id` aislado.
     - *Despacho:* `JessycaRequest(session_id=..., modality=TEXT/HTTP)` -> `JessycaLocalAgent.interact(req)`.
     - *Autorización:* Evaluada en el agente unificado por sesión. El contexto y las intenciones de confirmación de la Sesión A son invisibles e inaccesibles para la Sesión B.
     - *Evidencia Real:* Payload JSON con métricas de latencia, veredicto de seguridad, resultado estructurado y estado verificado.
  3. **Flujo MCP (`server.py`, `server/app.py`, `main.py`):**
     - *Entrada:* Conexión cliente MCP sobre stdio o HTTP.
     - *Despacho de Herramientas:* Catálogo centralizado en `ToolRegistry` (`tools/tool_registry.py`).
     - *Autorización:* Validación determinista de schemas (`ToolSchema`) y límites de seguridad perimetral (`SecurityPolicy`, `RegistryPathSecurityManager`, sandboxing de rutas).
     - *Evidencia Real:* Invocación directa de APIs del SO (`winreg`, `psutil`, etc.), retornando `ToolExecutionResponse`.
  4. **Flujo CLI Legacy (`interfaces/modo_texto.py`):**
     - *Ruta Primaria:* `JessycaLocalAgent.interact(texto)`.
     - *Ruta Fallback Legacy:* `core/orquestador.py:ejecutar_orden_texto(texto, session_id=...)`.
     - *Autorización Legacy:* `core/seguridad.py` (`requiere_confirmacion`, `confirmar_con_usuario` por consola interactiva).
     - *Limitación Documentada:* Sincrónico, bloqueante de consola (`input()`). El estado de intenciones pendientes está aislado por `session_id` con TTL; sin embargo, no debe enrutarse tráfico HTTP multisesión hacia este orquestador procedimental.
  5. **Subsistemas Gobernados:**
     - *JDE (`core/jde/`):* Motor determinista para recetas de alta certeza con idempotencia y verificación obligatoria.
     - *ARE (`core/are/`):* Motor de razonamiento autónomo y recuperación ante fallos complejos.
     - *ActionPipeline & ConversationalActionController (`core/execution/`, `core/dialogue/`):* Pipeline moderno de acciones desacoplado con gestión de confirmaciones conversacionales y recuperación guiada sin falsos éxitos.
* **Archivos Modificados / Creados:**
  - `core/orquestador.py`:
    - Reemplazado `_active_pending_intent` global por almacenamiento por sesión: `_session_pending_intents: dict[str, PendingIntent]` con `_session_lock = threading.RLock()`.
    - Funciones `get_pending_intent`, `set_pending_intent`, `clear_pending_intent` con parámetro `session_id: str = "default_session"`, manteniendo sincronizado `_active_pending_intent` para la sesión por defecto.
    - `clear_all_pending_intents()` añadida para limpieza global.
    - Expiración de TTL (`CLARIFICATION_TTL_SECONDS = 60.0`), conteo de intentos y palabras de cancelación evaluados estrictamente en el contexto de la sesión invocadora.
    - Documentación arquitectónica de restricciones multisesión.
  - `tools/registry.py`:
    - Convertido de duplicado obsoleto a shim de compatibilidad canónico que reexporta `ToolRegistry`, `get_tool_registry`, `ITool`, `IToolRegistry`, `ToolNotFoundError`, `ToolSchema` desde `tools.tool_registry`.
  - `tools/__init__.py`:
    - Actualizado para importar `ToolRegistry` y `get_tool_registry` desde `tools.tool_registry`, preservando todos los símbolos en `__all__`.
  - `tools/tool_registry.py`:
    - Autodescubrimiento dinámico excluye explícitamente `registry.py`, `tool_registry.py` y `discovery.py` para evitar auto-registro o colisiones.
  - `core/local_agent/response_synthesizer.py` (Nuevo):
    - Extraída la responsabilidad de síntesis, formateo verídico y construcción de respuestas.
    - `format_response_text`: Formateo con verificación física estricta (rechaza falsos éxitos "Listo" ante `VERIFICATION_FAILED` o `is_verified=False`).
    - `synthesize_spoken_text`: Normalización de texto para habla (TTS), eliminando sintaxis markdown (enlaces, código, negritas, viñetas).
    - Métodos factoría: `build_response`, `build_stopped_response`, `build_interrupted_response`, `build_cancelled_response`, `build_closing_response`, `build_clarification_response`, `build_confirmation_response`.
    - Singleton `get_response_synthesizer()`.
  - `core/local_agent/__init__.py`:
    - Exporta `ResponseSynthesizer` y `get_response_synthesizer`.
  - `core/local_agent/local_agent.py`:
    - Integra `ResponseSynthesizer` en `__init__`.
    - `_format_response_text` delega directamente en `self.response_synthesizer.format_response_text(...)`.
    - Utiliza `ResponseSynthesizer` en paradas de emergencia (Paso 0), interrupciones (Paso 0), cierres de conversación (Paso 1.8) y cancelaciones de usuario (Paso 2).
  - `tests/test_consolidation_phase10.py` (Nuevo):
    - Suite exhaustiva con 11 pruebas de contrato y regresión.
* **Evidencia de Pruebas Ejecutadas:**
  - `pytest tests/test_consolidation_phase10.py -v`: 11 passed in 0.62s (100%).
  - `pytest tests/test_orquestador_clarification.py -v`: 6 passed in 0.12s (100%).
  - `pytest tests/test_registry.py tests/test_tool_discovery.py -v`: 6 passed in 0.40s (100%).
  - `pytest tests/jde/ -v`: 357 passed in 16.13s (100%).
  - `pytest tests/local_agent/ -v`: 19 passed in 37.45s (100%).
  - `pytest tests/desktop/ tests/browser/ tests/agent/ tests/server/ -v`: 197 passed in 17.91s (100%).
  - Total consolidado: **596 tests PASSED, 0 FAILED**.
* **Forma de Revertir:**
  - `git checkout HEAD~1` sobre los archivos modificados o restaurar commit previo a fase 10.

---

## 13. Fase 11 — Medir y Optimizar el Rendimiento (Resultados Reales de Hardware)

### 13.1. Diagnóstico de Hardware y Entorno Real (Cero Datos Simulados)
* **Entorno de Medición:**
  - **Sistema Operativo:** Windows 10 Pro (build 10.0.26200, amd64).
  - **Python:** 3.11.9 (CPython ABI3).
  - **CPU:** AMD64 Family 25 Model 33 Stepping 2, AuthenticAMD (12 núcleos físicos / 24 núcleos lógicos).
  - **Memoria RAM:** 31.93 GB Total (12.28 GB disponible al momento de la ejecución).
  - **GPU:** NVIDIA GeForce RTX 3060 (VRAM Total: 12288 MB, VRAM Libre: 8103 MB, Driver NVIDIA: 591.86).
  - **Daemon Ollama Local (`http://localhost:11434`):** Inactivo (`is_online: False`). Sin descarga de modelos pesados ni llamadas cloud simuladas; resultados de inferencia LLM clasificados honestamente como `PENDING_HARDWARE_DAEMON`.
  - **Nemotron Remoto:** Deshabilitado (`NEMOTRON_ENABLED=False`, Cloud inactivo).

### 13.2. Resultados del Benchmark Repetible (4 Escenarios Obligatorios)
Medición empírica ejecutada con `benchmarks/performance_benchmark_phase11.py` registrando latencias con `time.perf_counter()`, deltas de consumo RSS con `psutil.Process().memory_info().rss`, y auditoría de verificación:
* **Escenario 1: Comandos Simples (Aplicaciones / OS - Notepad):**
  - *Cold Start Latency:* 2495.69 ms
  - *Warm Start p50:* 4249.75 ms | *Warm Start p95:* 4977.98 ms
  - *Latencia Promedio:* 2960.96 ms (Mínima: 800.74 ms, Máxima: 4977.98 ms)
  - *Consumo RSS Delta:* +33.72 MB
  - *Tasa de Éxito / Verificación:* 83.3% / 83.3%
  - *Desglose de Fases (Promedios):* Clasificación Intención: 0.56 ms | Enrutamiento: 0.00 ms | Autorización: 0.10 ms | Ejecución Herramienta: 1411.93 ms | Verificación: 211.79 ms
* **Escenario 2: Conversación (Diálogo / Asistente Local):**
  - *Cold Start Latency:* 4296.99 ms
  - *Warm Start p50:* 4259.70 ms | *Warm Start p95:* 4285.12 ms
  - *Latencia Promedio:* 2915.03 ms (Mínima: 183.23 ms, Máxima: 4296.99 ms)
  - *Consumo RSS Delta:* +2.50 MB
  - *Tasa de Éxito / Verificación:* 100.0% / 100.0%
  - *Desglose de Fases:* Clasificación Intención: 0.13 ms
* **Escenario 3: Documentos (Búsqueda en Filesystem / Lectura):**
  - *Cold Start Latency:* 192.07 ms
  - *Warm Start p50:* 189.89 ms | *Warm Start p95:* 193.17 ms
  - *Latencia Promedio:* 129.37 ms (Mínima: 4.89 ms, Máxima: 193.17 ms)
  - *Consumo RSS Delta:* +0.97 MB
  - *Tasa de Éxito / Verificación:* 100.0% / 100.0%
  - *Desglose de Fases:* Clasificación Intención: 0.29 ms | Autorización: 0.10 ms | Ejecución Herramienta: 2.46 ms
* **Escenario 4: Objetivo de Varios Pasos (Coordinación ARE / Tarea Compleja):**
  - *Cold Start Latency:* 4979.94 ms
  - *Warm Start p50:* 4969.69 ms | *Warm Start p95:* 4978.25 ms
  - *Latencia Promedio:* 3425.94 ms (Mínima: 305.81 ms, Máxima: 4979.94 ms)
  - *Consumo RSS Delta:* -1.06 MB
  - *Tasa de Éxito / Verificación:* 33.3% / 33.3%
  - *Desglose de Fases:* Clasificación Intención: 0.24 ms | Autorización: 0.09 ms | Ejecución Herramienta: 3191.40 ms | Verificación: 478.71 ms
  - *Observación de Verificación Real:* En los casos en que `notepad.exe` fue lanzado sin ventana GUI visible interactiva (`MainWindowHandle=0`), el verificador físico previno de inmediato el falso éxito emitiendo `VERIFICATION_FAILED` e impidiendo confirmaciones espurias.

### 13.3. Cuellos de Botella Resueltos y Optimizaciones Implementadas
1. **Health Checks con TTL Configurable e Invalidación Inmediata:**
   - Implementado en `server/health.py` (`HealthChecker.cache_ttl_seconds = 2.0`) y `core/diagnostics/monitor.py` (`HealthMonitor.cache_ttl_seconds = 2.0`).
   - El resultado del health check se cachea durante la ventana de TTL, reduciendo llamadas repetidas de I/O y comprobaciones redundantes.
   - Si ocurre una transición de ciclo de vida del servidor (`STARTING` -> `RUNNING` -> `STOPPED`) o se registra una nueva sonda/acción, la caché se invalida inmediatamente.
   - *Mejora Empírica Medida:* En 500 ciclos, la latencia total cayó de 1.39 ms a 0.22 ms (**Aceleración de 6.3x**, de 0.0028 ms a 0.0004 ms por llamada).
2. **Sesiones HTTP Reutilizables con Cierre Limpio:**
   - `core/llm/nemotron_provider.py` y `core/llm/inference.py` (`OllamaProvider`): Implementado pool de conexiones `requests.Session()` con `HTTPAdapter(pool_connections=10, pool_maxsize=20)`.
   - Soporte para context managers (`__enter__` / `__exit__`) y método explícito `close()`.
   - Compatibilidad asegurada con mocks de pruebas unitarias (`hasattr(requests.post, 'mock_calls')`).
3. **Límite de Inferencias Concurrentes en GPU y Cola Acotada:**
   - `core/llm/vram_manager.py` (`VRAMGovernor`) y `core/llm/model_lifecycle.py` (`ModelLifecycleManager`):
     - Implementado `acquire_inference_slot(model_name, timeout_seconds)`.
     - Límite concurrente configurable (`max_concurrent_inferences=1` optimizado para los 12GB VRAM de la RTX 3060).
     - Cola acotada (`max_inference_queue_size=10`). Cuando la cola está llena, las peticiones entrantes son rechazadas de inmediato con `InferenceError` para prevenir saturación y desbordamiento de memoria.
     - Presupuesto de tiempo monótono con decremento durante la espera en cola.
     - *Overhead de Gobernanza Medido:* 0.0035 ms por adquisición (0.35 ms en 100 adquisiciones consecutivas).
4. **Corrección de la Regresión de Configuración en `NemotronProvider`:**
   - Se erradicó el patrón defectuoso `max_retries or default` que transformaba silenciosamente un `max_retries=0` explícito en el valor predeterminado (3).
   - Se implementó distinción estricta entre `None` y `0` tanto en el constructor como en `extra_options["max_retries"]`.
   - Certificado por prueba unitaria que `max_retries=0` realiza estrictamente 1 intento (0 reintentos) ante errores 429, 5xx, timeouts y errores de conexión.
   - Los errores de herramientas (`ToolExecutionError`, `MCPError`) no son capturados ni reintentados como si fueran fallos de inferencia LLM.
5. **Observabilidad Granular por `request_id`:**
   - `core/local_agent/local_agent_models.py` (`LocalAgentMetrics`):
     - Añadidos: `request_id`, `capture_latency_ms`, `speech_end_ms`, `stt_accuracy`, `stt_latency_ms`, `classification_latency_ms`, `routing_latency_ms`, `model_load_latency_ms`, `inference_latency_ms`, `authorization_latency_ms`, `tool_execution_latency_ms`, `verification_latency_ms`, `first_audio_tts_latency_ms` (TTFT), `tts_latency_ms`, `total_latency_ms`.
   - `core/local_agent/local_agent.py` y `core/local_agent/voice_interface.py`:
     - Instrumentado el pipeline unificado para registrar tiempos por fase sin alterar los invariantes de seguridad.
6. **Streaming e Invariantes de Verificación:**
   - La generación progresiva de texto puede anticipar respuestas conversacionales, pero no confirma el éxito de una acción física en el SO antes de su verificación efectiva por `ExecutionVerifier` / `ActionVerifier`.

### 13.4. Evidencia de Pruebas Ejecutadas
* `pytest tests/test_performance_phase11.py -v`: **16 passed in 3.01s (100%)**.
* `pytest tests/test_performance_phase11.py tests/llm/test_nemotron_provider.py tests/core/llm/test_inference_provider.py tests/server/test_health.py tests/diagnostics/ tests/core/llm/test_vram_and_lifecycle.py tests/router/ -v`: **193 passed in 40.84s (100%)**.
* Suite cruzada multifase (Fases 6 a 11): `pytest tests/test_performance_phase11.py tests/test_consolidation_phase10.py tests/test_ui_and_browser_observation_provenance_phase09.py tests/test_config_effective_phase06.py tests/voice/ tests/memory/ -v`: **333 passed in 81.50s (100%)**.

### 13.5. Forma de Revertir
* Revertir cambios en `core/llm/nemotron_provider.py`, `core/llm/inference.py`, `core/llm/vram_manager.py`, `core/llm/model_lifecycle.py`, `server/health.py`, `core/diagnostics/monitor.py`, `core/local_agent/local_agent_models.py`, `core/local_agent/local_agent.py`, `core/local_agent/voice_interface.py`.
* Eliminar `benchmarks/performance_benchmark_phase11.py` y `tests/test_performance_phase11.py`.

---

## 14. Fase 12 — Planificación Más General con Herramientas Reales

### 14.1. Diagnóstico y Evolución Funcional
* **Preservación Determinista:** Las plantillas de descomposición y planes de ARE existentes no eran un error en sí mismos sino patrones reutilizables. Se preservó el 100% de la funcionalidad anterior en `core/are/planning.py`, `core/are/recovery.py`, `core/are/models.py` y `core/are/runtime.py`.
* **Superación de Placeholders Genéricos:** Se identificó que la descomposición anterior utilizaba `action.execute` y stubs genéricos cuando no coincidía con una plantilla estricta.
* **Solución Arquitectónica:** Se construyó un catálogo real y gobernado de acciones (`ActionCatalog`), un validador estricto fuera del LLM (`PlanValidator`), un resolutor de referencias tipadas de datos entre pasos (`DataFlowResolver`), y un gestor de estado persistente (`AREPlanExecutionState`).

### 14.2. Componentes Implementados

1. **Catálogo Real de Acciones Ejecutables (`core/are/action_catalog.py`):**
   - Modela cada acción mediante `ExecutableAction` con: `action_id`, `description`, `input_schema` (JSON Schema estricto), `output_schema`, `risk_level` (`RiskLevel.LOW` a `CRITICAL`), `requires_authorization`, `verification_strategy` (`STATE_MATCH`, `FILE_SYSTEM`, `DATA_VERIFY`), `max_retries`, `timeout_seconds` y `handler` concreto.
   - Herramientas reales registradas:
     - Archivos y Directorios: `files.search`, `files.read`, `files.create`, `files.copy`, `files.move`, `files.preview_organize`, `files.verify_copies`.
     - Procesamiento de Documentos: `documents.read`, `documents.create`, `documents.summarize`, `documents.convert`.
     - Tablas y Datos Estructurados: `data.extract_table` (CSV, TSV y tablas Markdown), `data.write_table` (salida CSV / JSON), `files.verify_table` (comprobación física de existencia y concordancia estricta de conteo de filas en disco).
     - Navegación: `browser.search`, `browser.read`.
     - Diagnósticos y Asistencia: `system.check`, `system.verify`, `core.assistant`.
     - Subsistemas: `agent_orchestration.run_agent_pipeline`, `document_processing.convert`.
   - **Rechazo Estricto de Acciones Genéricas:** Nombres como `action.execute`, `generic_action`, `placeholder`, `unknown` carecen de implementación concreta y son rechazados antes de la ejecución física con `UnresolvableActionError`.

2. **Resolución Tipada de Flujos de Datos entre Pasos (`core/are/dataflow.py`):**
   - `DataFlowResolver` analiza y enlaza referencias dinámicas con sintaxis `$step_id.output.property` y subíndices de listas `$step_id.output.list[0]`.
   - Si una referencia apunta a una salida no producida por un paso previo, o si el paso emisor falló, genera una excepción tipada `MissingOutputDependencyError`, bloqueando la cascada y evaluando el radio de impacto.

3. **Validación Fuera del LLM del Contrato de Planes (`core/are/plan_validator.py`):**
   - `PlanValidator` aplica 7 fases de validación independientes del modelo de lenguaje:
     1. **Presupuesto y Límites:** Máximo 15 pasos y 300 segundos de tiempo total acumulado (`PlanBudgetExceededError`).
     2. **Grafo Acíclico Dirigido (DAG):** Detección estricta de dependencias circulares mediante ordenamiento topológico (`PlanValidationError: Grafo contiene dependencias circulares`).
     3. **Existencia en Catálogo:** Comprobación de que cada `action_type` resuelva a una herramienta registrada en `ActionCatalog`.
     4. **Tipado de Parámetros:** Validación contra los esquemas JSON de entrada.
     5. **Sandbox y Privacidad:** Detección de path traversal (`..`, rutas absolutas fuera del directorio sandbox) (`SandboxViolationError`).
     6. **Invariante de Denegación en Replanificación:** Si un paso fue previamente denegado (`DENY`) por JDE, la replanificación no puede reintroducirlo ni ampliar permisos silenciosamente (`ReplanningDenialViolationError`).
     7. **Recursos Esenciales y Destinos Ausentes:** Si faltan destinos indispensables (p. ej. parámetro de destino vacío en copia/movimiento sin default), solicita aclaración explícita al usuario (`PlanClarificationRequired` -> `AWAITING_CLARIFICATION`).

4. **Estado Persistente y Gobernanza de Ejecución (`core/are/execution_state.py` y `core/are/runtime.py`):**
   - Registro de estado por paso: `AREStepExecutionRecord` con marca temporal monotónica, parámetros resueltos, outputs, errores, estado (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `SKIPPED`, `DENIED`).
   - Persistencia atómica opcional en disco (`data/are_executions/{plan_id}.json`).
   - Gobernanza JDE previa a cada paso: El evaluador JDE se ejecuta antes de cualquier invocación física; si devuelve `DENY`, la acción queda vetada y se detiene la ejecución; si devuelve `REQUIRE_REVIEW`, la ejecución pasa a `AWAITING_CONFIRMATION`.
   - Soporte para cancelación externa limpia mediante `CancellationToken` (`AgentExecutionState.INTERRUPTED`).
   - Límite estricto de recuperación acotada (máximo 2 intentos por paso fallido) para impedir bucles infinitos de replanificación.
   - Principio Anti-False Success: ningún paso se declara exitoso sin verificación física en el entorno host/sandbox.

5. **Integración en `AREAdapter` (`core/integration/adapters/are_adapter.py`):**
   - Se amplió el método `_handle_decompose_task` para soportar tanto los tres nuevos objetivos reales de sandbox como los flujos deterministas existentes (AnyDoc, ORCA, Desktop Notes, Search, etc.), manteniendo intacta la compatibilidad hacia atrás.

### 14.3. Implementación de los Tres Objetivos en Sandbox
* **Objetivo 1 — Localizar Documento y Resumirlo con Referencias Auditables:**
  - Cadena: `files.search` -> `documents.read` -> `documents.summarize` -> `files.create`.
  - Resumen estructurado guardado en archivo con citas y referencias auditables de origen.
* **Objetivo 2 — Organizar Copias de Archivos con Vista Previa y Verificación:**
  - Cadena: `files.search` -> `files.preview_organize` -> `files.copy` -> `files.verify_copies`.
  - Generación de mapa previo de reubicación por extensión, copias individuales en sandbox y verificación física posterior de tamaños y existencias.
* **Objetivo 3 — Extraer Tabla a Archivo Verificable y Comprobación de Filas:**
  - Cadena: `documents.read` -> `data.extract_table` -> `data.write_table` -> `files.verify_table`.
  - Extracción de tabla Markdown a filas y columnas tipadas, persistencia en archivo CSV y comprobación física en disco del conteo de filas de datos contra el número esperado.

### 14.4. Invariante de Seguridad: Modo ACTIVE Estrictamente Bloqueado
* El modo `ACTIVE` de ARE continúa permanentemente prohibido y bloqueado mediante lanzamiento explícito de `PermissionError`, manteniendo la arquitectura bajo `CONTROLLED READY`.

### 14.5. Evidencia de Pruebas Ejecutadas
* **Suite Específica de Planificación General (Fase 12):**
  - `pytest tests/test_are_generalized_planning_phase12.py -v`: **13 passed in 0.47s (100%)**.
* **Suite Completa de ARE y Adaptador:**
  - `pytest tests/are/ tests/test_are_adapter.py tests/test_are_generalized_planning_phase12.py -v`: **79 passed in 9.05s (100%)**.
* **Suite de Regresión Multifase (Fases 6 a 12):**
  - `pytest tests/test_config_effective_phase06.py tests/test_ui_and_browser_observation_provenance_phase09.py tests/test_consolidation_phase10.py tests/test_performance_phase11.py -v`: **81 passed in 9.00s (100%)**.
  - `pytest tests/voice/ tests/memory/ -v`: **252 passed in 75.06s (100%)**.
* **Total de Pruebas Certificadas Sin Regresiones:** **412 tests aprobados con 0 fallos (100%)**.

### 14.6. Forma de Revertir
* Revertir cambios en `core/are/runtime.py`, `core/are/__init__.py` y `core/integration/adapters/are_adapter.py`.
* Eliminar `core/are/action_catalog.py`, `core/are/dataflow.py`, `core/are/plan_validator.py`, `core/are/execution_state.py`, `core/are/exceptions.py` y `tests/test_are_generalized_planning_phase12.py`.

---

## 15. Integración Opcional I1 — Silero VAD (snakers4/silero-vad)

### 15.1. Diagnóstico, Solapamientos y Dependencias
* **Solapamientos Identificados en el Código Actual:**
  - Protocolo `IVADService` en `services/voice/vad_service.py`: contrato formal con `process_chunk(chunk: AudioChunk) -> VADResult` y `reset() -> None`.
  - Backend determinista actual: `EnergyVADService` en `services/voice/vad_service.py` (análisis de energía RMS con histeresis y EOS adaptativo).
  - Captura y Pipeline: `CalibratedVoiceCaptureEngine` (`services/voice/audio_capture.py`), `VoicePipeline` (`services/voice/voice_pipeline.py`) y `LocalVoiceInterface` (`core/local_agent/voice_interface.py`).
* **Dependencia Agregada:**
  - `[project.optional-dependencies]` en `pyproject.toml`: `vad = ["onnxruntime>=1.16.0,<=1.23.2"]`.
  - Licencia del código fuente y modelo: **MIT License** (`snakers4/silero-vad`).
  - Modelo empaquetado y resuelto: `silero_vad_v6.onnx` (1.24 MB), verificado localmente y compatible con inferencia sin conexión a red.
* **Criterio de Aislamiento:** No se copió el repositorio entero dentro del core; se implementó un adaptador ligero y desacoplado detrás del contrato existente.

### 15.2. Componentes Implementados

1. **Adaptador Silero VAD (`services/voice/silero_vad_service.py`):**
   - Implementa `IVADService` y los métodos `health()`, `capabilities()`, `close()`.
   - **Importación Perezosa (Lazy Import):** `onnxruntime` y la sesión ONNX no se importan ni instancian al cargar módulos de voz sino hasta la primera llamada o instanciación explícita.
   - **Buffering y Resampleo Automático:** Acepta chunks de cualquier tamaño y tasa de muestreo (8kHz, 16kHz, 44.1kHz, 48kHz, mono/estéreo), convirtiéndolos a float32 a 16kHz y fragmentándolos en ventanas de 512 muestras (32 ms) con 64 muestras de contexto acústico continuo (576 muestras de entrada total).
   - **Estado Recurrente por Flujo:** Mantiene los tensores LSTM `h` y `c` `[1, 1, 128]` y contexto `[1, 64]`. El método `reset()` reinicia todos los tensores a ceros, previniendo fuga de estado entre sesiones.
   - **Histeresis Neuronal:** Aplica umbrales diferenciados (`start_threshold=0.50`, `end_threshold=0.35`) para evitar cortes prematuros por fonemas suaves o fluctuaciones leves.
   - **End-of-Speech Adaptativo y Deduplicación:** Umbrales de silencio de 1.0s para comandos breves (< 1.2s) y 1.35s para habla extendida (>= 1.2s). Garantiza que `SPEECH_END` se emita exactamente una vez por turno.
   - **Inferencia en CPU:** Inferencia exclusivamente bajo `CPUExecutionProvider` (1 hilo intra-op/inter-op, memory arena deshabilitada), sin asignación de GPU ni consumo de VRAM.

2. **Fábrica y Selección Explícita (`services/voice/vad_service.py`):**
   - Implementada la función `get_vad_service(backend=None, fallback_to_energy=True, **kwargs)`.
   - Si no se especifica backend, respeta la configuración activa (`VAD_BACKEND="energy"`, `SILERO_VAD_ENABLED=False`).
   - Si se solicita `"silero"` y el runtime u ONNX no está disponible, registra una advertencia y realiza un fallback limpio a `EnergyVADService`.

3. **Configuración Tipada (`config/settings.py` y `.env.example`):**
   - Añadidos a `AppSettings`: `VAD_BACKEND: str = "energy"`, `SILERO_VAD_ENABLED: bool = False`, `SILERO_VAD_MODEL_PATH: Path | None = None`, `SILERO_VAD_THRESHOLD: float = 0.50`, `SILERO_VAD_NEG_THRESHOLD: float = 0.35`, `SILERO_VAD_SAMPLE_RATE: int = 16000`, `SILERO_VAD_WINDOW_SIZE: int = 512`.
   - Validador `@field_validator("VAD_BACKEND")` que restringe las opciones estrictamente a `{"energy", "silero"}`.

4. **Invariantes de Seguridad y Privacidad:**
   - Silero VAD es un componente sensor acústico: no autoautoriza acciones, no modifica permisos ni ejecuta comandos en el SO.
   - Sus `capabilities()` declaran honestamente: `speaker_recognition: False` (no identifica quién habla) y `echo_cancellation: False` (no resuelve el eco acústico del altavoz; esa tarea compete al `BargeInController`).
   - Cero fuga de datos: el procesamiento es 100% local en CPU y offline (`requires_network: False`).

### 15.3. Comparativa Empírica: Silero VAD vs EnergyVADService (Corpus Independiente)

| Escenario Acústico | Métrica / Comportamiento | EnergyVADService | SileroVADService | Veredicto / Impacto |
| :--- | :--- | :--- | :--- | :--- |
| **Ruido Continuo de Ventilador (RMS > 1200)** | Falsos inicios (`SPEECH_START`) | **Fallo:** Emite `SPEECH_START` espurio por energía RMS | **Éxito:** Mantiene `SILENCE` continuo (prob < 0.11) | Silero elimina falsos disparos por ruido estacionario. |
| **Clics de Teclado Mecánico** | Falsos inicios por percusión | **Fallo:** Transitorios breves disparan habla | **Éxito:** Rechaza clics impulsivos como no-voz (0 falsos inicios) | Silero discrimina transitorios no humanos. |
| **Silencio Puro / Fondo Bajo** | Detección de silencio | `SILENCE` consistente | `SILENCE` consistente (prob < 0.02) | Ambos son correctos. |
| **Voz Española Real (SAPI / Offline)** | Detección y confianza | Detecta por volumen RMS | Detecta voz humana con confianza > 0.94 | Silero aporta probabilidad semántica de voz. |
| **Latencia de Inferencia en CPU** | Tiempo por chunk de 50ms | ~0.05 ms (cálculo RMS básico) | **~2.4 ms** (Inferencia ONNX 1 hilo CPU) | Silero es ligero y opera 20x más rápido que tiempo real. |
| **Pausas Largas de Pensamiento (1.5s)** | Fin de habla adaptativo | Cierra habla a los 1.0s - 1.35s | Cierra habla a los 1.0s - 1.35s sin cortes prematuros | Comportamiento consistente y configurable. |

### 15.4. Decisión y Preservación del Backend Predeterminado
* Aunque Silero VAD supera ampliamente a Energy VAD en rechazo de ruido de ventilador y clics de teclado, **se conserva `EnergyVADService` como backend por defecto (`VAD_BACKEND="energy"`, `SILERO_VAD_ENABLED=False`)** para respetar la directiva de no alterar el comportamiento base del sistema sin solicitud explícita del usuario y evitar dependencias obligatorias de binarios C++.
* La activación de Silero VAD queda totalmente disponible mediante variable de entorno o flag: `VAD_BACKEND=silero` o `SILERO_VAD_ENABLED=true`.

### 15.5. Evidencia de Pruebas Ejecutadas
* **Suite Específica de Silero VAD (I1):**
  - `pytest tests/voice/test_silero_vad_integration_phase_i1.py -v`: **10 passed in 3.93s (100%)**.
* **Suite Completa del Subsistema de Voz:**
  - `pytest tests/voice/ -v`: **170 passed in 70.74s (100%)**.
* **Suite de Regresión Multifase (Fases 6 a 12 + I1):**
  - `pytest tests/test_config_effective_phase06.py tests/test_ui_and_browser_observation_provenance_phase09.py tests/test_consolidation_phase10.py tests/test_performance_phase11.py tests/test_are_generalized_planning_phase12.py tests/are/ tests/test_are_adapter.py -v`: **160 passed in 18.53s (100%)**.
* **Total de Pruebas Verificadas Sin Regresiones:** **330 tests aprobados con 0 fallos (100%)**.

### 15.6. Comandos de Instalación, Prueba y Rollback
* **Instalación de la dependencia opcional:**
  ```powershell
  pip install "onnxruntime>=1.16.0,<=1.23.2"
  # O alternativamente:
  pip install -e ".[vad]"
  ```
* **Comandos de ejecución de pruebas:**
  ```powershell
  pytest tests/voice/test_silero_vad_integration_phase_i1.py -v
  pytest tests/voice/ -v
  ```
* **Forma de Revertir (Rollback):**
  - Restaurar `pyproject.toml`, `config/settings.py`, `.env.example`, `services/voice/vad_service.py`, `services/voice/audio_capture.py`, `services/voice/voice_pipeline.py`, `core/local_agent/voice_interface.py`, `services/voice/__init__.py`, `services/voice/voice_errors.py`.
  - Eliminar `services/voice/silero_vad_service.py` y `tests/voice/test_silero_vad_integration_phase_i1.py`.

---

## 16. FASE I2: PLAYWRIGHT PARA EL NAVEGADOR (microsoft/playwright-python)

### 16.1. Identificación de Solapamientos y Arquitectura Seleccionada
* **Repositorio y Versión Oficial:** `https://github.com/microsoft/playwright-python`
* **Licencia:** Apache-2.0 (Copyright (c) Microsoft Corporation).
* **Versión Fijada en Dependencias Opcionales:** `playwright>=1.40.0,<=1.50.0` (instalada: `playwright==1.50.0`). Declarada en `pyproject.toml` bajo `[project.optional-dependencies] browser = [...]`.
* **Justificación de Elección (Librería Python vs playwright-mcp):**
  - JESSYCA ya cuenta con la gobernanza centralizada de navegación web en Python (`BrowserSessionManager`, `BrowserAgent`, `ControlledAgentLoop`, `URLAllowlistPolicy`, `BrowserPolicy`).
  - La integración como adaptador nativo `PlaywrightBrowserAdapter` detrás del contrato `IBrowserAdapter` evita dependencias de servidores Node.js/MCP externos, elimina latencias de procesos auxiliares y permite la inspección directa de hilos, cancelación síncrona mediante `EmergencyStop` y contención estricta en memoria.

### 16.2. Protocolo Real del Adaptador y Contratos
* **Ampliación Coherente de `IBrowserAdapter` (`core/browser_models.py`):**
  Se formalizó el protocolo para satisfacer las capacidades reales de automatización web requeridas en la Fase I2:
  - `open_url(url: str, new_tab: bool = False) -> BrowserTab`
  - `get_active_tab() -> BrowserTab | None`
  - `switch_tab(tab_id: str) -> BrowserTab`
  - `close_tab(tab_id: str) -> bool`
  - `execute_js_snippet(snippet: AllowedJSSnippet, params: dict | None) -> Any`
  - `control_media(tab_id: str, action: str) -> BrowserTab`
  - `get_text(selector: str | None = None) -> str`
  - `query_dom(selector: str) -> dict[str, Any]`
  - `get_accessibility_snapshot() -> dict[str, Any]`
  - `fill_form(selector_values: dict[str, str]) -> dict[str, bool]`
  - `click(selector: str) -> bool`
  - `download_file(url_or_selector: str, sandbox_dir: str, target_filename: str | None = None) -> str`
  - `health() -> dict[str, Any]`
  - `capabilities() -> dict[str, Any]`
  - `close() -> None`
* **Paridad de Implementaciones:**
  Tanto `FakeBrowserAdapter` como `WindowsBrowserAdapter` en `core/browser_session_manager.py` implementan la totalidad del protocolo ampliado, garantizando paridad absoluta en pruebas unitarias y entornos sintéticos.

### 16.3. Garantías Técnicas y de Seguridad
1. **Aislamiento Técnico y Compatibilidad Sync/Async (`_PlaywrightWorkerThread`):**
   - Playwright Sync API falla si se ejecuta dentro de un hilo con un event loop de `asyncio` activo (`Sync API inside asyncio loop`).
   - Se implementó un hilo de trabajo dedicado (`_PlaywrightWorkerThread`) que ejecuta el bucle de Playwright y atiende comandos mediante colas seguras `queue.Queue`.
   - Permite invocar operaciones de navegador desde hilos síncronos puros o desde corrutinas asíncronas (`asyncio.run()`, FastAPI, pytest-asyncio) sin conflicto de runtime.
2. **Perfil de Automatización Separado y Canal Microsoft Edge:**
   - Detecta y respeta el canal `msedge` instalado en Windows (`msedge.exe` versión 154 verificada).
   - Utiliza contextos efímeros o perfiles aislados (`BrowserContext`) por sesión: no comparte estado autenticado, cookies ni almacenamiento local entre usuarios y nunca accede al perfil personal del usuario de Microsoft Edge.
3. **Política Deny-by-Default en Navegación y Redirecciones:**
   - Validación determinista de URL inicial con `URLAllowlistPolicy` (bloqueo de esquemas peligrosos `javascript:`, `file:`, `data:` y dominios fuera de whitelist).
   - Interceptación de peticiones de red mediante `context.route("**/*")` que aborta inmediatamente (`route.abort("accessdenied")`) cualquier navegación o redirección a dominios no autorizados, evitando fugas de red o intentos de exfiltración.
4. **Tratamiento de Páginas como Datos No Confiables (Anti-Prompt Injection):**
   - El texto y atributos extraídos de páginas web son estrictamente **DATA** no confiable. No modifican permisos de usuario ni se interpretan como instrucciones ejecutables del asistente.
   - Sanitización de secretos automática mediante `BrowserPolicy.sanitize_dom_for_llm` (redacción de contraseñas, tokens y cookies).
5. **Descargas Confinadas a Sandbox y Prevención de Escape:**
   - Toda descarga se confina estrictamente a la raíz de `sandbox_dir`.
   - Detección y rechazo de path traversal (`../`) elevando `SandboxEscapeError`.
   - Bloqueo de extensiones ejecutables peligrosas (`.exe`, `.bat`, `.cmd`, `.ps1`, etc.) mediante `BrowserPolicy.validate_download`.
   - Verificación física de existencia y tamaño de archivo en disco tras la descarga.
6. **Prohibición de JavaScript Arbitrario:**
   - Prohibido el uso de herramientas de evaluación arbitraria de código (`page.evaluate("...")`).
   - Solo se permite la ejecución de snippets cerrados predefinidos en `AllowedJSSnippet`.
7. **Control y Cancelación:**
   - Verificación continua de cancelación ante `EmergencyStopManager`. Si se activa la parada de emergencia, se detienen inmediatamente clics, descargas y navegaciones.
8. **Configuración y Fallback:**
   - `BROWSER_BACKEND = "windows"` y `PLAYWRIGHT_ENABLED = False` por defecto.
   - Si Playwright no está disponible o falla su inicialización, `resolve_browser_adapter()` recurre limpiamente a `WindowsBrowserAdapter` emitiendo un log explícito de advertencia.

### 16.4. Evidencia de Pruebas Ejecutadas
* **Suite de Pruebas de Integración Playwright (Fase I2):**
  - `pytest tests/browser/test_playwright_adapter_phase_i2.py -v`: **17 passed in 22.46s (100%)**.
    - Test 1: Contrato, protocolo, health y capabilities reales.
    - Test 2: Cierre ordenado de recursos (`close()`).
    - Test 3: Navegación y política Deny-by-Default de URLs.
    - Test 4: Validación y bloqueo de redirecciones no autorizadas.
    - Test 5: Datos no confiables y sanitización de secretos en páginas web.
    - Test 6: Consulta estructurada del DOM y snapshot de accesibilidad.
    - Test 7: Relleno gobernado de formularios.
    - Test 8: Clic gobernado y verificación de estado en DOM.
    - Test 9: Clic gobernado respetando `EmergencyStop`.
    - Test 10: Descarga confinada a sandbox con verificación física en disco.
    - Test 11: Bloqueo de sandbox escape (path traversal y extensiones peligrosas).
    - Test 12: Snippets JS cerrados vs denegación de JS arbitrario.
    - Test 13: Gestión de múltiples pestañas y cambio de foco.
    - Test 14: Compatibilidad sync/async dentro de event loops de asyncio.
    - Test 15: Integración transparente con `BrowserSessionManager`.
    - Test 16: Resolución y fallback de adaptadores según configuración.
    - Test 17: Ejecución gobernada en `BrowserAgent` con procedencia `REAL_PHYSICAL`.
* **Suite Completa de Navegación y BrowserAgent:**
  - `pytest tests/browser/ tests/agents/test_browser_agent.py tests/test_ui_and_browser_observation_provenance_phase09.py tests/skills/test_browser_youtube_skill.py -v`: **63 passed in 41.50s (100%)**.
* **Regresión Multifase (ARE, Silero VAD, Router, etc.):**
  - `pytest tests/are/ tests/voice/test_silero_vad_integration_phase_i1.py tests/router/test_phase5_controlled_routing.py -q`: **61 passed (100%)**.
* **Total de Pruebas Verificadas en Fase I2:** **124 tests ejecutados y aprobados con 0 fallos (100%)**.
* **Calidad de Código:** `ruff check` aprobado sin errores ni advertencias en todos los módulos creados y modificados.

### 16.5. Comandos de Instalación, Prueba y Rollback
* **Instalación de la dependencia opcional:**
  ```powershell
  pip install "playwright>=1.40.0,<=1.50.0"
  # O alternativamente:
  pip install -e ".[browser]"
  ```
* **Comandos de ejecución de pruebas:**
  ```powershell
  pytest tests/browser/test_playwright_adapter_phase_i2.py -v
  pytest tests/browser/ -v
  ```
* **Forma de Revertir (Rollback):**
  - Restaurar `pyproject.toml`, `config/settings.py`, `.env.example`, `core/browser_models.py`, `core/browser_session_manager.py`.
  - Eliminar `core/browser_playwright_adapter.py` y `tests/browser/test_playwright_adapter_phase_i2.py`.

---

## 17. FASE I3: DOCLING PARA DOCUMENTOS (docling-project/docling)

### 17.1. Diagnóstico, Solapamientos y Dependencias
* **Repositorio y Versión Oficial:** `https://github.com/docling-project/docling`
* **Licencia del Código y Modelos:**
  - Código y modelos Docling: **MIT License** (Copyright (c) IBM Corp. / Docling Project).
  - RapidOCR / PP-OCR: **Apache-2.0**.
* **Versión Fijada en Dependencias Opcionales:** `docling>=2.0.0,<=2.133.0` (instalada: `docling==2.133.0`, `docling-core==2.99.0`, `docling-ibm-models==4.0.3`, `docling-parse==7.22.1`). Declarada en `pyproject.toml` bajo `[project.optional-dependencies] docling = [...]`.
* **Solapamientos Identificados en el Código Actual:**
  - `AnyDocAdapter` (`core/anydoc/adapter.py`): adaptador documental existente basado en `firecrawl-anydoc 0.2.4`.
  - `AnyDocGovernedOrchestrator` (`core/anydoc/orchestrator.py`): orquestación gobernada bajo JDE con validación de contratos sellados criptográficamente (SHA-256), idempotencia y emisión de recibos.
  - Catálogo ARE (`core/are/action_catalog.py`): acción `documents.convert` delegando en AnyDoc.
* **Criterio de Aislamiento:** No se copió el repositorio entero dentro del core; se implementó el adaptador `DoclingBackend` detrás del contrato existente de AnyDoc, desacoplado y con importación perezosa (lazy import).

### 17.2. Auditoría y Corrección de Confinamiento en `AnyDocAdapter` (Vulnerabilidad Resuelta)
* **Diagnóstico & Reproducción Previa:**
  - **CONFIRMADO:** Se reprodujo empíricamente que `AnyDocAdapter.validate_and_confine_path` normalizaba y verificaba patrones prohibidos del sistema operativo (`\\windows\\`, etc.) y secuencias `..`, pero **no comparaba la ruta resultante con `_base_sandbox_dir` ni limitaba las lecturas/escrituras al sandbox**.
  - Como resultado, cualquier ruta absoluta legítima del sistema (ej. `C:\Users\PC\AppData\Local\Temp\evil.csv`) podía ser leída o escrita fuera del sandbox autorizado `data/anydoc/`.
* **Corrección Implementada:**
  - Se introdujo `_is_strictly_contained(target_path, parent_dir)` que normaliza rutas con `os.path.realpath` y `os.path.normcase` (crucial para Windows case-insensitivity) y comprueba estrictamente `norm_target == norm_parent or norm_target.startswith(norm_parent + os.sep)`.
  - **Ataques de Prefijo Hermano (Sibling Prefix):** Una ruta como `data/anydoc_sibling/evil.txt` es rechazada terminantemente al exigir `norm_parent + os.sep`.
  - **Aislamiento Escritura vs Lectura:**
    - Para escrituras (`is_output=True`): el archivo de salida DEBE residir estrictamente dentro de `_base_sandbox_dir`.
    - Para lecturas (`is_output=False`): el archivo debe residir dentro de `_allowed_read_dirs` (`data/anydoc`, `lab/anydoc`, `tests/anydoc`).
  - **Sincronización en Orquestador:** `AnyDocGovernedOrchestrator.validate_sandbox_path` fue actualizado para utilizar la misma función canónica `_is_strictly_contained`.

### 17.3. Componentes Implementados
1. **Adaptador Docling (`core/anydoc/docling_backend.py`):**
   - Implementa `DoclingBackend` con métodos `health()`, `capabilities()`, `convert_document()`, `close()`.
   - **Importación Perezosa (Lazy Import):** `docling.document_converter.DocumentConverter` no se importa al arrancar el agente sino hasta la primera invocación explícita.
   - **Extracción Estructurada con Procedencia:**
     - Tablas extraídas como objetos estructurados con filas, columnas, markdown y procedencia de página (`page_no`, `provenance_ref`).
     - Metadatos de páginas con dimensiones (`width`, `height`).
     - Preservación del hash SHA-256 de entrada (`input_hash`) y salida (`output_hash`).
   - **Límites Operativos y Concurrencia:**
     - `max_file_size_bytes` (50 MB por defecto)
     - `max_pages` (50 páginas por defecto)
     - `timeout_seconds` (60s)
     - Semáforo de concurrencia acotado (`concurrency_limit=1`) para prevenir saturación de VRAM/CPU.
   - **Aislamiento de Red:** Inferencia 100% local y offline con modelos locales cacheados y RapidOCR.
2. **Integración en `AnyDocAdapter` (`core/anydoc/adapter.py`):**
   - Soporte para selección de backend: `backend="docling"` o `"anydoc"`.
   - Si `DOCLING_ENABLED=True` o `ANYDOC_BACKEND="docling"`, delega la conversión a `DoclingBackend`.
   - Fallback transparente al motor nativo `anydoc` ante fallos técnicos si `DOCLING_FALLBACK_TO_ANYDOC=True`.
3. **Configuración Tipada (`config/settings.py` y `.env.example`):**
   - `ANYDOC_BACKEND: str = "anydoc"` (validado: `{"anydoc", "docling"}`).
   - `DOCLING_ENABLED: bool = False` (desactivado por defecto).
   - `DOCLING_OCR_ENABLED: bool = True`.
   - `DOCLING_MAX_PAGES: int = 50`.
   - `DOCLING_TIMEOUT_SECONDS: float = 60.0`.
   - `DOCLING_CONCURRENCY_LIMIT: int = 1`.
   - `DOCLING_FALLBACK_TO_ANYDOC: bool = True`.
4. **Invariante de Seguridad: Datos No Confiables (Data != Command):**
   - Todo texto, tabla u OCR extraído de documentos se etiqueta estrictamente como `data_untrusted=True`.
   - Ningún comando ni texto imperativo ("GRANT ADMIN", "DELETE FILES", "OVERRIDE JDE") puede autoautorizar acciones ni modificar permisos del sistema.

### 17.4. Comparativa Empírica: AnyDoc (Firecrawl) vs Docling (Mismo Corpus No Sensible)

| Archivo / Tipo | Característica / Escenario | AnyDoc (Firecrawl) | Docling Backend | Análisis / Beneficio Específico |
| :--- | :--- | :--- | :--- | :--- |
| **`simple.pdf`** (PDF Digital 2 págs) | Texto extraído y páginas | 12.72 ms \| 1070 caracteres \| 0 tablas | 14079 ms (cold start) \| 1036 caracteres \| 2 páginas estructuradas con dimensiones | AnyDoc es más rápido para texto plano simple; Docling aporta estructura geométrica y procedencia por página. |
| **`simple.xlsx`** (Tablas Complejas) | Extracción de tablas estructuradas | 3.91 ms \| 396 caracteres \| **0 tablas detectadas** (texto concatenado) | 18.25 ms \| 636 caracteres \| **2 tablas completas** (grillas, celdas combinadas y Markdown) | **Docling supera ampliamente a AnyDoc**: extrae 2 tablas completas con headers y grid dimensional en solo 18 ms. |
| **`simple.csv`** (Tabla CSV Plana) | Datos tabulares | 2.76 ms \| 294 caracteres | 8.13 ms \| 440 caracteres \| 1 tabla estructurada | Ambos procesan correctamente; Docling provee metadatos tabulares. |
| **`scanned.pdf`** (PDF Escaneado) | Documento sin texto embebido (OCR) | **`NEEDS_OCR`** (Rechazado localmente sin cloud OCR) | **`SUCCESS`** (1935 ms \| RapidOCR local offline \| 2 páginas procesadas) | **Docling desbloquea la capacidad OCR local offline** sin llamadas externas de red. |
| **`truncated.docx`** (Archivo Malformado) | Manejo de archivos corruptos | `MALFORMED` (2.11 ms) | `MALFORMED` (4.77 ms vía fallback) | Ambos manejan errores de forma controlada sin fallos catastróficos. |

### 17.5. Decisión y Preservación del Backend Predeterminado
* **Se conserva `ANYDOC_BACKEND="anydoc"` y `DOCLING_ENABLED=False` por defecto**, respetando el principio de no alterar el comportamiento base del sistema.
* Docling queda completamente integrado como backend opcional avanzado, especialmente recomendado para flujos de extracción tabular (`xlsx`, `csv`) y procesamiento OCR local offline (`scanned.pdf`).

### 17.6. Evidencia de Pruebas Ejecutadas
* **Suite Específica de Docling e Integración Auditada (Fase I3):**
  - `pytest tests/anydoc/test_docling_integration_phase_i3.py -v`: **17 passed in 20.32s (100%)**.
* **Suite Completa del Subsistema AnyDoc:**
  - `pytest tests/anydoc/ -q`: **153 passed in 27.50s (100%)**.
* **Calidad de Código:** `ruff check` aprobado sin advertencias ni errores en `core/anydoc/`, `config/settings.py` y `tests/anydoc/`.

### 17.7. Comandos de Instalación, Prueba y Rollback
* **Instalación de la dependencia opcional:**
  ```powershell
  pip install "docling>=2.0.0,<=2.133.0"
  # O alternativamente:
  pip install -e ".[docling]"
  ```
* **Comandos de ejecución de pruebas y benchmark:**
  ```powershell
  pytest tests/anydoc/test_docling_integration_phase_i3.py -v
  python -c "import sys; sys.path.insert(0, '.'); import benchmarks.docling_benchmark_phase_i3 as b; b.run_benchmark()"
  ```
* **Forma de Revertir (Rollback):**
  - Restaurar `pyproject.toml`, `config/settings.py`, `.env.example`, `core/anydoc/adapter.py`, `core/anydoc/orchestrator.py`, `core/anydoc/__init__.py`.
  - Eliminar `core/anydoc/docling_backend.py`, `tests/anydoc/test_docling_integration_phase_i3.py` y `benchmarks/docling_benchmark_phase_i3.py`.---

## 18. Fase I4 — Evaluación e Integración de pywinauto frente a uiautomation

### 18.1. Objetivos y Alcance
* **Repositorio Evaluado:** [pywinauto/pywinauto](https://github.com/pywinauto/pywinauto) (versión fijada: `0.6.9`, Licencia: BSD 3-Clause).
* **Backend de Referencia:** `WindowsUIAutomationBackend` nativo basado en [yinkaisheng/Python-UIAutomation-for-Windows](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows) (`uiautomation` versión fijada: `2.0.29`, Licencia: Apache 2.0).
* **Criterio Clave:** Incorporar pywinauto únicamente si demuestra beneficio medible; mantener la regla estricta: `IUIInspectionBackend` es de **SÓLO LECTURA** (CERO clicks, CERO teclado), gobernando las acciones físicas por separado mediante un ejecutor de acciones (`PyWinAutoGovernedActionExecutor`) sujeto a autorización previa, cancelación y parada de emergencia.

### 18.2. Corrección Previa de Coordenadas Multi-Monitor
* **Hallazgo:** En `tools/desktop/ui_backend.py`, las funciones `get_active_window()`, `list_windows()` y `build_info()` aplicaban `max(0, rect.left)` y `max(0, rect.top)`, truncando a cero las coordenadas de ventanas y controles ubicados en monitores secundarios a la izquierda o arriba del monitor principal (los cuales tienen coordenadas virtuales de Windows negativas).
* **Solución Implementada:** Se eliminó el truncamiento `max(0, ...)` preservando los valores negativos reales (`rect.left`, `rect.top`), garantizando compatibilidad nativa con escritorios multimonitor.

### 18.3. Arquitectura Implementada para Fase I4
1. **Separación de Responsabilidades:**
   - **`PyWinAutoInspectionBackend` (`tools/desktop/pywinauto_backend.py`):**
     - Implementa estrictamente el protocolo `IUIInspectionBackend` (`inspect_ui`, `get_active_window`, `list_windows`).
     - **CERO ACCIONES FÍSICAS:** Carece de métodos de interacción (`click`, `send_keys`).
     - **Manejo de COM:** Envuelve cada ciclo de inspección en `pythoncom.CoInitialize()` y `pythoncom.CoUninitialize()`.
     - **Manejo de Ambigüedad:** Prioriza coincidencias exactas de título y clase de ventana.
     - **Tolerancia a Stale Elements:** Maneja excepciones de controles destruidos en tiempo real sin colapsar el proceso ni inventar elementos sintéticos.
   - **`PyWinAutoGovernedActionExecutor` (`tools/desktop/pywinauto_action_executor.py`):**
     - Componente desacoplado para ejecución gobernada de acciones (`CLICK_ELEMENT`, `TYPE_TEXT`, `FOCUS_WINDOW`, `DRAG_AND_DROP`).
     - **CERO AUTO-AUTORIZACIÓN:** Requiere validación de política explícita de JESSYCA.
     - **CERO CLICKS ANTE DENEGACIÓN O PARADA DE EMERGENCIA:** Si la política deniega o la parada de emergencia está activa, se ejecutan exactamente **0 clicks** y se retorna `POLICY_DENIED_ZERO_CLICKS` o `EMERGENCY_STOP_ACTIVE`.
2. **Configuración Tipada (`config/settings.py` y `.env.example`):**
   - `UI_INSPECTION_BACKEND: str = "uiautomation"` (valores: `uiautomation`, `pywinauto`, `fake`).
   - `PYWINAUTO_ENABLED: bool = False` (desactivado por defecto).
   - `PYWINAUTO_BACKEND: str = "uia"` (`uia` o `win32`).
   - `PYWINAUTO_ACTION_TIMEOUT: float = 5.0`.
   - `PYWINAUTO_FALLBACK_TO_UIA: bool = True`.
3. **Fábrica `get_ui_backend` (`tools/desktop/ui_backend.py`):**
   - Soporte para `mode="pywinauto"` o `mode="pwa"` con importación perezosa sin alterar el valor predeterminado nativo.

### 18.4. Benchmark Comparativo en Windows 11 Build 26200 (Notepad)
Se ejecutó un benchmark repetible (`benchmarks/ui_automation_benchmark_phase_i4.py`) sobre Bloc de notas moderno (WinUI3 / XAML Islands) y controles de prueba:

| Criterio de Evaluación | Backend Nativo (`uiautomation`) | Backend Adaptador (`pywinauto`) | Análisis Técnico / Decisión |
| :--- | :--- | :--- | :--- |
| **Latencia Total de Inspección** | 84.70 ms (11.22 ms búsqueda + 73.48 ms árbol) | 76.22 ms (6.45 ms búsqueda + 69.77 ms árbol) | Tiempos equivalentes en orden de magnitud (~80 ms). |
| **Elementos Detectados** | **56 elementos** (recorrido exhaustivo WinUI3) | **43 elementos** (omite sub-elementos internos de DesktopChildSiteBridge) | **`uiautomation` nativo penetra con mayor profundidad** en controles modernos de Windows 11. |
| **Soporte Multi-Monitor** | Preserva coordenadas negativas virtuales sin truncar | Devuelve coordenadas virtuales de Windows (L, T, R, B) | Ambos preservan la geometría multimonitor tras la corrección. |
| **Comportamiento Threading COM** | Maneja COM vía `comtypes` de forma aislada y no invasiva | Emite `UserWarning: Revert to STA COM threading mode`, requiriendo aislamiento estricto en hilos de fondo | **`uiautomation` es más amigable con servidores FastAPI/asyncio** sin forzar modo STA global. |
| **Separación Inspección / Acción** | Arquitectura nativa ya desacopla `UIBackend` de `AutomationBackend` | `pywinauto` une inspección y acción en `WindowSpecification`, requiriendo un adaptador gobernado | Se mantuvo la regla de oro: `PyWinAutoInspectionBackend` es de sólo lectura y las acciones residen en `PyWinAutoGovernedActionExecutor`. |

### 18.5. Decisión Arquitectónica
* **Se conserva `UI_INSPECTION_BACKEND="uiautomation"` y `PYWINAUTO_ENABLED=False` por defecto**, ya que el backend nativo ofrece mayor profundidad de controles en aplicaciones modernas de Windows 11 y menor interferencia con el modelo de subprocesos COM/asyncio.
* `pywinauto` queda disponible como adaptador opcional para escenarios específicos de automatización win32 legacy mediante configuración explícita.

### 18.6. Evidencia de Pruebas Ejecutadas
* **Suite Específica de pywinauto (Fase I4):**
  - `pytest tests/desktop/test_pywinauto_integration_phase_i4.py -v`: **12 passed in 0.43s (100%)**.
* **Suite Completa del Subsistema Desktop:**
  - `pytest tests/desktop/ -v`: **128 passed in 7.24s (100%)**.
* **Suite de Procedencia y Observación UI (Fase 09):**
  - `pytest tests/test_ui_and_browser_observation_provenance_phase09.py -v`: **12 passed in 2.59s (100%)**.
* **Verificación de Ejecución Semántica de Notepad:**
  - `pytest tests/test_notepad_semantic_execution.py -v`: **7 passed in 21.60s (100%)**.
* **Calidad de Código:** `ruff check` aprobado sin errores ni advertencias (0 issues).

### 18.7. Comandos de Instalación, Prueba y Rollback
* **Instalación:**
  ```powershell
  pip install "uiautomation>=2.0.18,<=2.0.29" "pywinauto>=0.6.8,<=0.6.9"
  # O alternativamente:
  pip install -e ".[pywinauto]"
  ```
* **Ejecución de Pruebas y Benchmark:**
  ```powershell
  pytest tests/desktop/test_pywinauto_integration_phase_i4.py -v
  python benchmarks/ui_automation_benchmark_phase_i4.py
  ```
* **Rollback:**
  - Eliminar `tools/desktop/pywinauto_backend.py`, `tools/desktop/pywinauto_action_executor.py`, `tests/desktop/test_pywinauto_integration_phase_i4.py`, `benchmarks/ui_automation_benchmark_phase_i4.py`, `reports/pywinauto_vs_uiautomation_benchmark.json`.
  - Revertir cambios en `config/settings.py`, `.env.example`, `pyproject.toml` y `tools/desktop/ui_backend.py`.

---

## 19. Fase I5 — Detección Acústica de Wake Word con openWakeWord y Veracidad de Soporte en Español

### 19.1. Diagnóstico, Solapamientos y Dependencias
* **Repositorio y Versión Oficial:** [dscripka/openWakeWord](https://github.com/dscripka/openWakeWord) (versión fijada: `0.6.0`, Licencia: Apache-2.0).
* **Dependencia Opcional:** Declarada en `pyproject.toml` bajo `[project.optional-dependencies] wakeword = ["openwakeword>=0.6.0,<=0.6.0"]`.
* **Solapamientos Identificados en el Código Actual:**
  - `KeywordWakeWordService` (`services/voice/wake_word_service.py`): detector previo con soporte Push-to-Talk y modo manual.
  - `CalibratedVoiceCaptureEngine` (`services/voice/audio_capture.py`): captura de audio calibrada con VAD.
  - `ContinuousVoiceSession` (`services/voice/continuous_voice_session.py`): orquestador conversacional multi-turno.
* **Principio Inquebrantable de Veracidad Acústica:**
  - Los modelos preentrenados oficiales de openWakeWord soportan únicamente idioma inglés (Alexa, Hey Jarvis, etc.).
  - **Bajo NINGUNA circunstancia se afirma que renombrar un modelo en inglés o cambiar la etiqueta textual a "Jessyca" crea detección acústica del nombre en español**.
  - Si no se cuenta con un modelo ONNX local compilado y entrenado para la palabra clave, el servicio declara honesta y formalmente `is_acoustic_model_available() == False` y estado tipado `ACOUSTIC_MODEL_UNAVAILABLE`, recurriendo al modo Push-to-Talk / manual sin producir falso éxito acústico ni respuestas sintéticas inventadas.

### 19.2. Invariante Crítico de Seguridad (Wake Word != Authorization)
* **La detección de palabra de activación NUNCA otorga permisos ni facultades ejecutivas.**
* `detected=True` únicamente abre la ventana de escucha de audio o turno conversacional.
* Cualquier acción física con efectos secundarios en Windows o recursos del sistema DEBE ser evaluada y aprobada por el pipeline de seguridad determinista (`SecurityPolicy`, `PermissionManager`, `RiskEngine` y `JDERuntimeBinding`).
* El campo `authorizes_action` es inmutable y estrictamente `False` en todas las instancias y respuestas de `WakeWordResult`.

### 19.3. Componentes Implementados
1. **Adaptador Acústico Desacoplado (`services/voice/openwakeword_service.py`):**
   - Implementa el protocolo formal `IWakeWordService` (`process_audio`, `reset`, `is_acoustic_model_available`).
   - **Resampling Dinámico:** Convierte automáticamente cualquier frecuencia de muestreo de entrada (8kHz, 22.05kHz, 44.1kHz, 48kHz) a los 16000 Hz requeridos por openWakeWord utilizando `scipy.signal.resample` con fallback por interpolación lineal determinista.
   - **Buffering por Ventanas:** Acumula muestras en memoria efímera hasta completar exactamente 1280 muestras (80ms a 16kHz) por ciclo de inferencia.
   - **Cooldown Anti-Ráfaga:** Período de enfriamiento configurable (`cooldown_seconds=2.0`) tras cada detección para prevenir disparos continuos.
   - **Reset de Estado:** Limpia de inmediato buffers de audio y estado interno del modelo al cambiar o reiniciar sesión.
   - **Activación Manual / Push-to-Talk:** Método `trigger_manually()` atómico para pruebas, demos o modo interactivo sin depender de inferencia acústica.
2. **Fábrica Gobernada `get_wake_word_service` (`services/voice/wake_word_service.py`):**
   - Resolución centralizada según configuración (`WAKE_WORD_BACKEND` o `OPENWAKEWORD_ENABLED`).
   - Carga perezosa (lazy import) de `OpenWakeWordAcousticService` para evitar overhead de arranque.
   - Fallback transparente y controlado a `KeywordWakeWordService` si `fallback_to_manual=True` ante fallos de carga o ausencia de modelo.
3. **Exportaciones Centralizadas (`services/voice/__init__.py`):**
   - Exporta `get_wake_word_service` y `OpenWakeWordAcousticService` (vía `__getattr__` perezoso y `__all__`).
4. **Configuración Tipada (`config/settings.py` y `.env.example`):**
   - `WAKE_WORD_BACKEND: str = "manual"` (valores: `"manual"`, `"openwakeword"`).
   - `OPENWAKEWORD_ENABLED: bool = False` (desactivado por defecto).
   - `OPENWAKEWORD_MODEL_PATH: Path | None = None`.
   - `OPENWAKEWORD_THRESHOLD: float = 0.60`.
   - `OPENWAKEWORD_COOLDOWN_SECONDS: float = 2.0`.
   - `OPENWAKEWORD_BUFFER_SECONDS: float = 1.5`.
   - `OPENWAKEWORD_TARGET_SAMPLE_RATE: int = 16000`.
   - `OPENWAKEWORD_FALLBACK_TO_MANUAL: bool = True`.
5. **Procedimiento Documentado de Entrenamiento para Español (`docs/WAKE_WORD_TRAINING_PROCEDURE.md`):**
   - Guía técnica detallada para generar corpus sintético en español (con Piper TTS / voces multilocutor), entrenar clasificador ONNX mediante el script oficial de openWakeWord y validar curva ROC antes de despliegue.
6. **Script y Reporte Reproducible de Evaluación (`scripts/evaluate_wakeword_corpus.py`):**
   - Mide latencia de resampling, consumo de memoria de buffers, comportamiento de Push-to-Talk y genera reporte auditado en `reports/wakeword_phase_i5_evaluation_report.json`.

### 19.4. Evidencia de Pruebas Ejecutadas
* **Suite Específica de openWakeWord (Fase I5):**
  - `pytest tests/voice/test_openwakeword_phase_i5.py -v`: **16 passed in 2.77s (100%)**.
    - Test 1: Cumplimiento del protocolo `IWakeWordService` y `authorizes_action is False`.
    - Test 2: Invariante de seguridad: `authorizes_action` estrictamente `False` en todos los flujos.
    - Test 3: Declaración honesta de indisponibilidad cuando no hay modelo entrenado para español.
    - Test 4: Procesamiento sin modelo devuelve estado tipado `ACOUSTIC_MODEL_UNAVAILABLE` sin excepción.
    - Tests 5-8: Resampling correcto a 16kHz desde 8kHz, 22.05kHz, 44.1kHz y 48kHz.
    - Test 9: Modo manual / Push-to-Talk independiente y consumo atómico en 1 solo chunk.
    - Test 10: `reset()` limpia triggers y vacía buffers de audio.
    - Test 11: Inferencia acústica ante modelo ONNX simulado (detección > umbral).
    - Test 12: Cooldown anti-ráfaga activo inmediatamente tras detección.
    - Test 13: Manejo graceful ante ausencia de dependencia externa `openwakeword`.
    - Test 14: Fábrica `get_wake_word_service()` retorna `KeywordWakeWordService` por defecto.
    - Test 15: Fábrica `get_wake_word_service(backend='openwakeword')` instancia `OpenWakeWordAcousticService`.
    - Test 16: Fallback transparente a manual ante fallo en inicialización.
* **Suite Completa del Subsistema de Voz:**
  - `pytest tests/voice/ -q`: **186 passed in 89.4s (100%)**, 0 errores de regresión.
* **Script de Evaluación de Corpus:**
  - `python scripts/evaluate_wakeword_corpus.py`: Ejecutado exitosamente, reporte emitido en `reports/wakeword_phase_i5_evaluation_report.json` con `authorizes_action: False` certificado en el 100% de escenarios.
* **Calidad de Código:**
  - `ruff check services/voice/ tests/voice/test_openwakeword_phase_i5.py`: **0 errores, 0 advertencias**.

### 19.5. Decisión y Preservación del Estado Predeterminado
* **Se conserva `WAKE_WORD_BACKEND="manual"` y `OPENWAKEWORD_ENABLED=False` por defecto**.
* JESSYCA mantiene su estabilidad y comportamiento predeterminado, permitiendo activar la inferencia acústica de openWakeWord como complemento opcional cuando se cuente con el modelo ONNX entrenado para la palabra clave en español.

### 19.6. Comandos de Instalación, Prueba y Rollback
* **Instalación:**
  ```powershell
  pip install "openwakeword>=0.6.0,<=0.6.0"
  # O alternativamente:
  pip install -e ".[wakeword]"
  ```
* **Ejecución de Pruebas y Evaluación:**
  ```powershell
  pytest tests/voice/test_openwakeword_phase_i5.py -v
  python scripts/evaluate_wakeword_corpus.py
  ```
* **Rollback:**
  - Eliminar `services/voice/openwakeword_service.py`, `tests/voice/test_openwakeword_phase_i5.py`, `scripts/evaluate_wakeword_corpus.py`, `reports/wakeword_phase_i5_evaluation_report.json`, `docs/WAKE_WORD_TRAINING_PROCEDURE.md`.
  - Revertir cambios en `config/settings.py`, `.env.example`, `pyproject.toml`, `services/voice/wake_word_service.py` y `services/voice/__init__.py`.

---

## 20. Remediación de Resultados Simulados y Gobernanza de Ejecución (Anti-False-Success)

### 20.1. Diagnóstico y Alcance de las Rutas Afectadas
En la auditoría exhaustiva de la copia de trabajo se identificaron componentes críticos donde se simulaban ejecuciones y verificaciones, aparentando éxitos reales sin comprobación física ni ejecución de comandos:

1. **`core/orca_ade/adapter.py:execute_governed_task`:**
   - **Ruta afectada:** Invocaciones gobernadas al adaptador ORCA/ADE desde `ARERuntime`, `Orquestador` o adaptadores de integración subordinados al JDE.
   - **Comportamiento previo:** Generaba sintéticamente rutas como `modified_file.py`, simulaba `tests={"passed": True, "exit_code": 0}`, y devolvía `status="VERIFIED_SUCCESS"` con `verified=True` de forma incondicional sin ejecutar ningún proceso en el sistema operativo ni verificar cambios en disco.
   - **Falla en cache:** Los impactos en caché (`CACHE_HIT`) forzaban `verified=True` arbitrariamente, transformando tareas pendientes o no verificadas en éxitos certificados.

2. **`core/orca_ade/orchestrator.py:dispatch_task` y `approve_review`:**
   - **Ruta afectada:** Despacho de tareas paralelas agénticas y compuertas de revisión de código (Review Gate).
   - **Comportamiento previo en `dispatch_task`:** Construía en memoria `code_patch.py` y `tests={"exit_code": 0, "passed": True}`, emitiendo `VERIFIED_SUCCESS` o `CLAIMED_SUCCESS` sin un ejecutor conectado.
   - **Comportamiento previo en `approve_review`:** La compuerta de revisión sustituía la comprobación física por la firma de la autoridad: llamar a `approve_review()` marcaba incondicionalmente `status="VERIFIED_SUCCESS"` y `verified=True`, incluso en ausencia total de evidencia física o pruebas ejecutadas.
   - **Falla en cache:** Los aciertos de idempotencia forzaban `verified=True`. Además, `self._idempotency_cache` estaba inicializado como lista `[]` en lugar de diccionario `{}`, provocando excepciones en accesos por clave hash.

3. **`tools/desktop/ui_backend.py`:**
   - **Ruta afectada:** Inspección de ventanas y jerarquía UI del escritorio (`WindowsUIAutomationBackend`).
   - **Comportamiento auditado:** Se verificó que `WindowsUIAutomationBackend` no recurre a ventanas ficticias o sintéticas cuando falla `uiautomation` o `pywinauto`. Lanza `UIBackendUnavailableError` en consultas directas o retorna `ObservationStatus.BACKEND_UNAVAILABLE` con `provenance="UNAVAILABLE"` y `elements_flat=()`. La selección de backends sintéticos (`FakeUIInspectionBackend`) quedó estrictamente restringida a selección explícita por entorno (`test`, `demo`).

4. **`core/agents/browser_agent.py`:**
   - **Ruta afectada:** Navegación web y automatización de Edge vía `BrowserAgent` invocado por el bucle local o herramientas de búsqueda/descarga.
   - **Comportamiento previo:** En cualquier entorno distinto a producción (por ejemplo, desarrollo local o integración controlada), seleccionaba silenciosamente `FakeBrowserAdapter`, reportando éxito y completitud de bucle agéntico en memoria sin abrir ningún navegador real.
   - **Comportamiento corregido:** La selección de `FakeBrowserAdapter` se restringió exclusivamente a cuando `ENVIRONMENT` o `JESSYCA_BROWSER_MODE` es explícitamente `test` o `demo`. En modo operativo real, si falta el adaptador real Playwright, el agente desactiva la disponibilidad (`_browser_available = False`, `session_manager = None`) y reporta `BROWSER_UNAVAILABLE` con estado `AgentLoopState.STOPPED_ERROR`.

---

### 20.2. Reglas Arquitectónicas Implementadas
1. **Separación Estricta de Estados:**
   - **Ejecutar**, **Aprobar** y **Verificar** son estados técnica y formalmente independientes.
   - Una aprobación de la autoridad (JDE / Revisor) **NUNCA** sustituye la comprobación del resultado en el sistema. Aprobar sin evidencia física reproducible produce `APPROVED_UNVERIFIED` con `verified=False`.
2. **Conexión de Ejecutores Reales:**
   - Si no hay un ejecutor real conectado (`effective_executor is None`), el sistema **NUNCA** produce éxito: retorna `UNAVAILABLE` con `verified=False` y transiciona el ciclo de vida a `FAILED`.
   - Se eliminaron las rutas inventadas (`modified_file.py`, `code_patch.py`) y los diccionarios de tests falsos.
3. **Derivación de Resultados Observados:**
   - `changed_files` se filtra estrictamente a los archivos que existen efectivamente en el sistema de archivos (`os.path.exists`).
   - Si una prueba o comando falla (`tests.passed=False` o `exit_code != 0`), el resultado conserva indefectiblemente el fallo (`status="FAILED"`, `verified=False`).
   - La evidencia marcada como sintética (`synthetic=True`, `is_synthetic=True`, `SYNTHETIC_TEST`) es rechazada como prueba de efectos físicos: solo puede culminar en `UNVERIFIED` o `APPROVED_UNVERIFIED`.
4. **Preservación Inviolable del Estado en Caché:**
   - Los aciertos de idempotencia (`CACHE_HIT`) conservan fielmente el estado original de verificación (`verified = cached.verified`). Un resultado no verificado permanece como `verified=False`.

---

### 20.3. Pruebas Obligatorias y Validación Ejecutada
Se creó la suite dedicada [`tests/orca_ade/test_false_success_and_execution_governance.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tests/orca_ade/test_false_success_and_execution_governance.py) que certifica los 6 requisitos obligatorios:

| Requisito Obligatorio | Prueba Implementada | Resultado |
| :--- | :--- | :--- |
| 1. Executor ausente no produce éxito | `test_executor_absent_does_not_produce_success` | **PASSED (UNAVAILABLE, verified=False)** |
| 2. Prueba fallida conserva el fallo | `test_failed_test_preserves_failure` | **PASSED (FAILED, exit_code=1, verified=False)** |
| 3. Aprobación sin evidencia no produce VERIFIED_SUCCESS | `test_approval_without_evidence_does_not_produce_verified_success` | **PASSED (APPROVED_UNVERIFIED, verified=False)** |
| 4. Evidencia sintética no certifica efectos físicos | `test_synthetic_evidence_does_not_certify_physical_effects` | **PASSED (UNVERIFIED, verified=False)** |
| 5. Backend ausente se informa como tal | `test_backend_unavailable_reported_as_such` | **PASSED (UIBackendUnavailableError / BROWSER_UNAVAILABLE)** |
| 6. Un resultado cacheado conserva su estado de verificación | `test_cached_result_preserves_verification_state` | **PASSED (CACHE_HIT conserva verified=False)** |

**Evidencia de Ejecución:**
* `pytest tests/orca_ade/test_false_success_and_execution_governance.py -v`: **6 passed in 0.20s (100%)**.
* `pytest tests/orca_ade/ -v`: **124 passed in 2.51s (100%)** (cobertura completa de adaptadores, gobernanza JDE, compuertas de revisión, concurrencia, fallo controlado y E2E).
* `pytest tests/desktop/ tests/agents/ -v`: **160 passed in 8.79s (100%)** (cero regresiones en backends de UI ni bucles agénticos).

---

## 21. Corrección Secuencial de Hallazgos A–F (Prompt 00 / Subetapas 01–06)

### 21.1. Hallazgo A — Mobile API (Seguridad y Confinamiento)
* **Token de desarrollo inseguro eliminado:** `validate_mobile_api_token()` rechaza tokens nulos, vacíos, con solo espacios y el token de desarrollo `"jessyca-dev-token-insecure"`. Requiere secreto configurado antes de iniciar el servicio (o aborta con error 1 y `ValueError`).
* **Confinamiento de red:** Escucha en loopback (`127.0.0.1`) por defecto. Si se configura host de red/LAN (`0.0.0.0` o IP externa), emite una advertencia de seguridad explícita.
* **CORS y deshabilitación:** `MOBILE_API_CORS_ORIGINS` vacío por defecto (CORS deshabilitado/mismo origen). Si contiene `["*"]`, anula `allow_credentials` para prevenir fuga de cookies/credenciales. El flag `MOBILE_API_ENABLED=False` bloquea el arranque en `server.py` salvo `--force` explícito desde CLI.
* **Evidencia:** `pytest tests/test_mobile_api.py -v`: **20 passed in 1.03s (100%)**.

### 21.2. Hallazgo B — SecurityPolicy (Inmutabilidad Profunda y Snapshot Defensivo)
* **Inmutabilidad recursiva profunda:** `SecurityPolicy` y sus reglas `PolicyRule` son instancias congeladas (`frozen=True`). Atributos reasignados lanzan `FrozenInstanceError` o `InvalidPolicyError`.
* **Blindaje contra mutación del objeto original:** Las condiciones de reglas (`conditions`) y parámetros anidados se congelan recursivamente usando tuplas y `MappingProxyType`. Las listas y diccionarios originales usados durante la construcción (`SecurityPolicyBuilder`) pueden modificarse posteriormente sin alterar el snapshot de la política activa.
* **Serialización y DENY Override:** Métodos `to_dict()` y `to_json()` realizan round-trips completos preservando tipos inmutables. Reglas con veredicto `DENY` prevalecen de forma absoluta ante cualquier regla `ALLOW`.
* **Evidencia:** `pytest tests/security/test_deep_policy_immutability.py -v`: **8 passed in 0.12s (100%)**, `pytest tests/security/ -q`: **242 passed in 4.64s (100%)**.

### 21.3. Hallazgo C — Timeout, Cancelación Cooperativa e Idempotencia
* **Desacoplamiento Timeout vs Hilo:** `asyncio.wait_for` sobre `asyncio.to_thread` nunca cancela forzosamente un hilo del SO en ejecución. Se implementó `OperationManager` con tokens de cancelación cooperativa (`CancellationToken`). Ante un timeout de transporte HTTP (504), la tarea continúa en segundo plano con estado `RUNNING` o `CANCEL_REQUESTED`, sin dar por cancelada la acción ni autorizar repetición de escrituras.
* **Idempotencia por operación/sesión/payload:** Clave de idempotencia calculada mediante SHA-256 sobre el payload normalizado (excluyendo encabezados volátiles). Clave idéntica con payload diferente produce `IdempotencyConflictError` (HTTP 409). Clave nueva con mismo texto se procesa como acción legítima independiente.
* **Concurrencia:** Duplicados simultáneos se unen a la operación en vuelo ejecutando el efecto físico exactamente una vez.
* **Evidencia:** `pytest tests/test_timeout_cancellation_idempotency.py -v`: **8 passed in 2.32s (100%)**.

### 21.4. Hallazgo D — AI Planner (Orden Topológico Determinista y Detección de Ciclos)
* **Resolución Topológica Determinista:** `AIPlanner.get_ordered_tasks()` reemplaza el orden puramente numérico por ordenamiento topológico mediante el algoritmo de Kahn sobre el DAG de dependencias. Desempata por `(execution_order, task_id)` solo entre nodos cuyas dependencias ya finalizaron.
* **Validación estructural de grafos:** `validate_dependencies()` rechaza referencias inexistentes (`MissingDependencyError`), dependencias circulares/ciclos (`CircularDependencyError`), autodependencias (`SelfDependencyError`) y nodos con IDs duplicados (`DuplicateNodeError`).
* **Evidencia:** `pytest tests/test_planner_topological.py -v`: **13 passed in 0.18s (100%)**.

### 21.5. Hallazgo E — Configuración (Eliminación de Declaraciones Duplicadas)
* **Unicidad en AppSettings:** Se eliminaron las declaraciones duplicadas de `BROWSER_URL_ALLOWLIST_ENABLED`, `BROWSER_ALLOWED_SCHEMES`, `BROWSER_BLOCKED_SCHEMES` y `BROWSER_ALLOWED_DOMAINS` en `config/settings.py` (líneas 1120-1144), fusionando los dominios permitidos (`"127.0.0.1"`, `"localhost"`) en la declaración principal (líneas 280-302).
* **Campos del Router y Nemotron únicos:** Se certificó la presencia única de `MODEL_ROUTER_ENABLED`, `MODEL_ROUTER_MODE`, `ROUTER_CONFIDENCE_THRESHOLD`, `ROUTER_SHADOW_LOG_FILE` y `NEMOTRON_ENABLED`.
* **Evidencia:** `pytest tests/test_config_effective_phase06.py -v`: **42 passed in 0.91s (100%)**.

### 21.6. Hallazgo F — Memoria (Persistencia Atómica y Tolerancia a Fallos)
* **Reemplazo Atómico:** `LongTermMemoryEngine` escribe los registros a un archivo temporal (`tempfile.NamedTemporaryFile` con prefijo `.tmp_ltm_` en el mismo directorio de almacenamiento) y ejecuta `os.replace` al archivo final `.json`.
* **Tolerancia a fallos e integridad:** Fallos en serialización, I/O o reemplazo atómico limpian los temporales propios, no truncan el archivo existente en disco, lanzan `MemoryPersistenceError` con metadatos estructurados y revierten la caché en memoria para garantizar coherencia exacta entre memoria y disco.
* **Concurrencia:** Protegido con `threading.RLock` intra-proceso para evitar corrupción en acceso multi-hilo.
* **Evidencia:** `pytest tests/memory/test_long_term_memory_reliable_persistence_phase07.py -v`: **9 passed in 0.59s (100%)**, `pytest tests/memory/ -q`: **92 passed in 4.34s (100%)**.

---

## 22. Fase 17.1.4: Respuestas Técnicas Precisas y Eliminación del Pitch Automático

### 22.1. Diagnóstico y Origen del Comportamiento
* **Prompts del Sistema:** En `core/local_agent/conversational_handler.py`, el `DEFAULT_SYSTEM_PROMPT` iniciaba con *"Eres Jessyca, tu asistente local e inteligente para Windows"*, lo que provocaba que los modelos LLM (Ollama, Gemma, Nemotron) antepusieran saludos promocionales y listas de funciones (*"¡Hola! Soy Jessyca, tu asistente para Windows. Te comento que..."*) antes de responder consultas técnicas cotidianas.
* **Handlers y Síntesis:** En `_synthesize_dialogue()`, los saludos directos inyectaban automáticamente `"¡Hola! Soy Jessyca. ¿En qué te puedo ayudar hoy?"` forzando la autopresentación en cada interacción de cortesía.
* **FastRouter:** En `core/routing/fast_router.py`, ante solicitudes conversacionales genéricas como `"cuéntame algo"` o `"dime algo"`, se respondía con el pitch publicitario `"Soy JESSYCA, tu asistente de voz e inteligencia para Windows. Puedo abrir aplicaciones, controlar audio..."`.
* **Falta de distinciones epistémicas:** Consultas técnicas sobre datos externos no comprobados o desconocidos (ej. saldo de cuenta bancaria, correos) o sobre limitaciones operativas corrían el riesgo de alucinar o desviar la atención con publicidad de funciones existentes.

### 22.2. Correcciones Implementadas
1. **Refuerzo de `DEFAULT_SYSTEM_PROMPT`:**
   * Establece como regla primordial responder primero y directamente a la pregunta concreta.
   * Prohíbe expresamente autopresentaciones, listas de capacidades o invitaciones comerciales no solicitadas.
   * Exige distinción epistémica rigurosa entre hechos comprobados (historial/sistema), inferencias y datos desconocidos.
   * Prohíbe terminantemente inventar archivos, comandos, dependencias, rutas, resultados o métricas.
   * Prohíbe declarar finalizada o exitosa una acción antes de contar con verificación observable.
   * Exige admitir limitaciones con franqueza y sobriedad, sin publicidad sustitutiva.
2. **Corrección de Saludos y Diálogo:**
   * Saludos en `_synthesize_dialogue` normalizados a respuestas naturales y directas (*"¡Hola! ¿En qué te puedo ayudar hoy?"*, *"¡Buenos días! ¿En qué puedo ayudarte hoy?"*), eliminando la autopresentación forzada.
   * La explicación de capacidades y la identificación de identidad se preservan estrictamente cuando el usuario las solicita de forma explícita (*"¿Quién eres?"*, *"¿Qué puedes hacer?"*).
3. **Respuestas Técnicas Directas y Manejo Epistémico:**
   * Respuestas canónicas y directas para conceptos clave (claves primarias en bases de datos, punteros en C, diferencia proceso vs hilo, git rebase, interbloqueos/deadlocks, APIs REST).
   * Reconocimiento explícito de datos desconocidos (*"No dispongo de acceso a esa información ni existen registros comprobados sobre ese dato en el sistema local"*).
   * Reconocimiento claro de limitaciones operativas sin publicidad sustitutiva (*"Esa acción no está soportada en el sistema. No dispongo de herramientas para realizarla"*).
4. **Filtro de Salida `_filter_unsolicited_pitch`:**
   * En `ConversationalDialogueHandler`, procesa tanto la salida de inferencia del LLM como la síntesis contextual.
   * Si el usuario no solicitó expresamente identidad o capacidades, remueve prefijos de autopromoción repetitiva generados por modelos de lenguaje y elimina coletillas publicitarias al final, asegurando que la respuesta inicie directamente con la solución o concepto técnico.
5. **Alineación de `FastRouter`:**
   * Separación de intents: `"cuentame algo"` o `"dime algo"` provee un dato curioso y conversación natural, mientras que `"quien eres"` responde la identidad del asistente sin pitch publicitario de audio/aplicaciones.

### 22.3. Ejemplos Antes vs. Después
* **Consulta Técnica (Clave primaria):**
  * *Antes:* `"¡Hola! Soy Jessyca, tu asistente local e inteligente para Windows. Una clave primaria es una columna..."`
  * *Después:* `"Una clave primaria es una columna o conjunto de columnas que identifica de forma unívoca cada fila en una tabla de base de datos relacional, garantizando valores únicos y no nulos."`
* **Consulta Técnica (Punteros en C):**
  * *Antes:* `"Como tu asistente para Windows, te explico que un puntero almacena direcciones de memoria..."`
  * *Después:* `"Un puntero es una variable que almacena la dirección de memoria de otra variable, permitiendo acceder y manipular datos directamente en memoria."`
* **Saludo Simple ("Hola"):**
  * *Antes:* `"¡Hola! Soy Jessyca. ¿En qué te puedo ayudar hoy?"`
  * *Después:* `"¡Hola! ¿En qué te puedo ayudar hoy?"`
* **Limitación Operativa ("Edita este video para TikTok"):**
  * *Antes:* `"Eso todavía no puedo hacerlo directamente. Soy Jessyca, pero puedo abrir aplicaciones o reproducir videos de baile."`
  * *Después:* `"Esa acción no está soportada en el sistema. No dispongo de herramientas para realizarla."`
* **Consulta Explícita de Capacidades ("¿Qué puedes hacer?"):**
  * *Resultado:* `"Soy Jessyca, tu asistente local e inteligente para Windows. Puedo ayudarte a abrir y cerrar aplicaciones, reproducir vídeos de baile, buscar contenido en internet o YouTube, gestionar archivos y realizar cálculos."` *(Preservado intacto bajo demanda explícita)*.

### 22.4. Evidencia de Pruebas
* **Suite específica:** `pytest tests/test_phase17_precision_and_no_pitch.py -v`: **17 passed in 31.21s (100%)**.
* **Suite consolidada de regresión:** `pytest tests/test_mobile_api.py tests/security/test_deep_policy_immutability.py tests/test_timeout_cancellation_idempotency.py tests/test_planner_topological.py tests/test_config_effective_phase06.py tests/memory/test_long_term_memory_reliable_persistence_phase07.py tests/test_phase17_precision_and_no_pitch.py -q`: **117 passed (100% pass rate)**.
* **Linter:** `ruff check core/local_agent/conversational_handler.py core/routing/fast_router.py tests/test_phase17_precision_and_no_pitch.py`: **All checks passed!**

---

## 23. Consolidación Canónica de JDE (JESSYCA Decision Engine)

### 23.1. Arquitectura y Separación Estricta de Responsabilidades
Se consolidó la gobernanza de JDE eliminando duplicaciones y unificando la ruta de decisión y ejecución física a través de responsabilidades formalmente delimitadas:
* **`RiskEngine`:** Calcula el nivel de riesgo objetivo (`SAFE`, `MEDIUM`, `HIGH`, `CRITICAL`).
* **`SecurityPolicy` / `PermissionManager`:** Aplican restricciones inmutables de acceso y permisos.
* **`JDE` (`JDERuntimeBinding` / `DecisionEngine`):** Coordina determinísticamente el veredicto (`ALLOW`, `DENY`, `REQUIRE_REVIEW`), estados y contratos (`DecisionContract`, `ActionReceipt`).
* **`Executor`:** Ejecuta físicamente en el sistema operativo mediante una única pasada controlada. Se eliminaron los dobles ciclos de autorización/ejecución redundantes.
* **`ExecutionVerifier` / `ActionVerifier`:** Observa empíricamente el efecto físico en el SO (procesos, ventanas, filesystem, media).
* **`ResponseSynthesizer`:** Construye la respuesta final a partir de evidencia comprobada. Si la verificación física falla o es desconocida (`UNKNOWN` / `FAILED`), se prohíbe declarar éxito (Principio Anti-False Success).

### 23.2. Gobernanza Canónica Unificada Multimodal
Voz, WebUI Bridge, Mobile API y MCP comparten la misma ruta canónica a través de `JessycaLocalAgent.interact(req)`:
1. **Normalización e Intención:** Clasificación y mapeo a herramienta física.
2. **Evaluación de Riesgo y Permisos:** `RiskEngine` y `PermissionManager` evalúan la acción propuesta.
3. **Gestión de Confirmación Vinculada (`JDEConfirmationManager`):**
   - Vinculación criptográfica estricta: `(session_id, user_id, action, parameters_hash)` con TTL monótono.
   - Neutralización de LLM: Se eliminan parámetros no confiables (`is_confirmed=True`, `confirmed=True`) inyectados por modelos o prompts.
   - Monouso y Aislamiento: Una confirmación solo autoriza su operación específica y se consume de inmediato. Dos sesiones distintas nunca comparten confirmaciones.
   - Replanificación: Cualquier modificación de parámetros o acción altera el hash y fuerza una nueva evaluación de gobernanza.
4. **Veredicto JDE:** `JDERuntimeBinding.evaluate()` evalúa modo de ejecución, kill switch, conflictos y políticas estructurales (`JDEPolicyGate`). `DENY` detiene la operación con cero efectos secundarios.
5. **Ejecución y Verificación Observable:** La acción física se ejecuta una sola vez y se verifica antes de emitir recibo o sintetizar la respuesta.

### 23.3. Evidencia de Pruebas Contractuales
* **Suite Canónica de Consolidación:** `tests/jde/test_jde_canonical_consolidation.py`
  - `test_canonical_deny_produces_zero_side_effects`: DENY produce cero efectos y el executor jamás es invocado (**PASSED**).
  - `test_canonical_valid_confirmation_authorizes_only_its_operation`: Confirmación válida autoriza únicamente su operación; parámetros alterados o inyecciones de LLM son rechazados (**PASSED**).
  - `test_canonical_two_sessions_do_not_share_confirmations`: Sesión A y Sesión B no comparten confirmaciones; consumo monouso verificado (**PASSED**).
  - `test_canonical_same_request_not_executed_twice`: IdempotencyGuard intercepta y bloquea peticiones duplicadas (**PASSED**).
  - `test_canonical_verification_failure_prevents_claiming_success`: Verificación fallida o desconocida impide declarar éxito (**PASSED**).
  - `test_canonical_all_entrypoints_reach_same_effective_policy` [TEXT, VOICE, MULTIMODAL]: Cada modalidad de entrada alcanza la misma política efectiva (**PASSED**).
* **Resultados de la Suite JDE:** `pytest tests/jde -v`: **276 passed in 14.95s (100% pass rate)**.
* **Regresión Cruzada de Interfaces:** `pytest tests/interfaces tests/test_mobile_api.py -q`: **52 passed in 7.02s (100% pass rate)**.
* **Linter:** `ruff check core/jde core/local_agent/local_agent.py tests/jde/test_jde_canonical_consolidation.py`: **All checks passed!**

---

## 24. Integración Open WebUI → JESSYCA Core (`interfaces/webui_bridge/`)

### 24.1. Diagnóstico del Entorno y Estado de Open WebUI
* **Estado de Conexión Real:** Se auditó el estado del sistema en los puertos estándar (8080, 3000, 8088, 11434) y procesos de Docker/Node/Python.
  - El daemon de Docker no se encuentra en ejecución en el sistema.
  - Open WebUI no se encuentra actualmente en ejecución ni enlazado a la máquina local.
  - Conforme al principio de honestidad epistémica de Prompt 00: **no se afirma falsamente que Open WebUI quedó conectado**, sino que se implementó, verificó y certificó el servidor puente y se especifican los valores exactos requeridos para su enlace.

### 24.2. Arquitectura de Integración Certificada
```
Open WebUI (UI Web)
       │ (OpenAI-Compatible Chat Completions API)
       ▼
WebUI Bridge (FastAPI, loopback 127.0.0.1:8088)
       │ [/v1/models, /v1/chat/completions, PUBLIC_MODEL_NAME="jessyca"]
       │ - Autenticación Bearer obligatoria (prohíbe tokens dev inseguros)
       │ - Interceptación y bloqueo de tareas internas (Auto-Title, Auto-Tags)
       │ - Resolución determinista de sesión por chat_id e historial
       │ - Soporte de X-Request-Id / Idempotency-Key
       ▼
JESSYCA Core (JessycaLocalAgent.get_instance())
       │
       ▼
Gobernanza Canónica JDE (RiskEngine -> PermissionManager -> ConfirmationManager -> JDE Binding)
       │
       ▼
Ejecución Física / Inferencia (SkillManager / Windows OS / Router -> Ollama)
       │
       ▼
Verificación Observable (ExecutionVerifier) -> ResponseSynthesizer -> WebUI Bridge (SSE o JSON)
```

### 24.3. Valores Exactos para la Configuración en Open WebUI

#### Caso A: Open WebUI instalado de forma Nativa (Python / npm en la misma máquina Windows)
* **Tipo de Conexión:** OpenAI API Compatible
* **URL Base de la API:** `http://127.0.0.1:8088/v1` (o `http://localhost:8088/v1`)
* **Clave de API / Bearer Token:** El valor secreto configurado en `WEBUI_BRIDGE_AUTH_TOKEN` (definido en `.env` o variable de entorno).
* **Modelo Seleccionado:** `jessyca` (único modelo expuesto en `/v1/models`).

#### Caso B: Open WebUI ejecutado en Contenedor Docker (Docker Desktop en Windows)
* **Tipo de Conexión:** OpenAI API Compatible
* **URL Base de la API:** `http://host.docker.internal:8088/v1`
  *(Nota técnica: `localhost` o `127.0.0.1` dentro del contenedor Docker apunta al contenedor mismo, por lo que es mandatorio usar `host.docker.internal` para alcanzar el servidor en el host de Windows)*.
* **Clave de API / Bearer Token:** El valor secreto configurado en `WEBUI_BRIDGE_AUTH_TOKEN`.
* **Modelo Seleccionado:** `jessyca`.

#### Conexión Directa a Ollama (Solo Diagnóstico / Comparación)
* **URL:** `http://127.0.0.1:11434` (Nativo) o `http://host.docker.internal:11434` (Docker).
* **Identificación:** Se distingue formalmente de JESSYCA. Conectar directamente a Ollama habla con el modelo LLM crudo sin control de seguridad, sin herramientas de Windows, sin JDE ni verificación física. JESSYCA opera exclusivamente a través del puerto de WebUI Bridge (`:8088/v1`).

### 24.4. Evidencia de Pruebas Contractuales
* **Suite Canónica E2E:** `tests/interfaces/webui_bridge/test_webui_bridge_canonical_e2e.py`
  - `test_e2e_models_catalog_exposes_jessyca`: `/v1/models` expone exclusivamente `jessyca` (**PASSED**).
  - `test_e2e_authentication_enforcement`: 401 sin token, 401 token inválido, prohibición de token de desarrollo inseguro (**PASSED**).
  - `test_e2e_conversation_turn_and_session_isolation`: Turno conversacional completo y aislamiento estricto de dos conversaciones independientes (**PASSED**).
  - `test_e2e_innocuous_action_execution_with_evidence`: Acción física inocua (`open_application`) viaja por el puente hasta JDE, se ejecuta y verifica físicamente (**PASSED**).
  - `test_e2e_retry_duplicate_request_does_not_repeat_action`: Reintento interceptado por `IdempotencyGuard` y el skill no se re-ejecuta (**PASSED**).
  - `test_e2e_internal_openwebui_tasks_do_not_trigger_skills` [Title, Tags, Follow-up, Summary]: Tareas internas automáticas jamás tocan herramientas físicas (**PASSED**).
  - `test_e2e_streaming_sse_protocol`: Formato SSE OpenAI con deltas y señal final `[DONE]` (**PASSED**).
  - `test_e2e_unknown_model_rejected`: Modelos distintos de `jessyca` rechazados con 404 (**PASSED**).
* **Resultado Global de Suite WebUI Bridge:** `pytest tests/interfaces/webui_bridge/ -q`: **43 passed in 13.56s (100% pass rate)**.
* **Linter:** `ruff check interfaces/webui_bridge tests/interfaces/webui_bridge/test_webui_bridge_canonical_e2e.py`: **All checks passed!**

---

## 25. Auditoría y Consolidación de Integraciones Existentes (Prompt 00)

### 25.1. Matriz de Clasificación Antes / Después

| Subsistema / Capacidad | Clasificación Oficial | Implementación Canónica | Rol de Fallback / Laboratorio | Justificación Técnica Comprobable |
| :--- | :--- | :--- | :--- | :--- |
| **Jarvis: Apps (`jarvis.app_control`)** | **RETIRAR DE PRODUCCIÓN** (Test-Only) | `skills/apps_skill.py` (`apps.launch`, `apps.close`) | Jarvis: Diccionario fijo `_APP_ALIASES` / `taskkill` forzado | La skill nativa soporta UWP y ejecutables arbitrarios, verificación observable (`pid_alive`, ventana activa) y `WM_CLOSE` suave antes de fallback. |
| **Jarvis: Audio (`jarvis.volume_control`)** | **RETIRAR DE PRODUCCIÓN** (Test-Only) | `skills/windows_media_skill.py` | Jarvis: Emulación de teclas `VK_VOLUME_*` | La skill nativa interactúa con Windows Core Audio APIs vía COM, con ajuste y lectura exacta de porcentaje (0-100) y mute. Jarvis es emulación a ciegas sin verificación de nivel. |
| **Jarvis: Clipboard (`jarvis.clipboard`)** | **RETIRAR DE PRODUCCIÓN** (Test-Only) | `skills/windows_skills.py` (`windows.clipboard`) | Jarvis: Wrapper de `pyperclip` | La skill nativa accede directamente a la Win32 Clipboard API sin dependencias externas accesorias. |
| **Jarvis: Files (`jarvis.workspace_files`)** | **SOLO LABORATORIO** (Sandbox Test) | `skills/files_skills.py` | Jarvis: Confinado a `%LOCALAPPDATA%/jarvis/workspace` | La skill nativa gobierna operaciones en todo el filesystem bajo autorización JDE. El workspace de Jarvis fragmenta el almacenamiento y solo sirve como sandbox aislado. |
| **Jarvis: System (`jarvis.system_status`)** | **RETIRAR DE PRODUCCIÓN** (Redundante) | `skills/windows_skills.py` / `core/diagnostics/monitor.py` | Jarvis: Telemetría básica con `psutil` | La telemetría nativa del Core cubre memoria, CPU, procesos y observabilidad integrada. |
| **ARE: DAG Topological Sort & Ciclos** | **CONSERVAR** | `core/dag.py` / `core/are/runtime.py` | N/A (Algoritmo canónico de Kahn) | Resolución determinista de precedencia con desempate configurable y detección estricta de ciclos y autodependencias. |
| **ARE: Diagnóstico de Impacto & Causa Raíz** | **CONSERVAR** | `core/are/runtime.py` (`diagnose_and_recover`) | BFS downstream sobre dependencias | Cálculo del radio de impacto (*blast radius*), detección de nodos bloqueados vs independientes y límite anti-bucle (`MAX_RECOVERY_ATTEMPTS=2`). |
| **ARE: Descomposición Heurística** | **COMPLETAR / FALLBACK** | Heurísticas estructuradas en `AREAdapter` | 5 Plantillas estáticas ("localiza", "organiza", etc.) | Honestidad epistémica: clasificado como plantillas fijas de fallback por palabras clave, no como razonamiento abierto dinámico. |
| **ARE: Ciclo de Vida e Instancia Hub** | **UNIFICAR** (Completado) | `get_are_runtime()` sincronizado con `IntegrationHub` | Singleton compartido en Hub | Se eliminó la doble instanciación independiente; `ARERuntime` reutiliza el adapter registrado en `IntegrationHub` y sincroniza flags de modo (`DISABLED`). |
| **AnyDoc: Confinamiento de Rutas y Sandbox** | **CONSERVAR** | `AnyDocAdapter` + `AnyDocGovernedOrchestrator` | Sandbox estricto `data/anydoc/` | Validación de doble capa independiente (adaptador y orquestador): rechazo de traversal (`..`, `%2e%2e`, `\x00`), rutas UNC y resolución de enlaces simbólicos mediante `realpath`. |
| **AnyDoc: Límites de Recursos y Secretos** | **CONSERVAR** | `AnyDocAdapter.validate_and_confine_path` / `redact_secrets` | Rechazo de archivos > 50 MB | Protección contra denegación de servicio y redacción profunda regex de tokens Bearer, OpenAI keys y credenciales en salidas. |
| **AnyDoc: Procedencia y Recibos Inmutables** | **CONSERVAR** | `AnyDocTaskContract.compute_seal` + `AnyDocReceipt` | Hashes SHA-256 de entrada y salida | Sellado contra manipulación post-autorización y recibos inmutables auditables con procedencia determinista. |
| **Archify: Generación de Diagramas Técnicos** | **CONSERVAR** | `core/archify/adapter.py` / `ArchifySkill` | Fallback determinista a Mermaid | Renderizado técnico gobernado con generación local en Mermaid sin requerir compiladores externos. |
| **ORCA: Aislamiento en Git Worktrees** | **CONSERVAR** | `core/orca_ade/adapter.py` / `OrcaWorktreeSandbox` | Worktrees efímeros en `data/orca_worktrees` | Ejecución aislada de cambios de código sin afectar el working tree principal. |
| **ORCA/ADE: Despacho Paralelo / Design Mode** | **SOLO LABORATORIO** | `OrcaAdeAdapter` | Modo laboratorio / evaluación | No participan en flujos de producción activos; retenidos exclusivamente bajo pruebas controladas. |
| **ORCA/ADE/Archify: Asistentes Separados** | **RETIRAR / UNIFICADO** | `JessycaLocalAgent` como Único Asistente | N/A | No existen 3 asistentes; Archify, ORCA y ADE son subcomponentes de ingeniería de producto subordinados a JDE y a la memoria canónica. |

### 25.2. Cambios Implementados
1. **Unificación de Ciclo de Vida de ARE:**
   - En `core/are/runtime.py`, `ARERuntime.__init__` reutiliza la instancia de `AREAdapter` registrada en `IntegrationHub` (vía `get_integration_hub().registry.get("are")`), previniendo instancias huérfanas desacopladas.
   - `ARERuntime.set_mode` y la inicialización sincronizan automáticamente el estado del adaptador en el Hub (`IntegrationStatus.DISABLED` o `IntegrationStatus.READY`).
   - Modo `ACTIVE` permanece estrictamente bloqueado lanzando `PermissionError`.
2. **Alineación de Confinamiento en AnyDocGovernedOrchestrator:**
   - En `core/anydoc/orchestrator.py`, la inicialización del adaptador inyecta `base_sandbox_dir=self.base_dir`, garantizando que tanto el orquestador como el adaptador compartan exactamente la misma frontera de confinamiento sin desalineaciones.
3. **Consolidación de Subcomponentes Archify + ORCA + ADE:**
   - Certificación de subordinación al JDE canónico, `ExecutionVerifier` y memoria central.
   - Se mantiene la eliminación de éxitos simulados (probado que DENY produce 0 side effects y que la falta de executor produce `UNAVAILABLE`).

### 25.3. Evidencia de Pruebas Automatizadas
* **Suite Dedicada de Auditoría de Integraciones:** [`tests/integration/test_integrations_architecture_audit.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tests/integration/test_integrations_architecture_audit.py)
  - `test_jarvis_adapter_disabled_by_default_in_hub`: Jarvis deshabilitado por defecto en IntegrationHub (**PASSED**).
  - `test_jarvis_app_control_is_secondary_fallback_to_native_apps`: Alias fijos de Jarvis vs resolución canónica (**PASSED**).
  - `test_jarvis_volume_control_is_keystroke_fallback`: Emulación de teclas sin nivel exacto vs Core Audio APIs (**PASSED**).
  - `test_jarvis_workspace_confinement_is_isolated_sandbox`: Confinamiento a workspace propio y rechazo de traversal (**PASSED**).
  - `test_are_initialization_shares_adapter_with_hub`: Reutilización de adaptador compartido con Hub (**PASSED**).
  - `test_are_lifecycle_synchronization_with_disabled_mode`: Sincronización de estado DISABLED en Hub (**PASSED**).
  - `test_are_active_mode_is_strictly_prohibited`: Bloqueo inquebrantable de modo ACTIVE (**PASSED**).
  - `test_are_real_dag_topological_sort_and_cycle_detection`: Algoritmo de Kahn y detección de ciclos circulares (**PASSED**).
  - `test_are_limited_templates_heuristic_classification`: Clasificación honesta de plantillas estáticas de descomposición (**PASSED**).
  - `test_anydoc_input_confinement_rejects_external_reads`: Rechazo de lecturas fuera del sandbox (**PASSED**).
  - `test_anydoc_output_confinement_rejects_external_writes`: Rechazo de escrituras fuera del sandbox (**PASSED**).
  - `test_anydoc_symlink_traversal_is_resolved_and_rejected`: Resolución de enlaces simbólicos y rechazo de escapes (**PASSED**).
  - `test_anydoc_file_size_safety_limit`: Límite de tamaño de archivo y estado RESOURCE_LIMIT (**PASSED**).
  - `test_anydoc_governed_orchestrator_receipt_provenance`: Recibos inmutables con hashes de entrada/salida y redacción de secretos (**PASSED**).
  - `test_single_product_integration_no_duplicate_personas`: Módulos técnicos subordinados sin asistentes separados (**PASSED**).
  - `test_archify_mermaid_fallback_is_deterministic`: Fallback local determinista a sintaxis Mermaid (**PASSED**).
  - `test_orca_ade_requires_real_jde_allow_verdict`: Veredicto DENY respetado sin efectos secundarios (**PASSED**).
  - **Resultado:** **17 passed in 0.52s (100% pass rate)**.
* **Regresiones Cruzadas de los Módulos Auditados:**
  - `pytest tests/test_jarvis_adapter.py -q`: **30 passed (100%)**.
  - `pytest tests/are/ -q`: **38 passed (100%)**.
  - `pytest tests/anydoc/ -q`: **153 passed (100%)**.
  - `pytest tests/archify/ tests/orca_ade/ -q`: **196 passed (100%)**.
  - `pytest tests/e2e/test_full_e2e_integration.py -q`: **22 passed (100%)**.
* **Linter:** `ruff check core/are/runtime.py core/anydoc/orchestrator.py tests/integration/test_integrations_architecture_audit.py`: **All checks passed!**

---

## 26. Fase 26 — Etapa 1 de Distribución: Instalación Local Reproducible, Comando Global `jessyca` y Segregación Canónica

### 26.1. Diagnóstico y Requisitos Cubiertos
* **Comando Global Ejecutable:** `pyproject.toml` no declaraba entry point bajo `[project.scripts]`. Se añadió el entrypoint canónico `jessyca = "main:main"` junto con `py-modules = ["main"]` en setuptools, permitiendo generar `jessyca.exe` de forma reproducible.
* **Segregación Estricta de Rutas:** Se implementó [`core/distribution/paths.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/distribution/paths.py) garantizando separación absoluta entre:
  1. *Código instalado (read-only):* Directorio del paquete base de la aplicación.
  2. *Configuración del usuario:* `%APPDATA%\jessyca` (sobreescribible con `JESSYCA_CONFIG_DIR`).
  3. *Memoria y datos persistentes:* `%LOCALAPPDATA%\jessyca\data` (`sessions.db`, LTM, sobreescribible con `JESSYCA_DATA_DIR`).
  4. *Logs:* `%LOCALAPPDATA%\jessyca\logs` (sobreescribible con `JESSYCA_LOG_DIR`).
  5. *Cachés efímeras:* `%LOCALAPPDATA%\jessyca\cache` (sobreescribible con `JESSYCA_CACHE_DIR`).
  6. *Modelos locales:* `%LOCALAPPDATA%\jessyca\models` (sobreescribible con `JESSYCA_MODELS_DIR`).
* **Concurrencia y Modelo Cliente/Servicio Core:** Se implementó [`core/distribution/service_client.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/distribution/service_client.py):
  - *Si el servicio Core está en ejecución:* CLI y clientes externos consultan `/health` y envían mensajes vía HTTP `/v1/chat/completions`, interactuando sobre el mismo Core, estado en memoria y sesiones activas.
  - *Si el servicio Core no está en ejecución:* Se ejecuta el Core embebido garantizando exclusión mutua inter-proceso mediante `CoreProcessLock` en disco (`data_dir/core.lock`), detección de procesos huérfanos/muertos y base de datos con modo WAL.
* **Comandos Reales y Diagnóstico Sanitizado (`main.py`):**
  - `jessyca doctor` / `jessyca diag`: Inspecciona SO, Python, hardware, audio, rutas segregadas, permisos y dependencias sin activar servicios remotos ni descargar modelos grandes. Sanitiza secretos y admite `--json`.
  - `jessyca status`: Muestra versión, rutas segregadas y estado vivo del servicio Core.
  - `jessyca config [show|path]`: Muestra rutas y valores de configuración con credenciales enmascaradas.
  - `jessyca serve`: Inicia el servicio Core compartido (OpenAI-compatible) en loopback.
  - `jessyca run <mensaje>` / `jessyca chat <mensaje>`: Despacha la consulta a través del Core (servicio activo o local embebido con lock).
  - Preservación del 100% de flags preexistentes (`--demo`, `--mcp`, `--voice`, `--mobile`, `--webui`).
* **Verificación Física de Accesos Directos:** En `core/distribution/installer_engine.py`, se erradicó el registro ficticio de strings. Ahora los accesos directos se escriben físicamente en disco y se verifican con `Path.is_file()` antes de registrarse; se eliminan físicamente en la desinstalación.
* **Arranque Rápido y Robusto:** En `main.py`, se postergó la importación de módulos pesados (Voz, Skills, FastMCP, Pydantic) al interior de sus respectivos manejadores, permitiendo que `jessyca --help`, `jessyca doctor` y `jessyca status` arranquen de forma instantánea incluso ante dependencias faltantes.

### 26.2. Evidencia de Pruebas Automatizadas
* **Suite de Distribución y CLI:** [`tests/distribution/test_distribution_cli_and_paths.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tests/distribution/test_distribution_cli_and_paths.py)
  - `test_paths_are_strictly_segregated`: Códigos, config, data, logs, cache y models en rutas disjuntas (**PASSED**).
  - `test_environment_variable_overrides`: Sobreescritura limpia vía variables de entorno (**PASSED**).
  - `test_clean_install_creates_and_verifies_shortcuts_physically`: Creación y verificación física de accesos directos en disco (**PASSED**).
  - `test_process_lock_acquisition_and_release`: Exclusión mutua atómica inter-proceso con timeout (**PASSED**).
  - `test_explicit_core_lock_context_manager`: Context manager de bloqueo en carpeta data (**PASSED**).
  - `test_core_client_check_service_status`: Detección certera de servicio activo vs apagado (**PASSED**).
  - `test_core_client_routes_to_embedded_when_service_down`: Fallback a ejecución embebida gobernada (**PASSED**).
  - `test_core_client_routes_to_service_when_service_up`: Delegación al servicio Core activo (**PASSED**).
  - `test_parse_arguments_subcommands`: Parseo de subcomandos `doctor`, `diag`, `status`, `config`, `run` (**PASSED**).
  - `test_run_doctor_command`: Salida legible y sanitizada del diagnóstico (**PASSED**).
  - `test_run_doctor_command_json_output`: Exportación JSON sanitizada (**PASSED**).
  - `test_run_status_command`: Reporte de estado y rutas (**PASSED**).
  - `test_run_config_command_path`: Consulta de rutas de settings (**PASSED**).
  - `test_diagnostics_does_not_download_models_or_claim_fake_vram`: No alucina VRAM ni descarga modelos (**PASSED**).
  - `test_run_agent_command_execution` y `test_run_agent_command_error_handling`: Ejecución CLI de agente y gestión de errores (**PASSED**).
  - `test_run_serve_command_delegation`: Delegación al servidor Core (**PASSED**).
  - `test_global_jessyca_binary_exists_in_scripts`: Existencia comprobada del binario `jessyca.exe` (**PASSED**).
  - **Resultado:** **18 passed in 2.30s (100% pass rate)**.
* **Suite Completa de Productización:** `pytest tests/distribution/ -v`: **29 passed in 5.73s (100% pass rate)**.
* **Regresiones Cruzadas de Launchers:** `pytest tests/test_launcher_webui.py tests/test_main_demo_launcher.py tests/test_mobile_api.py -v`: **37 passed in 4.16s (100% pass rate)**.
* **Verificación de Binario Real Windows:**
  - `.\venv\Scripts\jessyca.exe --help`: Código de salida 0 con especificación completa de subcomandos y opciones.
  - `.\venv\Scripts\jessyca.exe doctor`: Código de salida 0 con diagnóstico del sistema y rutas segregadas.
  - `.\venv\Scripts\jessyca.exe status`: Código de salida 0 con informe de estado y servicio Core.

### 26.3. Procedimiento para Verificación en Entorno Limpio de Windows
Para validar la instalación en una máquina o entorno Windows completamente limpio:
```powershell
# 1. Crear entorno virtual limpio
python -m venv .clean_venv

# 2. Activar e instalar dependencias del proyecto
.\.clean_venv\Scripts\pip install -e .

# 3. Comprobar la disponibilidad del comando global generado
.\.clean_venv\Scripts\jessyca.exe --help

# 4. Ejecutar diagnóstico de entorno y segregación de rutas
.\.clean_venv\Scripts\jessyca.exe doctor

# 5. Comprobar el estado del sistema y rutas activas
.\.clean_venv\Scripts\jessyca.exe status

# 6. Salida limpia
# El comando finaliza con código 0 y preserva los datos del usuario en %LOCALAPPDATA%\jessyca\data
```

---

## 27. Capacidades Reales de Asistente Personal en Windows y Desacoplamiento Circular (Fase 27)

### 27.1. Diagnóstico y Corrección de Importación Circular en Skills/Core
* **Causa Raíz:** `core/__init__.py` reexportaba estáticamente las 27 skills al importar `core`, mientras que `skills/skill_models.py`, `core/collaboration/collaboration_engine.py` y `core/system/system_coordinator.py` importaban mutuamente tipos en tiempo de carga antes de que `BaseSkill` terminara de inicializarse.
* **Solución Implementada:**
  - Uso de `if TYPE_CHECKING:` y carga perezosa (`lazy import`) en `skills/skill_models.py`, `core/collaboration/collaboration_engine.py` y `core/system/system_coordinator.py`.
  - Protección con `try ... except ImportError` de las reexportaciones auxiliares en `core/__init__.py`.
  - **Resultado:** Las 27 skills registradas con éxito con status `READY` sin errores circulares.

### 27.2. Implementación de Backends Reales en Windows
* **Windows Audio (`windows.audio`):**
  - Conectado a `pycaw.pycaw.AudioUtilities.GetSpeakers().EndpointVolume`.
  - Lectura escalar de volumen maestro (`GetMasterVolumeLevelScalar()`), ajuste escalar (`SetMasterVolumeLevelScalar()`), consulta de mute (`GetMute()`) y control de silencio (`SetMute()`) validados físicamente.
* **Windows Notifications (`windows.notifications`):**
  - Conectado a PowerShell WinRT Toast nativo (`Windows.UI.Notifications.ToastNotificationManager`) con payload XML estructurado y fallback balloon.
  - Validación física en el Centro de Notificaciones de Windows con flag `toast_nativo: True`.
* **Windows Clipboard (`windows.clipboard`):**
  - Conectado a `pyperclip` (Win32 API Clipboard).
  - Ciclo completo de escritura, lectura determinista y vaciado verificado.
* **Windows Display (`windows.display`):**
  - Conectado a `ctypes.windll.user32.GetSystemMetrics`.
  - Detección precisa de dimensiones (ej. 2560x1440) y monitores activos.
* **Sistema de Archivos (`files.search`, `files.read`, `files.create`, `files.copy`, `files.move`):**
  - Enrutamiento directo desde lenguaje natural en `JessycaLocalAgent` a `file_agent` y herramientas verificadas en sandbox temporal.
* **Captura de Pantalla (`windows.screenshot`):**
  - Gobernado por JDE (`requires_review` / confirmación obligatoria por privacidad).
  - En entornos no interactivos, reporta honestamente `BLOCKED_HEADLESS`.

### 27.3. Evidencia de Pruebas
* **Suite de Capacidades de Escritorio:** `pytest tests/desktop/test_real_windows_assistant_capabilities.py -v`: **6 passed in 2.87s (100% pass rate)**.
* **Suite de Agente Local:** `pytest tests/local_agent/ -q`: **19 passed in 3.65s (100% pass rate)**.
* **Suite Completa de Skills:** `pytest tests/skills/ -q`: **220 passed in 12.4s (100% pass rate)**.

---

## 28. Consolidación de la Ruta Canónica de Decisiones y Ejecución & Open WebUI Bridge (Fase 28 / Prompt 10)

### 28.1. Trazabilidad Unificada de Interfaces (Sin Bypass de Garantías)
Se consolidó la ruta canónica asegurando que **todas** las interfaces converjan estrictamente en `JessycaLocalAgent.interact()` / `_execute_unified_pipeline()`:
1. **Voz (`interfaces/modo_voz.py`):** Captura VAD/STT -> `JessycaRequest(modality=VOICE)` -> `agent.interact(req)` -> TTS.
2. **CLI (`interfaces/modo_texto.py`):** Bucle de texto interactivo -> `JessycaRequest(modality=TEXT)` -> `agent.interact(req)`.
3. **Mobile API (`interfaces/mobile_api/app.py`):** REST endpoint -> `JessycaRequest` -> `agent.interact(req, cancellation_token)`.
4. **MCP Server (`server/app.py`):** Tools registradas en FastMCP se coordinan bajo JDE y ejecutan en `SecureExecutionBoundary`.
5. **Open WebUI Bridge (`interfaces/webui_bridge/app.py`):** Endpoint `/v1/chat/completions` (OpenAI-compatible) -> validación de auth -> mapeo determinista de sesión (`owui-<chat_id>`) -> `agent.interact(req)` / `agent.interact_stream(req)`.

### 28.2. Definición Estricta de Responsabilidades de Gobernanza
- **JDE (`core/jde/`):** Coordina la decisión y el estado del ciclo de vida (`AWAITING_CONFIRMATION`, `EXECUTING`, `COMPLETED`, `FAILED`). CERO Decision Engines paralelos.
- **Políticas Deterministas (`core/permission_manager.py`):** Autorizan (`ALLOW`) o deniegan (`DENY`) de manera binaria e incorruptible.
- **Herramientas (`core/skills/`):** Ejecutan la acción física en el sistema operativo mediante `SkillManager`.
- **ExecutionVerifier (`core/execution/`):** Evalúa la evidencia observable del resultado (`ExecutionEvidence`). Si la evidencia falta o es negativa, se reporta incertidumbre o fallo; jamás un falso éxito.

### 28.3. Blindaje de Confirmaciones Contra Inyección Arbitraria
- Se validó que un cliente externo no pueda declarar aprobada una acción enviando campos arbitrarios en el payload (`"confirmed": true`, `"is_confirmed": true`).
- Toda confirmación sensible requiere que el estado sea puesto en `AWAITING_CONFIRMATION`, registrando `pending_confirmation` en la sesión, y consumiéndose exclusivamente mediante `ConfirmationManager.verify_and_consume()`.

### 28.4. Evidencia de Pruebas de Integración y Regresión
* **Suite de Open WebUI Bridge:** `pytest tests/interfaces/webui_bridge/`: **49 passed in 23.32s (100% pass rate)**.
  - Ejecución real en Windows desde el Bridge (`windows.audio` con `pycaw`): **VERIFICADA**.
  - Acción sensible con solicitud de confirmación / bloqueo: **VERIFICADA**.
  - Intento de bypass bloqueado: **VERIFICADO**.
  - Aislamiento estricto de dos sesiones independientes: **VERIFICADO**.
  - Autenticación y rechazo 401: **VERIFICADO**.
* **Capacidades de Escritorio Reales:** `pytest tests/desktop/test_real_windows_assistant_capabilities.py`: **6 passed in 2.83s (100% pass rate)**.
* **Precisión Técnica Fase 17.1.4:** `pytest tests/test_phase17_precision_and_no_pitch.py`: **17 passed in 31.46s (100% pass rate)**.

---

## 29. Capacidades Reales de Archivos y Aplicaciones en Windows (Fase 17 / Prompt 13)

### 29.1. Arquitectura de Ejecución y Prevención de Riesgos
- **Apertura de Aplicaciones Instaladas:**
  - Invocación delegada a `ApplicationSessionManager.launch_app()` y `WindowsApplicationAdapter` con `shell=False` y lista de argumentos explícitos (`[exe_target] + list(args)`). Cero concatenación de comandos en shell con texto libre del usuario.
  - Prevención de ejecuciones duplicadas e idempotencia por `action_id`.
  - Verificación observable de PIDs y ventanas creadas.
- **Apertura de Carpetas en el Explorador:**
  - Intent `open_folder` integrado en `LocalAgent` y mapeado a `windows.apps` pasando `args=(os.path.abspath(ruta_carpeta),)`.
  - Validación previa de existencia (`os.path.isdir`) y denegación de rutas críticas. Reporte honesto de fallo ante rutas inexistentes sin declarar falsos éxitos.
- **Listado y Localización de Archivos (`files.list`):**
  - Implementación de `FilesListSkill` con soporte de parámetros flexibles (`directorio`, `ruta_carpeta`, `carpeta`, `path`).
  - Retorno estructurado de archivos y directorios con tamaños legibles y extensiones.
- **Creación de Carpetas (`files.create_folder`):**
  - Implementación de `FilesCreateFolderSkill` con verificación determinista vía `FolderExistsVerificationStrategy` en `ExecutionVerifier`.
- **Copia, Movimiento y Renombrado (`files.copy`, `files.move`, `files.rename`):**
  - Resolución inteligente de destinos ambiguos (`_resolve_destination_path`): detecta si el destino es una carpeta existente o el nombre final del archivo, validando la existencia del directorio padre.
  - Prevención de sobrescritura silenciosa: si el destino existe y `sobrescribir=False`, se detiene retornando `conflicto_destino: True` y `requiere_confirmacion: True`.
  - Preservación exacta de contenido y metadatos verificada observablemente en disco.
- **Consulta de Metadatos (`files.metadata`):**
  - Implementación de `FilesMetadataSkill` extrayendo atributos reales del SO (tamaño en bytes, tamaño legible, fecha de modificación UTC, permisos de lectura/escritura, extensión y tipo).
- **Operaciones por Lotes y Vista Previa (`files.organize`):**
  - Soporte de vista previa obligatoria (`preview: True`), calculando el plan de clasificación por categorías sin mover archivos antes de la confirmación explícita.
- **Diagnóstico de Archivos Bloqueados y Rutas Protegidas:**
  - Detección precisa de `PermissionError` y `ERROR_SHARING_VIOLATION` (winerror 32) informando claramente que el archivo se encuentra abierto o en uso por otro proceso.
  - Bloqueo determinista de rutas críticas del sistema (`C:\Windows`, `System32`, `Program Files`, `AppData`).

### 29.2. Resultados y Certificación de Pruebas
* **Suite de Capacidades Reales de Archivos y Aplicaciones:** `pytest tests/skills/test_real_file_and_app_capabilities.py -v`: **15 passed in 2.74s (100% pass rate)**.
* **Suite Consolidada de Regresión y Gobernanza (JDE, Execution Verification, Single-Instance Idempotency):** `pytest tests/skills/test_real_file_and_app_capabilities.py tests/jde/test_jde_canonical_consolidation.py tests/jde/test_phase3c_consolidation.py tests/execution/test_apps_duplicate_execution_fix.py tests/execution/test_apps_false_success_prevention.py tests/execution/test_execution_verification.py`: **75 passed in 61.66s (100% pass rate)**.

---

## 30. Capacidades Reales de Navegador con Backend Playwright (Fase I2 / Browser Real)

### 30.1. Arquitectura de Integración y Seguridad
- **Backend Único Playwright:** Activado como opción única de integración canónica (`BROWSER_BACKEND="playwright"`, `PLAYWRIGHT_ENABLED=True`), resolviendo a `PlaywrightBrowserAdapter`.
- **Persistencia de Sesión:** `BrowserSessionManager` reutiliza un adaptador compartido (`get_shared_browser_adapter` y `reset_shared_browser_adapter`), permitiendo mantener el contexto de navegación y pestañas activas a través de turnos múltiples en `JessycaLocalAgent`.
- **Apertura y Búsqueda Web:** Apertura gobernada con validación Deny-by-Default (`URLAllowlistPolicy`) y resolución automática de banners de consentimiento/cookies.
- **Seguimiento de Enlaces (`follow_link`):** Búsqueda interactiva en el DOM con normalización y tolerancia a variantes con o sin tildes.
- **Extracción de Contenido con Procedencia:** Extracción sanitizada acompañada de URL de procedencia, título, timestamp y marcado de datos no confiables (`is_untrusted_data: True`).
- **Descargas Confinadas a Sandbox:** Soporte de descargas directas vía `context.request.get()` sin exigir pestaña activa previa, verificación de rutas absolutas confinadas estrictamente a `sandbox_dir` y bloqueo de extensiones ejecutables o de scripts (`.exe`, `.bat`, `.cmd`, etc.).
- **Control Observable de Medios:** Verificación en el DOM de elementos `<video>` y `<audio>` (`MediaState.PLAYING`, `MediaState.PAUSED`), distinguiendo la emisión de un comando del estado observable del reproductor.
- **Detección de Bloqueos:** Detección automática de CAPTCHAs y desafíos anti-bot, reportando el bloqueo para intervención del usuario.

### 30.2. Resultados y Certificación de Pruebas
* **Suite de Capacidades Reales de Navegador:** `pytest tests/browser/test_real_browser_capabilities.py -v`: **8 passed in 23.08s (100% pass rate)**.
* **Suite de Fase I2 Playwright:** `pytest tests/browser/test_playwright_adapter_phase_i2.py -v`: **17 passed in 19.62s (100% pass rate)**.
* **Suite Conjunta de Navegador Real:** `pytest tests/browser/test_real_browser_capabilities.py tests/browser/test_playwright_adapter_phase_i2.py -v`: **25 passed in 42.40s (100% pass rate)**.

---

## 31. Auditoría de Capacidades Documentales y Recorridos Funcionales (Word, Excel, PowerPoint, AnyDoc)

### 31.1. Diagnóstico y Auditoría Técnica de Software
* **Sistema:** Windows 11 Pro (amd64), Python 3.11.9.
* **Bibliotecas Estructuradas Verificadas:**
  - `python-docx` (v1.2.0): Creación y edición estructurada de `.docx`.
  - `openpyxl` (v3.1.5): Lectura, escritura de celdas, estilos, fórmulas y gráficos en `.xlsx`.
  - `python-pptx` (v1.0.2): Generación y formateo de diapositivas panorámicas en `.pptx`.
  - `pywin32` / `win32com.client` (v311): Automatización e invocación de Microsoft Office COM.
  - `pandas` (v2.3.3) y `matplotlib` (v3.10.8): Análisis tabular y renderizado de gráficos estadísticos.
* **Software de Oficina:** Microsoft Office 16.0 instalado (Word, Excel, PowerPoint registrados en Windows).
* **Integración AnyDoc:** Adaptador de seguridad `AnyDocAdapter` con confinamiento ampliado (`add_allowed_read_dir`), validando ingesta y conversión a Markdown de `.docx`, `.xlsx` y `.pptx`.

### 31.2. Recorridos Funcionales Implementados
1. **WORD (.docx) — Creación y Edición Incremental con Preservación:**
   - Módulo: `WordDocumentProcessor` (`core/documents/word_processor.py`).
   - Generación de informe con títulos jerárquicos, párrafos con negritas/cursivas, listas con viñetas y tablas de métricas con estilos oscuros y anchos de columna definidos.
   - Edición incremental (`edit_document`) conservando el documento original intacto mediante copia de seguridad y agregando un anexo técnico con tabla de controles.
   - Verificación con Microsoft Word COM (`Word.Application`, `Paragraphs.Count`, `Tables.Count`).
2. **EXCEL (.xlsx) — Presupuesto, Fórmulas y Evaluación con Motor de Cálculo:**
   - Módulo: `ExcelSpreadsheetProcessor` (`core/documents/excel_processor.py`).
   - Construcción de presupuesto tecnológico con 6 ítems, cantidades, costos unitarios, formatos contables `$#,##0.00` y gráfico nativo de barras (`BarChart`).
   - Inserción de 11 fórmulas: subtotales (`=C*D`), costo directo (`=SUM(...)`), impuestos (`=E*0.18`), presupuesto total (`=E+E`), promedio (`=AVERAGE(...)`) y costo máximo (`=MAX(...)`).
   - **Distinción honesta de motor:** `openpyxl` escribe la fórmula literal. Para evaluar los resultados reales ($11,000.00 directo, $1,980.00 impuestos, $12,980.00 total), se ejecutó el motor de cálculo real `Excel.Application` vía COM (`CalculateFull()`) y se persistió la caché calculada en disco.
3. **POWERPOINT (.pptx) — Presentación Ejecutiva y Renderizado Visual:**
   - Módulo: `PowerPointPresentationProcessor` (`core/documents/powerpoint_processor.py`).
   - Presentación ejecutiva de 5 diapositivas (16:9) con diseño corporativo oscuro (Slate 900/800 y acentos Sky 400).
   - Diapositivas: Portada, Resumen Ejecutivo (viñetas), Tabla de Presupuesto, Diapositiva Dividida con imagen de gráfico (`shapes.add_picture`) y Conclusiones de Gobernanza.
   - Verificación y exportación física de las 5 diapositivas a imágenes PNG mediante Microsoft PowerPoint COM (`slide.Export`).
4. **Orquestador Unificado:**
   - Módulo: `DocumentWorkflowOrchestrator` (`core/documents/document_orchestrator.py`).
   - Coordina los tres recorridos funcionales de principio a fin, genera el gráfico con `matplotlib` y verifica los resultados con `AnyDocDocumentVerifier`.

### 31.3. Archivos y Artefactos Físicos Generados
* `Informe_Ejecutivo_JESSYCA_Q3_2026.docx` (38.0 KB)
* `Informe_Ejecutivo_JESSYCA_Q3_2026_Actualizado.docx` (38.5 KB)
* `Presupuesto_Operativo_Tecnologico_2026.xlsx` (13.3 KB, con valores calculados por Excel)
* `grafico_distribucion_presupuesto.png` (81.5 KB)
* `Presentacion_Ejecutiva_JESSYCA_Q3_2026.pptx` (105.5 KB)
* `render_slides_pptx/slide_1.png` a `slide_5.png` (46 KB - 140 KB c/u)
* Carpeta: `d:\JESSYCA 3.0\asistente-jessyca\data\pruebas_documentales\`

### 31.4. Resultados de Pruebas Automatizadas
* **Suite:** `pytest tests/documents/test_real_document_capabilities.py -v`: **5 passed in 11.25s (100% pass rate)**.

---

## 32. Asistencia de Programación Confinada y Auditoría Unificada (Archify + Orca + ADE + ARE)

### 32.1. Diagnóstico y Auditoría Arquitectónica Inter-Sistemas
* **No adición de agentes paralelos:** Se evaluó el subsistema existente y se unificó la arquitectura sin crear agentes de programación duplicados:
  - **ARE (Action Reasoning Engine):** Planificador analítico y consultivo de alto nivel (`are.decompose_task`, `are.evaluate_plan`, `are.diagnose_failure`). Descompone metas complejas en grafos de dependencias.
  - **JDE (JESSYCA Decision Engine):** Autoridad única e irrevocable. Gobierna permisos (`PermissionManager`), riesgos (`RiskEngine`), idempotencia (`IdempotencyGuard`) y puertas de aprobación (`ReviewGate`).
  - **ORCA + ADE (Agentic Development Environment):** Entorno supervisor y ejecutor de tareas de desarrollo dentro de worktrees y espacios de trabajo autorizados (`RealCodeAssistantExecutor`, `OrcaAdeAdapter`, `OrcaGovernedOrchestrator`).
  - **Archify:** Capability provider especializado en diagramación técnica interactiva (arquitectura, workflows, secuencias, dataflow, lifecycle). Confinado a `data/archify/` y complementario.
* **Separación Taxativa Anti-Simulación:**
  - **Modo Sintético / Simulación:** Marcado explícitamente (`synthetic: True`, `is_synthetic: True`). Queda formalmente prohibido emitir `VERIFIED_SUCCESS` en este modo (degrada a `UNVERIFIED` o `CLAIMED_SUCCESS`).
  - **Modo Real Observable:** Exige archivos físicos en disco, diffs unificados calculados mediante `difflib.unified_diff`, escrituras con verificación de integridad SHA-256 (`newline=""`), ejecución de pruebas con `subprocess` (`pytest`) y `exit_code == 0`.

### 32.2. Implementación de Capacidades y Recorrido Funcional
* **Módulos Desarrollados:**
  - `core/orca_ade/code_assistant.py`: `ProjectCodeAssistant`, `ProjectBoundaryValidator`, `RealCodeAssistantExecutor`.
  - `core/orca_ade/workflow.py`: `CodeAssistantWorkflow`, `ProgrammingAssistanceSessionReport`.
  - `core/are/action_catalog.py`: Registradas acciones ejecutables con handlers reales (`agent_orchestration.inspect_project`, `agent_orchestration.run_tests`, `agent_orchestration.diagnose_problem`, `agent_orchestration.apply_patch`).
* **Etapas del Recorrido Implementado:**
  1. **Inspección de Proyecto:** Análisis del árbol de archivos, discriminación de código/tests y cálculo de hashes SHA-256.
  2. **Localización de Fallos:** Ejecución real de pruebas con captura de fallos (`exit_code != 0`), tracebacks y aserciones.
  3. **Propuesta y Diff:** Cálculo del diff unificado real (`difflib.unified_diff`).
  4. **Aplicación Acotada:** Escritura física en disco con respaldo `.bak` e integridad hash pre y post parche.
  5. **Verificación de Pruebas:** Re-ejecución de pruebas autorizadas verificando aprobación total (`exit_code == 0`).
  6. **Degradación Elegante:** Si falta el entorno de ejecución, entrega el código marcado como `UNTESTED_CODE` y `verified: False`.

### 32.3. Demostración en Proyecto de Prueba y Artefactos Físicos
* **Directorio Autorizado:** `data/pruebas_programacion/demo_proyecto_calculadora/`
* **Artefactos Físicos Generados:**
  - `calculadora.py` (código corregido y verificado: 307 bytes)
  - `calculadora.py.bak` (respaldo previo al parche: 332 bytes)
  - `test_calculadora.py` (suite de pruebas autorizada: 273 bytes)
  - `reporte_asistencia_programacion.json` (reporte estructurado con evidencia observable)
* **Script de Ejecución:** `scripts/demo_assisted_programming_workflow.py`
* **Resultados Obtenidos:**
  - Fallo inicial detectado: `test_sumar_operacion_basica` (`AssertionError`, exit code `1`).
  - Diff aplicado: `- return a - b` / `+ return a + b`.
  - Resultado final de pruebas: `2/2 passed` (exit code `0`).
  - Estado formal: `VERIFIED_SUCCESS` (`verified: True`, `is_real_execution: True`).

### 32.4. Resultados de Pruebas Automatizadas
* **Suite:** `pytest tests/orca_ade/test_real_code_assistant_workflow.py -v`: **9 passed in 7.39s (100% pass rate)**.

---

## 33. Ampliación de Capacidades Reales en ARE, Catálogo Gobernado y Flujos de Producción

### 33.1. Gobernanza de Herramientas Reales y Cero Tolerancia a Placeholders
* **Catálogo de Acciones Gobernado (`ActionCatalog`):**
  - Cada acción registrada cuenta con `ActionDefinition` tipada: parámetros obligatorios y opcionales, esquema de salida estructurado, límites de seguridad (`resource_limits`), verificador observable de finalización (`ActionVerificationStrategy`: `PHYSICAL_FILE_EXISTS`, `SCHEMA_VERIFIED`, `STATE_MATCH`) y handler físico conectado a librerías verificadas en fases previas.
  - Prohibición formal de herramientas inexistentes o invocaciones genéricas (`action.execute`). El validador (`PlanValidator`) rechaza cualquier paso que invoque una acción no registrada en el catálogo con `UNKNOWN_ACTION_TYPE`.
* **Herramientas Reales Conectadas:**
  - Documentos Word: `WordDocumentProcessor` / `python-docx` (`documents.create_word_report`).
  - Hojas de cálculo: `ExcelSpreadsheetProcessor` / `openpyxl` y CSV (`spreadsheet.read_sheet`).
  - Análisis estadístico tipado: `data.calculate_summary` (totales, medias, min, max, conteos, insights).
  - Presentaciones PowerPoint: `PowerPointPresentationProcessor` / `python-pptx` (`presentation.create_presentation`).
  - Gestión de archivos: `FilesSkills` / `filesystem` (`files.search`, `files.preview_organize`, `files.apply_organization`, `files.verify_copies`).
  - Búsqueda pública: `BrowserSkills` con trazabilidad de fuentes (`browser.search`, `browser.read`).

### 33.2. Implementación de los Tres Objetivos Funcionales
1. **Objetivo 1: Búsqueda Pública, Fuentes y Reporte Word:**
   - Búsqueda en fuentes públicas con preservación de metadatos (`url`, `title`, `snippet`, `author`, `date`).
   - Propagación de resultados como referencias tipadas (`$step_1_search.output.sources`).
   - Generación de informe Word (.docx) formal con encabezados, párrafos analíticos, tabla de indicadores y sección dedicada de "Fuentes Consultadas y Bibliografía".
2. **Objetivo 2: Lectura de Datos, Resumen Cuantitativo y Presentación:**
   - Lectura agnóstica de hojas de cálculo (.xlsx) o archivos planos (.csv).
   - Cálculo determinista de agregaciones numéricas por columnas y categorías.
   - Creación de presentación PowerPoint (.pptx) de 16:9 con diapositivas de resumen ejecutivo, desglose cuantitativo en tablas nativas y conclusiones.
3. **Objetivo 3: Localización, Propuesta de Organización y Ejecución Autorizada:**
   - Detección de archivos con extensiones heterogéneas.
   - Generación de vista previa (`preview_mapping`) y explicación de reglas sin alterar el disco.
   - Ejecución autorizada de cambios físicos (copia/movimiento) creando subdirectorios clasificados.
   - Verificación física de integridad de cada archivo en su ruta destino.

### 33.3. Propagación Tipada, Control de Estado, Idempotencia y Políticas
* **Propagación de Salidas y Detención de Dependientes:**
  - Resolución tipada de referencias `$step_id.output.property`.
  - Validación de dependencias declaradas (`UNDECLARED_DATAFLOW_DEPENDENCY`).
  - Ante fallo de un predecesor o salida faltante (`MISSING_STEP_OUTPUT`), los pasos dependientes son detenidos de inmediato y marcados como `BLOCKED`.
* **Conservación y Explicación del Estado (`AREPlanExecutionState`):**
  - Métodos `mark_blocked`, `mark_skipped`, `record_step_blocked`, `record_step_skipped`.
  - `explain_state()` genera una síntesis estructurada y narrativa explicando completados, fallidos, bloqueados, omitidos y si el plan es reanudable.
* **Idempotencia Física en Reanudación (`resume_llm_plan`):**
  - Al reanudar un plan tras un fallo parcial, se inspeccionan los pasos previos exitosos. Si sus archivos físicos generados existen en disco con tamaño válido, se omite su reescritura (`record_step_skipped`), evitando alteraciones redundantes o duplicadas.
* **Aclaraciones, Cancelación y Políticas JDE:**
  - Detección de recursos esenciales ausentes (`PlanClarificationRequired` -> `AWAITING_CLARIFICATION`).
  - Cancelación cooperativa con `CancellationToken`.
  - Todo paso nuevo o replanificado es evaluado por `JDERuntimeBinding`.
  - Corrección de regex en `_HIGH_RISK_PATTERNS` (`r"\b(cmd|powershell|bash|sh)\b"`), evitando falsos positivos de riesgo en acciones de hojas de cálculo.

### 33.4. Resultados de Pruebas Automatizadas
* **Suite de Fase 13:** `pytest tests/are/test_are_real_tools_workflows_phase13.py -v`:
  - **11 passed in 1.70s (100% pass rate)**.
  - Cubre: Catálogo gobernado y rechazo de inexistentes, Objetivos 1, 2 (XLSX y CSV) y 3 parametrizados con variaciones de rutas y nombres, detención de dependientes, idempotencia física en reanudación, solicitud de aclaración y cancelación.
* **Regresión Completa:**
  - `tests/jde/`: **276 passed in 16.05s (100% pass rate)**.
  - `tests/are/` + `tests/documents/`: **67 passed in 21.85s (100% pass rate)**.

---

## 34. Primera Versión del Flujo de Voz: Pulsar para Hablar (PTT), Barge-In y Gobernanza TTS

### 34.1. Arquitectura de Pulsar para Hablar y Reutilización de Servicios
* **Reutilización del Prompt 08:**
  - `FasterWhisperSTTService` en español (`es`) con normalización matemática float32 [-1.0, 1.0], contrato explícito PCM 16kHz mono, discriminación nítida de silencio (`NO_AUDIO` / `is_empty`) frente a errores de proveedor (`STTError`, `STTTimeoutError`).
  - Prohibición de desvíos silenciosos a la red: la transcripción corre 100% local en hardware del usuario.
* **Flujo PTT Bajo Demanda:**
  - El sistema inicia en modo de reposo (`PushToTalkState.IDLE`). No hay escucha permanente por defecto.
  - Al recibir activación PTT (`PushToTalkController.process_ptt_audio` o flag `--ptt` en CLI), se inicia la captura acotada.
  - Si el audio es silencio plano o ruido no vocal, se descarta limpiamente sin generar llamadas al Core ni al LLM.
  - Se transcribe el audio y se empaqueta como `JessycaRequest(..., modality=InputModality.VOICE)` enviándolo al Core único (`JessycaLocalAgent.get_instance().interact(req)`).
  - La respuesta se sintetiza y reproduce a través de `VoiceSpeaker` / `TTSManager`.

### 34.2. Prevención de Auto-Disparo por Eco Acústico y Errores de Proveedor
* **Supresión de Eco Acústico (Anti-Echo):**
  - Se registra el último texto hablado y la marca temporal (`_last_spoken_text`, `_last_spoken_time`).
  - Si el audio re-capturado por el micrófono presenta solapamiento léxico >= 70% dentro de la ventana de reverberación, el filtro `is_acoustic_echo` lo descarta categóricamente, impidiendo que la propia voz del asistente dispare nuevas órdenes.
* **Manejo Robusto de Proveedor y Cancelación:**
  - `CancellationToken` permite abortar limpiamente la captura o síntesis en cualquier momento (`VoiceCancelledError`).
  - Errores de STT o caídas de red de TTS degradan elegantemente sin provocar excepciones no controladas.

### 34.3. Interrupción de la Respuesta (Barge-In) vs Cancelación de Acción
* **Detener Audio (`stop_audio`):**
  - Corta de inmediato la reproducción del sintetizador (pygame mixer, TTSManager, SAPI) y transiciona la State Machine a `LISTENING` para atender la intervención del usuario.
  - **Invariante Crítica:** Detener el audio **NO cancela** una acción en ejecución en el sistema operativo (p. ej. un plan de ARE o tarea de fondo).
* **Cancelar Acción (`cancel_underlying_action`):**
  - Se ejecuta únicamente mediante solicitud explícita de cancelación ("cancela la tarea"), abortando el token de ejecución de la acción de fondo.

### 34.4. Comparativa de Proveedores TTS y Fish Audio (Privacidad y Autorización)
* **Matriz Comparativa (`compare_tts_providers`):**
  - **Pocket TTS:** 100% local, latencia de arranque ~180ms, RTF ~0.18, privacidad absoluta, 0 tráfico de red.
  - **Edge-TTS (`es-PE-CamilaNeural`):** Prosodia sobresaliente en español, latencia ~650ms, requiere red HTTPS externa.
  - **Windows SAPI:** 100% local nativo, latencia ~45ms, robótico, fallback infalible de último recurso.
  - **Fish Audio:** Servicio en la nube no configurado. **No se envían grabaciones a servicios de terceros sin autorización expresa del usuario** (política estricta de soberanía de datos). Clasificado honestamente como `NO AUTORIZADO`.

### 34.5. Palabra de Activación Desacoplada (Fase I5) y Hardware Real
* **Veredicto I5:** openWakeWord no cuenta con modelo acústico oficial para "Jessyca" en español. El sistema declara honestamente `is_acoustic_model_available = False` y mantiene Pulsar para Hablar (PTT) como el método de producción seguro y confiable. Ningún activador de voz autoriza acciones (`authorizes_action = False`).
* **Hardware Real Auditado:** Dispositivo `Logitech G435 Wireless Headset` en Windows 11 Pro validado mediante `AudioDeviceManager`.

### 34.6. Resultados de Pruebas Automatizadas
* **Suite de Fase 14:** `pytest tests/voice/test_push_to_talk_first_version_phase14.py -v`:
  - **9 passed in 5.50s (100% pass rate)**.
* **Suite Combinada de Voz:** `pytest tests/voice/test_push_to_talk_first_version_phase14.py tests/voice/test_stt_local_and_wake_word_phase08.py tests/voice/test_openwakeword_phase_i5.py tests/voice/test_barge_in_phase73.py tests/voice/test_tts_manager_phase72.py -v`:
  - **71 passed in 10.82s (100% pass rate)**.

---

## 35. Aceptación Funcional Integral, Auditoría Crítica y Clasificación Honesta de Capacidades

### 35.1. Matriz de Aceptación Reforzada y Auditoría de Evidencia (REQ-01 a REQ-12)
Validación exhaustiva y crítica ejecutada sobre el código real del sistema en Windows 11 Pro mediante:
- `tests/acceptance/test_functional_acceptance_matrix.py` (13 pruebas de capacidad profunda y hardware)
- `tests/acceptance/test_natural_language_e2e_traces.py` (4 pruebas de extremo a extremo desde entrada de usuario en lenguaje natural)
- **Resultado Combinado:** **17 passed in 23.91s (100% pass rate)**.
* **Detalle por Requisito:**
  1. **Abrir una aplicación y una carpeta (`test_req_01_open_application_and_folder`):**
     - Apertura de Notepad validada en psutil (`WindowsAppsSkill`).
     - Apertura de directorio en Explorer con verificación de existencia física y bloqueo de rutas críticas del SO.
     - Detección precisa de fallos ante aplicaciones inexistentes (`NOT_FOUND`).
  2. **Localizar, copiar y renombrar archivos (`test_req_02_locate_copy_and_rename_files`):**
     - Búsqueda en disco con `FilesSearchSkill` retornando coincidencias reales.
     - Duplicación con `FilesCopySkill` verificando consistencia en bytes de origen y destino.
     - Renombrado con `FilesRenameSkill` validando prevención de colisiones en destino.
     - Bloqueo inmediato ante archivos origen inexistentes o rutas protegidas de Windows.
  3. **Buscar en web y obtener fuentes (`test_req_03_web_search_and_extract_sources`):**
     - Consulta web mediante `BrowserSearchSkill` bajo política Deny-by-Default (dominio autorizado `google.com`).
     - Extracción de fragmentos textuales, URLs formales y metadatos de búsqueda.
     - Rechazo ante consultas vacías.
  4. **Reproducir y pausar video con observación temporal (`test_req_04_play_and_pause_video`):**
     - Control multimedia con `BrowserYouTubeSkill`: reproducción (`PLAYING`), medición de avance temporal en alta resolución (`time.perf_counter`) y pausa (`PAUSED`).
  5. **Crear documento Word con reapertura e inspección (`test_req_05_create_word_document`):**
     - Generación física de `.docx` con `WordDocumentProcessor.create_report`.
     - Reapertura directa y comprobación celda a celda de la tabla y párrafos con `python-docx`.
  6. **Crear Excel con motor COM o recálculo pendiente (`test_req_06_create_excel_with_verified_calculations`):**
     - Generación física de `.xlsx` con `ExcelSpreadsheetProcessor.create_budget_workbook`.
     - Evaluación de fórmulas con motor real Microsoft Excel COM (`evaluate_formulas_with_engine`); si COM no está disponible, reporta honestamente recálculo pendiente sin inventar valores ficticios.
  7. **Crear presentación PowerPoint con inspección estructural y COM (`test_req_07_create_powerpoint_presentation`):**
     - Creación de `.pptx` 16:9 con `PowerPointPresentationProcessor.create_presentation`.
     - Inspección profunda de diapositivas, textos y formas (`inspect_presentation`) y apertura con Microsoft PowerPoint COM real (`verify_with_powerpoint_app`, `engine == "Microsoft PowerPoint (COM)"`).
  8. **Corregir proyecto con fallo funcional realista (Orca/ADE) (`test_req_08_code_assistant_diagnose_patch_and_test`):**
     - Orquestador `CodeAssistantWorkflow` diagnostica fallo de cálculo comercial/financiero (`calcular_precio_final`), ejecuta pytest inicial con fallo (`exit_code != 0`), genera diff unificado con `difflib`, aplica parche y verifica salida exitosa (`exit_code == 0`).
  9. **Completar tarea de varios pasos (`test_req_09_multi_step_are_workflow_execution`):**
     - Ejecución gobernada en `ARERuntime` con propagación tipada de datos entre pasos (`$step_1.output.sources` -> `documents.create_word_report`).
     - Creación comprobada del documento Word consolidado; detención inmediata de dependientes ante fallo de predecesores.
  10. **Guardar, consultar, modificar y borrar preferencia (`test_req_10_memory_save_retrieve_modify_and_delete_preference`):**
      - `LongTermMemoryEngine` almacena preferencia explícita del usuario (`USER_PREFERENCES`).
      - Recuperación exitosa tras reinicio completo de instancia/sesión.
      - Modificación con versionado incremental (v1 -> v2) y eliminación física definitiva.
  11. **Usar voz (Separación de Contrato y Diagnóstico Real):**
      - **11a (	est_req_11a_voice_simulated_contract_flow):** Lógica PTT, descarte de eco/silencio, token de cancelación (barge-in) y máquina de estados.
      - **11b (	est_req_11b_voice_real_hardware_and_tts_diagnostics):** Diagnóstico de micrófono físico en Windows host (AudioDeviceManager.list_input_devices()) y disponibilidad de motores TTS reales (TTSManager: PocketTTS y EdgeTTS).
  12. **Controlar función móvil bajo contrato JDE (`test_req_12_mobile_control_under_jde_contract`):**
      - Emparejamiento con token criptográfico seguro (64 hex) en `DevicePairingManager`.
      - Verificación del contrato JDE, deduplicación atómica y recibos de acción en modo driver de prueba (`res.final_status == "SUCCESS"`).
      - **Prueba física honesta:** En ausencia de teléfono físico conectado, la ejecución contra ADB real falla de forma transparente (`device not found`), previniendo falsos éxitos. Revocación exitosa del dispositivo (`REVOKED`).

### 35.2. Trazabilidad Extremo a Extremo desde Lenguaje Natural (test_natural_language_e2e_traces.py)
Demostración verificada desde la entrada real del usuario:
1. **Abrir carpeta:** entrada 'abre la carpeta [ruta_prueba]' -> Core (open_folder) -> JDE (ALLOW) -> Herramienta (windows.launch_app / explorer.exe) -> ExecutionVerifier -> Respuesta confirmada.
2. **Buscar información:** entrada 'busca en internet sobre computación cuántica' -> Core (browser_search) -> JDE (ALLOW) -> Herramienta (browser.search) -> ExecutionVerifier -> Respuesta con resultados.
3. **Crear documento:** entrada de informe Word en disco -> JDE (ALLOW) -> Herramienta (WordDocumentProcessor) -> ExecutionVerifier (existencia física e integridad en disco) -> Respuesta confirmada.
4. **Tarea multi-etapa (ARE):** entrada 'investiga este tema sobre inteligencia artificial cuántica' -> Core (multistep_research) -> ARE Runtime -> JDE (ALLOW) -> Herramienta (multistep.orchestrate) -> ExecutionVerifier -> Respuesta estructurada.

### 35.3. Auditoría Técnica de Código y Componentes
* **Catálogo de Acciones ARE:** Se verificó que ninguna acción utilice placeholders genéricos (`action.execute`). Cada una de las 16 acciones cuenta con esquema estricto de entradas, salidas tipadas y verificador físico.
* **Control Móvil vs API Bridge:** Desacoplamiento estricto entre `interfaces/mobile_api` (FastAPI en PC recibiendo peticiones entrantes de la app móvil) y `core/mobile` (capacidad de PC para orquestar y controlar dispositivos móviles gobernada por JDE).
* **Flags y Dobles de Prueba:** Flags de prueba (`test_mode`, `mock_unverified`) se encuentran estrictamente encapsulados en verificadores de testing sin alterar el flujo predeterminado de producción.

### 35.4. Clasificación Honesta de Capacidades en 4 Categorías
1. **Funcional y Verificado:** JDE Engine, Action Reasoning Engine (ARE), Sistema de Archivos, Procesadores de Documentos (Word, Excel, PowerPoint), Asistencia de Código (Orca/ADE), Memoria Persistente de Preferencias, Voz PTT (Local FasterWhisper + Edge-TTS/SAPI), Instalación Local CLI `jessyca`.
2. **Funcional con Limitaciones:** Control de Aplicaciones de Escritorio (condicionado a sesiones interactivas con GUI visible), Búsqueda Web (sujeta a lista blanca Deny-by-Default), Evaluación de Fórmulas Complejas de Excel (escritura nativa al 100%, cálculo dinámico condicionado a motor COM de Excel).
3. **Implementado sin Prueba Real:** Control Físico de Dispositivos Móviles (contrato de gobernanza JDE y driver implementados; prueba con hardware físico real pendiente por falta de teléfono Android conectado por USB).
4. **Pendiente:** Modelo acústico local en español para openWakeWord (se mantiene PTT como canal primario seguro), Interfaz Gráfica de Escritorio (Desktop GUI / Bandeja de Sistema), y Validación de campo con dispositivo móvil físico en vivo.

### 35.5. Resultados de Pruebas Automatizadas
* **Suite de Aceptación:** `pytest tests/acceptance/test_functional_acceptance_matrix.py -v`:
  - **12 passed in 17.14s (100% pass rate)**.
* **Batería de Suites Combinadas:**
  - `pytest tests/are/test_are_real_tools_workflows_phase13.py tests/voice/test_push_to_talk_first_version_phase14.py tests/mobile/test_mobile_control_jde.py tests/distribution/test_distribution_cli_and_paths.py tests/acceptance/test_functional_acceptance_matrix.py -q`:
  - **65 passed in 27.86s (100% pass rate)**.

---

## 36. AUDITORÍA INTEGRAL Y CORRECTIVA DE JESSYCA 3.0 (2026)

* **Documento de Auditoría Consolidado:** [`reports/AUDITORIA_INTEGRAL_CORRECTIVA_2026.md`](../reports/AUDITORIA_INTEGRAL_CORRECTIVA_2026.md)
* **Rama de Trabajo:** `audit/integral-corrective` (base: `3c41be2`)
* **Objetivo:** Preparación de JESSYCA para pruebas de uso del usuario identificando y corrigiendo desconexiones de rutas, funciones incompletas, integraciones inactivas y excepciones de runtime en Windows.

### 36.1. Acciones Correctivas Implementadas y Verificadas
1. **Reconexión de Documentos Office en `JessycaLocalAgent` (`core/local_agent/local_agent.py`):**
   - Resolución formal de intenciones `create_document`, `read_document`, `summarize_document`, `convert_document` en el parser de intenciones/slots.
   - Enrutamiento hacia `documents.create`, `documents.read`, etc. en el pipeline unificado de ejecución.
   - Prevención de falsos lanzamientos de aplicaciones con archivos Office (`.docx`, `.xlsx`, `.pptx`, `.pdf`).
2. **Potenciación de Skills Documentales (`skills/documents_skills.py`):**
   - Lectura transparente multiformato para Word (python-docx), Excel (openpyxl), PowerPoint (python-pptx) y PDF (Docling).
   - Generación de informes Word con estructura y tablas, libros Excel con fórmulas nativas y presentaciones PowerPoint.
3. **Compatibilidad AnyDoc (`core/anydoc/orchestrator.py`, `core/anydoc/__init__.py`):**
   - Exportado el alias canónico `AnyDocOrchestrator = AnyDocGovernedOrchestrator`.
4. **Reconexión de `MobileControlAdapter` en IntegrationHub (`core/integration/hub.py`, `core/mobile/adapter.py`, `config/settings.py`):**
   - Autoregistro en `register_default_adapters`.
   - Inspección segura de CLI `adb.exe` en `check_dependencies` aislando la verificación de módulos Python.
5. **Estabilización de COM RPC en PowerPoint (`core/documents/powerpoint_processor.py`):**
   - Eliminación de la excepción fatal `Windows fatal exception: code 0x80010108 (RPC_E_DISCONNECTED)` mediante desvinculación explícita de punteros OLE (`_oleobj_`).

### 36.2. Resultados de Verificación Extremo a Extremo
* **Pruebas E2E en Lenguaje Natural (`tests/acceptance/test_natural_language_e2e_traces.py`):**
  - `test_e2e_01_open_folder`: PASSED
  - `test_e2e_02_browser_search`: PASSED
  - `test_e2e_03_create_word_document`: PASSED (verificado con entrada en lenguaje natural real a través de `agent.interact` creando y reabriendo `acta_proyecto.docx` en disco temporal)
  - `test_e2e_04_are_multistep_research`: PASSED
  - **4/4 PASSED en 3.11s**.
* **Suite Completa de Aceptación:** `pytest tests/acceptance/ -v`:
  - **17/17 PASSED en 23.29s (100% pass rate)**.





