# JESSYCA 3.0 — OFFICIAL ROADMAP EXTENDIDO

---

## PARTE I — COMPONENTES COMPLETADOS (ESTADO ESTABLE)

El subsistema core de **Jessyca Windows MCP** ha sido implementado bajo **Clean Architecture**, **SOLID**, **Seguridad por Diseño** y **Pruebas Estrictas**.

### ETAPA 04 — SECURITY FOUNDATION
- **04.1 Security Architecture Foundation**: Definición de `SecurityLevel` (`SAFE`, `WARNING`, `DANGEROUS`, `CRITICAL`), `PermissionDecision`, `ConfirmationStatus` e inmutabilidad de contexto.
- **04.2 Risk Engine**: Motor de evaluación de riesgo determinista e independiente (`RiskEngine`, `IRiskEvaluator`).
- **04.3 Permission Manager**: Administrador de permisos desacoplado (`PermissionManager`, `IPermissionManager`).
- **04.4 Confirmation Manager**: Gestor interactivo de solicitudes de confirmación del usuario con expiración (TTL) y firmas canónicas.
- **04.5 Security Policy**: Evaluador determinista de políticas configurables (`SecurityPolicyEvaluator`, `PolicyDecision`).
- **04.6 Audit Logger**: Registro estructurado de auditoría de seguridad inmutable y sanitizado (`AuditLogger`, `AuditEvent`, `FileAuditSink`, `MemoryAuditSink`).
- **04.7 Security Tests & Audit**: Suite de pruebas adversariales verificando las 10 Invariantes de Seguridad.

### ETAPA 05 — MCP SERVER & EXECUTION SECURITY
- **05.1 MCP Server Foundation**: Servidor FastMCP (`JessycaMCPServer`), `ServerLifecycleManager`, `RequestContext` con aislamiento de entradas no confiables del cliente.
- **05.2 Tool Execution Boundary & Security Integration**: Pipeline determinista de 10 pasos (`SecureExecutionPipeline`), `AuthorizationEvidence` con hash criptográfico SHA-256 (`action_fingerprint`), `SecurityDecisionAggregator` (regla `most_restrictive`), `SecureExecutionBoundary` e `IToolExecutor`.

### ETAPA 06 — WINDOWS TOOLS EXECUTION & CAPABILITY SYSTEM
- **06.1 Capability System & Tool Registry Hardening**: Capa declarativa inmutable de capacidades (`ToolCapability`, `CapabilityOperation`, `CapabilitySource`), `CapabilityRegistry`, `CapabilityValidator`, `CapabilityResolver` e integración con `ToolRegistry`.
- **06.2 Secure Filesystem Tools (`windows.files`)**: Manipulación de archivos e inspección dentro de sandbox aislado (`FILESYSTEM_SANDBOX_ROOT`), `PathSecurityManager` (anti-traversal, canonical realpath, anti-symlink escape), escrituras atómicas (`os.replace()`) y límites de tamaño.
- **06.3 Secure Process Management Tools (`windows.process`)**: Consulta y administración de procesos mediante `psutil` con Cero Shell Execution, **Protected Process Protection** (bloqueo de terminación para `System`, `csrss.exe`, `lsass.exe`, etc.) y **PID Reuse Protection** (binding de `pid` + `name` + `creation_time`).
- **06.4 Secure Windows Registry Tools (`windows.registry`)**: Inspección **estrictamente READ-ONLY** del Registro de Windows vía `winreg` nativo (con backend desacoplado `IRegistryBackend` / `FakeRegistryBackend`), `RegistryPathSecurityManager` (hives autorizados HKCU/HKLM, límite de profundidad). Cero `reg.exe` o invocación de shell.
- **06.5 Secure Windows Services Tools (`windows.services`)**: Inspección **estrictamente READ-ONLY** de Servicios de Windows vía `psutil.win_service_iter()`, `ServiceNameSecurityManager` (anti-command injection). Cero `sc.exe` o invocación de shell.

> [!IMPORTANT]
> **ESTADO OFICIAL DE LA ETAPA 06**:
> **STATUS: COMPLETED — 06.5**

### ETAPA 07 — SECURE SHELL & COMMAND EXECUTION SYSTEM (`windows.shell`)
- **07.1 Command Policy & Allowlist Foundation**: Regla estricta de ejecutor explícito en lista blanca.
- **07.2 Secure Command & Argument Parser**: Parser sin `shell=True` (anti-command injection).
- **07.3 PowerShell & CMD Execution Boundary**: Modo no interactivo (`-NoProfile -NonInteractive`).
- **07.4 Command Execution Engine**: Timeouts, supervisión asíncrona y cuotas de recursos.
- **07.5 Output Security & Redaction**: Filtrado y sanitización de credenciales.
- **07.6 Command Audit & Adversarial Testing**: Fuzzing y pruebas de seguridad adversariales.

> [!IMPORTANT]
> **ESTADO OFICIAL DE LA ETAPA 07**:
> **STATUS: COMPLETED — 07.6**

### ETAPA 08 — DESKTOP AUTOMATION, VISION & OCR SYSTEM (`windows.desktop`)
- **08.1 Desktop Vision Foundation & Screen Capture**: Captura de pantalla segura (`take_screenshot`) con metadatos exclusivamente en auditoría.
- **08.2 OCR Text Extraction Engine**: Reconocimiento OCR de texto (`ocr_screen`), regiones y redactor de secretos (`OCRTextSanitizer`).
- **08.3 UI Element Bounding Box & Visual Element Inspector**: Inspección visual READ-ONLY de ventanas (`get_active_window`, `list_windows`, `inspect_ui_element`) e inmutabilidad (`WindowInfo`, `DetectedUIElement`).
- **08.4 Secure Desktop Automation Boundary**: Frontera de automatización gráfica protegida por el subsistema independiente de Parada de Emergencia / Fail-Safe (`EmergencyStopManager`), token de cancelación (`CancellationToken`), guardias resguardados (`ActionGuard`), ejecutores desacoplados (`IMouseExecutor`, `IKeyboardExecutor`), verificación post-acción (`ActionVerifier`), sincronización por condiciones (`DesktopSynchronizer`) y mapeo de DPI Awareness por monitor (`CoordinateMapper`).

> [!IMPORTANT]
> **ESTADO OFICIAL DE LA ETAPA 08**:
> **STATUS: COMPLETED — 08.4**

### ETAPA 09 — SECURE NETWORK & SYSTEM DIAGNOSTICS (`windows.network`)
- **09.1 Network Interfaces & Adapter Inspection**: Inspección READ-ONLY de adaptadores e IP.
- **09.2 Active Connections & Port Inspection**: Consulta de puertos escuchando y conexiones TCP/UDP activas.
- **09.3 System Routing Table & DNS Cache**: Tabla de rutas IP y caché DNS local.
- **09.4 Network Boundary Consolidation**: Frontera de seguridad consolidada de red.

> [!IMPORTANT]
> **ESTADO OFICIAL DE LA ETAPA 09**:
> **STATUS: COMPLETED — 09.4**

### ETAPA 10 — SESSION STATE, CONTEXT ENGINE & MEMORY FOUNDATION
- **10.1 Session State & Persistent Memory Foundation**: Modelos inmutables (`SessionState`, `SessionMessage`, `SessionFact`, `SessionPreference`, `SessionMetadata`), `SessionSecurityManager`, `InMemorySessionStore` y `SQLiteSessionStore`.
- **10.2 Context Builder & Memory Retrieval Engine**: Snapshot inmutable `ContextSnapshot`, orquestador `ContextBuilder`, protocolo `IMemoryRetriever`, aislamiento de prompt injection y acotamiento de tamaño/items.

> [!IMPORTANT]
> **ESTADO OFICIAL DE LA ETAPA 10**:
> **STATUS: COMPLETED — 10.2**

### ETAPA 11 — SYSTEM APPLICATION, BROWSER & CLIPBOARD CONTROL BOUNDARIES
- **11.1 Application Control Boundary**: Gestor de fronteras de control de aplicaciones nativas (`ApplicationBoundaryManager`, `ApplicationSessionManager`), política de instancia única (*Single Instance Enforcement*) y lista autorizada.
- **11.2 Browser Control Boundary & URL Security**: Control seguro de navegación web (`BrowserBoundaryManager`), eseguramiento de esquemas (`http`, `https`) y política estricta de dominios autorizados (*URL Allowlist*).
- **11.3 Clipboard Security Boundary**: Acceso controlado y aislado al portapapeles de Windows (`ClipboardSecurityManager`), acotamiento de tamaño (64 KB) y sanitización con `SecretRedactor` / `OCRTextSanitizer`.

> [!IMPORTANT]
> **ESTADO OFICIAL DE LA ETAPA 11**:
> **STATUS: COMPLETED — 11.3**

### ETAPA 12 — SEMANTIC MEMORY & LOCAL VECTOR STORE
- **12.0 Semantic Memory Readiness & Architectural Audit**: Auditoría de Etapa 10, postulado $MEMORY = EVIDENCE, MEMORY \neq AUTHORITY$, taxonomía de 6 tipos de memoria (`FACT`, `PREFERENCE`, `EPISODIC`, `TASK`, `TECHNICAL`, `TEMPORARY`) y diseño del pipeline de sanitización.
- **12.1 Local Vector Store & Local Embedding Engine**: Implementación de `LocalVectorStore` (thread-safe, bounded top-k, bounded document size, bounded metadata, path validation), `FakeVectorStore`, `LocalEmbeddingProvider` (hash 384-dim determinista 100% offline), `OllamaEmbeddingProvider` (API HTTP Ollama en 127.0.0.1 con fallback) y `ChromaVectorStore` (integración local con fallback).
- **12.2 Semantic Memory Pipeline Integration & Context Builder Fusion**: Integración de `SemanticMemoryRetriever` en `ContextBuilder`, origen `ContextSource.SEMANTIC_MEMORY`, consultas semánticas asociativas y empaquetado en `ContextSnapshot` como evidencia no confiable.

### ETAPA 13 — AUTONOMY, TASK SCHEDULER & NOTIFICATION DISPATCHER
- **13.1 Task Scheduler & Background Operations**: `TaskScheduler` local, almacenamiento efímero acotado, límites de concurrencia y retención.
- **13.2 Local Wake Word Detector**: `WakeWordDetector` efímero acotado local (Inactivo, Listening, Triggered, Processing, Error).
- **13.3 Notification Dispatcher**: `NotificationDispatcher` con Windows Toast, edge-tts fallback, deduplicación y rate limiting.
- **13 Auditoría Final**: Auditoría de seguridad probando que la autonomía programada no eleva privilegios.

> **STATUS: COMPLETED — ETAPA 13**

### ETAPA 14 — UNTRUSTED PLUGIN ARCHITECTURE & SANDBOX
- **14.0 Plugin Security Architecture**: Modelo de seguridad `UNTRUSTED CODE`, 12 capacidades declaradas inmutables y prohibición de auto-elevación de riesgo.
- **14.1 Plugin Manifest**: Validación pre-carga con `PluginManifestValidator`, esquemas, SemVer e higiene de rutas.
- **14.2 Secure Plugin Loader**: Pipeline seguro de carga de 7 pasos restringido a `PLUGINS_DIRECTORY` y prevención anti Symlink Escape.
- **14.3 Plugin Execution Sandbox**: Aislamiento de recursos y tiempo de ejecución acotado (`PLUGIN_SANDBOX_TIMEOUT`).
- **14.4 Plugin Execution Pipeline**: Ruta obligatoria de 8 pasos integrando la arquitectura de seguridad completa.
- **14 Auditoría Adversarial**: 13 ataques adversariales neutralizados exitosamente.

> **STATUS: COMPLETED — ETAPA 14**

### ETAPA 15 — SYSTEM MODIFICATION BOUNDARIES (SYSTEM WRITE)
- **15.0 System Write Readiness Audit**: Auditoría inicial del sistema y dictamen de cero escrituras habilitadas.
- **15.1 Controlled Change Transaction**: `ChangeTransactionManager`, `ChangeSnapshot` SHA-256, `ChangeResult`, `RollbackResult`, grados de reversibilidad (`REVERSIBLE`, `PARTIALLY_REVERSIBLE`, `IRREVERSIBLE`) y flujo de 6 pasos.
- **15.2 Registry Write Boundary**: `RegistryWriteBoundary` con allowlist explícita, deshabilitado por defecto, *Diff View* antes de confirmar y rollback.
- **15.3 Service Control Boundary**: `ServiceControlBoundary` con protección de servicios críticos (`SERVICE_PROTECTED_LIST`), inspección previa, confirmación y rollback.
- **15.4 Software Install Boundary**: `SoftwareInstallBoundary` restringido a `winget` y allowlist explícita, prohibición de `.exe`/`.msi` arbitrarios, inyección de shell, fingerprint SHA-256 y rollback de desinstalación.
- **15 Auditoría Final de Seguridad**: 14 demostraciones formales de seguridad validadas con 176/176 pruebas passing.

> [!IMPORTANT]
> **ESTADO OFICIAL DE LA ETAPA 15**:
> **STATUS: COMPLETED — ETAPA 15**

---

## PARTE IV — PRÓXIMA SUBETAPA RECOMENDADA

**ETAPA COMPLETADA**:
`ETAPA 15 — SYSTEM MODIFICATION BOUNDARIES`

**ESTADO GLOBAL**:
Todas las etapas hasta la Etapa 15 se encuentran 100% implementadas, auditadas adversariamente y verificadas con 176 pruebas passing al 100%.

