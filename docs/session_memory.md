# Session State & Persistent Memory Foundation — Jessyca Virtual Assistant (Subetapa 10.1)

## Visión General

La **Subetapa 10.1** inicia la **ETAPA 10 — JESSYCA VIRTUAL ASSISTANT & AGENTIC WORKFLOW ORCHESTRATION** construyendo la capa de gestión de estado de sesión y memoria persistente inmutable.

---

## GARANTÍAS ABSOLUTA DE SEGURIDAD Y PRIVACIDAD

1. **ZERO TOOL / SYSTEM EXECUTION**: La capa de sesión es exclusivamente para almacenamiento y gestión de estado. CERO ejecución de herramientas, CERO automatización de escritorio, CERO invocación de shell.
2. **UNTRUSTED MEMORY TRUST BOUNDARY**: Toda memoria (hechos, preferencias, historial de mensajes) se considera **DATOS NO CONFIABLES**. La memoria guardada no puede actuar como instrucción ni sobreescribir políticas de seguridad.
3. **FAIL-SAFE DENY**: Sesiones en estados terminales (`EMERGENCY_STOPPED`, `CANCELLED`, `EXPIRED`), NaN, Infinity, tipos incorrectos o SessionIds inválidos resultan en `DENY`.
4. **PRIVACIDAD & REDACCIÓN (METADATOS EXCLUSIVOS)**: Integración automática de `SecretRedactor` en mensajes y memoria. `AuditLogger` y `EventBus` registran **ÚNICAMENTE METADATOS** (`session_id_hash`, `status`, `message_count`, `fact_count`, `duration_ms`). CERO mensajes crudos o hechos en logs de auditoría.
5. **ESTADO INMUTABLE THREAD-SAFE**: `SessionState` y todos sus componentes son dataclasses congeladas (`frozen=True`). Almacenamiento desacoplado mediante `InMemorySessionStore` y `SQLiteSessionStore` protegido por `threading.RLock`.

---

## Componentes Principales

### 1. Modelos de Sesión (`core/session_models.py`)
- `SessionStatus`: Estados explícitos (`ACTIVE`, `PAUSED`, `WAITING_CONFIRMATION`, `WAITING_INPUT`, `COMPLETED`, `CANCELLED`, `EXPIRED`, `EMERGENCY_STOPPED`).
- Dataclasses inmutables: `SessionId`, `SessionRole`, `SessionMessage`, `SessionFact`, `SessionPreference`, `SessionMetadata`, `SessionSnapshot`, `SessionState`.

### 2. Validador de Seguridad (`core/session_security.py`)
- `SessionSecurityManager`: Valida SessionIds, transiciones de estado, sanitiza textos con `SecretRedactor` y enforza límites configurados.

### 3. Almacenamiento Desacoplado (`core/session_store.py`)
- `ISessionStore`: Protocolo abstracto para persistencia de sesiones.
- `InMemorySessionStore`: Almacenamiento en memoria thread-safe con `threading.RLock`.
- `SQLiteSessionStore`: Persistencia en SQLite nativo sin dependencias externas usando SQLite WAL mode y consultas parametrizadas.

### 4. Gestor de Sesión (`core/session_manager.py`)
- `SessionManager`: Servicio orquestador del ciclo de vida de sesión (`create_session`, `get_session`, `append_message`, `add_fact`, `add_preference`, `update_status`, `create_snapshot`, `pause_session`, `resume_session`, `cancel_session`, `expire_session`).
