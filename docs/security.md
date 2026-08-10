# Arquitectura de Seguridad - Jessyca Windows MCP (Etapa 04)

## Propósito

El subsistema de seguridad de **Jessyca Windows MCP** está diseñado siguiendo **Clean Architecture**, **SOLID** y el principio de **Seguridad por Diseño** (Security by Design).

Su objetivo es actuar como una capa de inspección e interceptación previa a la ejecución de cualquier herramienta MCP solicitada por el usuario o modelos de lenguaje (LLM).

---

## Componentes y Modelos de Dominio (Subetapas 04.1 a 04.4)

### 1. Niveles de Seguridad (`SecurityLevel`)
Enum tipado para clasificar el nivel de riesgo de las herramientas:
- **`SAFE`**: Operaciones seguras sin efectos secundarios graves (ej. lectura de información de sistema).
- **`WARNING`**: Operaciones de modificación moderada que requieren precaución (ej. modificar archivos de usuario, iniciar procesos).
- **`DANGEROUS`**: Operaciones de alto impacto que requieren confirmación interactiva del usuario (ej. eliminar archivos, finalizar procesos, operaciones recursivas).
- **`CRITICAL`**: Operaciones de riesgo crítico que exigen elevación de privilegios UAC/Admin en Windows o modifican el Registro de Windows (`HKLM`) o rutas de sistema (`C:\Windows\System32`).

### 2. Decisiones de Autorización (`PermissionDecision`)
Enum tipado con los tipos formales de resolución de permisos (Subetapa 04.3):
- **`ALLOW`**: Autorizado para ejecución inmediata.
- **`DENY`**: Rechazado / Denegado explícitamente con un motivo explicativo (`reason`).
- **`REQUIRE_CONFIRMATION`**: Requiere confirmación previa antes de ejecutar.
- **`ALLOW_ONCE`**: Concedido temporalmente únicamente para un único uso.
- **`ALWAYS_ALLOW`**: Autorizado permanentemente.

### 3. Estados de Confirmación (`ConfirmationStatus`)
Enum tipado del ciclo de vida de una confirmación de usuario (Subetapa 04.4):
- **`PENDING`**: Esperando respuesta.
- **`APPROVED`**: El usuario aprobó la solicitud.
- **`REJECTED`**: El usuario rechazó la solicitud.
- **`CANCELLED`**: La solicitud fue cancelada formalmente.
- **`EXPIRED`**: No hubo respuesta dentro del tiempo límite (TTL / Expiración).

### 4. Subetapa 04.2 — Risk Engine (`RiskEngine` & `IRiskEvaluator`)
Motor de evaluación de riesgo **independiente, determinista, extensible y desacoplado**.
Responde exclusivamente a: `"¿Qué nivel de riesgo representa esta operación?"` -> Produce un `RiskAssessment`.

### 5. Subetapa 04.3 — Permission Manager (`PermissionManager` & `IPermissionManager`)
Componente desacoplado de autorización.
Responde exclusivamente a: `"¿Esta operación está autorizada?"` -> Produce un `PermissionResult` (`ALLOW`, `DENY`, `REQUIRE_CONFIRMATION`, `ALLOW_ONCE`, `ALWAYS_ALLOW`).

### 6. Subetapa 04.4 — Confirmation Manager (`ConfirmationManager` & `IConfirmationManager`)
Administra y valida las solicitudes de confirmación para operaciones que requieren aprobación explícita del usuario.
Responde exclusivamente a: `"¿Esta solicitud de confirmación fue aceptada, rechazada, cancelada o expiró?"`

> [!IMPORTANT]
> El `ConfirmationManager` **NO** ejecuta herramientas, **NO** modifica el sistema Windows y **NO** ejecuta comandos.

#### Binding de Acción mediante Action Fingerprint (SHA-256)
Cada confirmación está matemáticamente vinculada a un hash determinista:
$$\text{ActionFingerprint} = \text{SHA256}(\text{tool\_name} + \text{operation} + \text{canonical\_parameters})$$
Una confirmación otorgada para la Solicitud A jamás puede ser reutilizada para ejecutar una Solicitud B distinta.

#### Protección contra Replay Attacks & Consumo Único
Toda confirmación aprobada consumida queda bloqueada inmutablemente. Intentos de reutilización o Replay Attacks son rechazados. Incluye cerrojo de hilos (`threading.Lock`) para proteger contra condiciones de carrera.

#### Sanitización de Parámetros Sensibles
Campos sensibles (`password`, `token`, `api_key`, `secret`, `credential`) se representan como `"[REDACTED]"` en vistas de diagnóstico sin alterar el cálculo determinista del fingerprint real.

#### Proveedor de Confirmación Abstraído (`IConfirmationProvider`)
Protocolo desacoplado con implementación `MockConfirmationProvider` para simulación de respuestas en pruebas unitarias (`APPROVED`, `REJECTED`, `CANCELLED`, `TIMEOUT`).

### 7. Subetapa 04.5 — Security Policy (`SecurityPolicy`, `SecurityPolicyEvaluator`, `IPolicyEvaluator`)
Capa declarativa que define las reglas de seguridad que gobiernan las operaciones de Jessyca:
- **Protección contra Sobrescritura Accidental de DENY**: Si cualquier regla coincidente deniega una operación (`DENY`), dicha denegación prevalece sobre cualquier regla `ALLOW` o `REQUIRE_CONFIRMATION`, sin importar si la regla `ALLOW` posee una prioridad más alta o es más general.
- **Límite Absoluto de `max_allowed_risk`**: Si el riesgo de una operación excede el límite `max_allowed_risk` configurado en la política (ej. `DANGEROUS`), la operación jamás puede resultar en `ALLOW`, forzando `DENY` o `REQUIRE_ELEVATED_AUTHORIZATION`.
- **Política Predeterminada Conservadora**:
  - `SAFE` -> `ALLOW`
  - `WARNING` -> `REQUIRE_CONFIRMATION`
  - `DANGEROUS` -> `REQUIRE_CONFIRMATION`
  - `CRITICAL` -> `DENY`
  - `UNKNOWN` -> `DENY` (Fail-Safe por defecto)
- **Protección de Escalamiento de Privilegios**: Operaciones clasificadas como `CRITICAL` o con `requires_elevation=True` jamás retornan `ALLOW` de manera efectiva; se preserva `requires_elevation=True` exigiendo `REQUIRE_ELEVATED_AUTHORIZATION`.
- **Inmutabilidad y Anti Auto-Modificación**: La política es una configuración protegida que no puede ser alterada por comandos o instrucciones del LLM / usuario por voz.
- **Fuentes Legítimas de Política (`PolicySource`)**: `DEFAULT`, `SYSTEM`, `ADMINISTRATOR`, `CONFIGURATION`. Excluye explícitamente `LLM`, `USER_PROMPT` o `ASSISTANT`.

### 8. Subetapa 04.6 — Audit Logger (`AuditLogger`, `AuditEvent`, `FileAuditSink`, `IAuditSink`)
Subsistema de auditoría estructurada para la trazabilidad inmutable de eventos de seguridad:
- **Sanitización Previa**: Reemplazo recursivo de secretos y credenciales por `"[REDACTED]"` antes de la persistencia.
- **Formato JSON Lines (`.jsonl`)**: Registro atómico un evento por línea en `logs/audit/audit.jsonl`.
- **Rotación por Tamaño**: Rotación automática al superar 10 MB conservando 5 backups.
- **Concurrencia Segura**: Cerrojos `threading.Lock()` para garantizar integridad en accesos multi-hilo.
- **Modo de Fallo Fail-Safe (`BEST_EFFORT`)**: Los fallos en la persistencia de auditoría no alteran las decisiones de seguridad ni interrumpen la ejecución del sistema.

---

## Flujo de Autorización y Auditoría (Etapa 04)

```text
Usuario / LLM
      ↓
Task / Tool Request (SecurityRequest)
      ↓
Security Policy Evaluator (04.5 IPolicyEvaluator -> PolicyDecision)
      ↓
Risk Engine (04.2 IRiskEvaluator -> RiskAssessment)
      ↓
Permission Manager (04.3 IPermissionManager -> PermissionResult)
      ↓
Confirmation Manager (04.4 IConfirmationManager -> ConfirmationResult)
      ↓
Tool Execution
      ↓
Audit Logger (04.6 IAuditLogger -> AuditEvent -> FileAuditSink / MemoryAuditSink)
```

### 9. Subetapa 04.7 — Security Tests & Security Audit
Auditoría de seguridad adversarial y suite de pruebas de seguridad end-to-end:
- **Matriz de Seguridad**: Documentada en [`docs/security_audit.md`](file:///d:/JESSYCA%203.0/asistente-jessyca/docs/security_audit.md).
- **10 Invariantes de Seguridad**: Verificadas y probadas formalmente.
- **Resistencia Adversarial**: Pruebas de Replay attack, fuzzing de entradas, inmutabilidad congelada (`frozen=True`), aislamiento del Audit Logger y prevención de elevaciones no autorizadas.
- **Suite Dedicada (`tests/security/`)**: 9 módulos especializados de pruebas de seguridad adversariales.

### 31. Subetapa 11.1 — Application Control Boundary & Single-Instance Enforcement
Frontera de seguridad para el control del ciclo de vida de aplicaciones de escritorio (`windows.application` -> `launch`, `focus`, `close`):
- **Single-Instance Reuse & Duplicate Launch Prevention**: Política configurable por defecto (`APPLICATION_SINGLE_INSTANCE_ENFORCED=True`). Al solicitar la apertura de una aplicación con una sesión/HWND activo, `ApplicationSessionManager` reutiliza y asigna el foco a la ventana existente sin abrir procesos duplicados en el SO (resuelve el Bug #1 de apertura múltiple).
- **Desacoplamiento de Capas**: Arquitectura obligatoria: `JESSYCA → ApplicationControlBoundary → ApplicationSessionManager → windows.desktop / windows.shell`. `windows.desktop` permanece genérico sin lógica acoplada a ejecutables de aplicaciones.
- **Auditoría e Invariante de Privacidad**: Integración completa con `SecureExecutionPipeline`, `RiskEngine`, `PermissionManager`, `EmergencyStopManager`, `AuditLogger` y `EventBus`. Registro de metadatos exclusivamente (`action`, `app_alias`, `session_id`, `duration_ms`). CERO secretos o comandos crudos en logs.
- **Sincronización con Fail-Safe**: Parada de Emergencia (`EmergencyStopManager.check_cancellation`) detiene e interrumpe cualquier solicitud de inicio/foco de aplicación en 0ms.

### 32. Subetapa 11.2 — Secure Browser Control Boundary & Session Manager
Frontera de seguridad para el control de sesiones de navegador web (`windows.browser` -> `open_url`, `switch_tab`, `close_tab`, `control_media`):
- **URL Allowlist Policy (Deny by Default)**: Solo se permiten esquemas `http://` and `https://`. Bloqueo absoluto de esquemas peligrosos (`javascript:`, `data:`, `file:`, `chrome:`, `edge:`, `about:`).
- **Media Playback Controller & Verificación Post-Acción**: `MediaPlaybackController` ejecuta acciones de reproductor de video/audio simulando el gesto de usuario (W3C User Gesture) y verifica que el estado resultante sea `PLAYING` o `PAUSED` (**resuelve el Bug #2 de YouTube Autoplay**).
- **Cero Ejecución de JS Libre**: Prohibición absoluta de invocación de scripts arbitrarios (`eval`, `Function()`). Solo se permiten acciones DOM/Media explícitamente cerradas.

### 33. Subetapa 11.3 — Media Playback, System Audio & Clipboard Control
Control verificable multimedia, audio del sistema y portapapeles (`windows.media`, `windows.audio`, `windows.clipboard`):
- **Media Playback Verification Pipeline**: Tubería inmutable `inspect state -> attempt action -> wait -> inspect state -> verify result`. Detección de Autoplay bloqueado por el navegador (`MEDIA_BLOCKED`) sin evadir políticas del SO.
- **Separación de Audio del Sistema**: `SystemAudioController` separa explícitamente la reproducción en navegador de la configuración de volumen, mute y dispositivos de salida del SO.
- **Frontera de Seguridad de Portapapeles**: `ClipboardSecurityManager` trata el contenido como `UNTRUSTED DATA`, impone límite de tamaño (`CLIPBOARD_MAX_SIZE=64KB`), interruptor global de activación (`CLIPBOARD_ENABLED`), aplica `OCRTextSanitizer` en toda lectura y registra metadatos exclusivamente en auditoría.

### 34. Subetapa 11.4 — Document Generation Bridge & Sandbox Hardening
Puente de generación segura de documentos (`windows.files.generate_document`):
- **Aislamiento de Sandbox Inquebrantable**: Integración obligatoria con `PathSecurityManager` para garantizar que la ruta canónica del archivo generado resida estrictamente dentro de `FILESYSTEM_SANDBOX_ROOT`. Bloqueo de Path Traversal (`../`, `..\`, UNC, root escape).
- **Límite de Tamaño & Pipeline**: Límite de tamaño de salida de 10 MB (`MAX_DOCUMENT_SIZE_BYTES`). Invocación sujeta a la tubería determinista `SecureExecutionPipeline` e inmutabilidad de metadatos de auditoría (`checksum_sha256`, `bytes_written`, `format`). CERO texto de documento en logs.

### 35. Subetapa 12.1 — Local Vector Store Foundation & Memory Evidence Boundary
Almacén vectorial local y recuperación de memoria semántica de largo plazo (`core/local_vector_store.py`):
- **Invariante Central MEMORY = EVIDENCE, MEMORY != AUTHORITY**: Los documentos vectoriales recuperados se tratan estrictamente como datos no confiables de contexto (`UNTRUSTED DATA`). CERO capacidad de conceder permisos, alterar reglas de autorización o modificar evaluaciones de `RiskEngine` o `PermissionManager`.
- **Generación de Embeddings Local & Determinista**: `LocalEmbeddingProvider` genera vectores numéricos de 384 dimensiones de forma 100% local sin requerir APIs externas.
- **Sanitización de Secretos & Límites**: Aplica `OCRTextSanitizer` en toda evidencia recuperada antes de entregarla al contexto. Enforza límite máximo de documentos (`VECTOR_STORE_MAX_DOCUMENTS=10000`).

### 29. Subetapa 10.1 — Session State & Persistent Memory Foundation
Gestión de estado de sesión y memoria persistente inmutable (`core/session_*.py`):
- **Untrusted Memory Trust Boundary**: Toda memoria conservada (mensajes, hechos, preferencias) se trata estrictamente como datos no confiables. La memoria guardada no puede actuar como instrucción ejecutable ni sobreescribir políticas de seguridad.
- **Zero Tool / System Execution**: CERO capacidad de ejecución de herramientas o invocación de shell en la capa de sesión.
- **Redacción de Secretos e Invariante de Privacidad**: Integración automática de `SecretRedactor` en mensajes y memoria. `AuditLogger` y `EventBus` registran **ÚNICAMENTE METADATOS** (`session_id_hash`, `status`, `message_count`, `fact_count`, `duration_ms`). CERO mensajes o hechos crudos en logs de auditoría.
- **Almacenamiento Desacoplado Thread-Safe**: `InMemorySessionStore` y `SQLiteSessionStore` protegidos con `threading.RLock` y consultas parametrizadas. Transiciones de estado validadas por `SessionSecurityManager` (FAIL-SAFE DENY).

### 30. Subetapa 10.2 — Context Builder & Memory Retrieval Engine
Motor de construcción de contexto y recuperación de memoria (`core/context_*.py` y `memory_retriever.py`):
- **Resistencia a Prompt-Injection**: Aislamiento de contenido de memoria recuperada (e.g. `[SAFETY_FILTERED]` sobre intentos de sobreescritura de instrucciones). La memoria nunca adquiere autoridad para alterar reglas de seguridad o capacidades.
- **Zero Tool Execution / System Mutation**: CERO ejecución de herramientas, CERO comandos del sistema y CERO invocación de shell en la construcción del contexto.
- **Redacción de Secretos & Privacidad en Auditoría**: Aplicación de `SecretRedactor` en el contenido de contexto. Registro de **ÚNICAMENTE METADATOS** en `AuditLogger` y `EventBus` (`session_id_hash`, `total_items`, `total_size_bytes`, `duration_ms`). CERO textos crudos en auditoría.
- **Timeout Enforced & Structural Bounds**: Enforzamiento de timeout no anulable (`CONTEXT_RETRIEVAL_TIMEOUT = 5.0s`), límites máximos de items y bytes en `ContextSnapshot` inmutable.

---

## Flujo de Autorización y Auditoría (Etapas 04–10)

```text
Usuario / Cliente MCP / Interfaz de Escritorio
      ↓
SessionManager (10.1) -> SessionState (Inmutable)
      ↓
ContextBuilder (10.2 - core/context_builder.py)
      ↓
ContextSecurityManager (Prompt-Injection Isolation + SecretRedactor + Bounds + Timeout)
      ↓
IMemoryRetriever (SessionMemoryRetriever / FakeMemoryRetriever)
      ↓
ContextSnapshot (Inmutable) -> Downstream Agent (Metadatos Exclusivos en AuditLogger)
```
