# Context Builder & Memory Retrieval Engine — Jessyca Virtual Assistant (Subetapa 10.2)

## Visión General

La **Subetapa 10.2** amplia la **ETAPA 10 — JESSYCA VIRTUAL ASSISTANT & AGENTIC WORKFLOW ORCHESTRATION** construyendo el motor de recuperación de memoria (`MemoryRetriever`) y construcción de contexto (`ContextBuilder`) determinista e inmutable.

---

## GARANTÍAS ABSOLUTAS DE SEGURIDAD Y PRIVACIDAD

1. **ZERO TOOL / SYSTEM EXECUTION**: La capa de construcción de contexto es puramente transformadora y de lectura en memoria. CERO ejecución de herramientas, CERO automatización de escritorio, CERO invocación de shell.
2. **UNTRUSTED MEMORY TRUST BOUNDARY**: Toda memoria recuperada se mantiene estrictamente aislada como **DATOS NO CONFIABLES**. La memoria no puede sobreescribir instrucciones de sistema, decisiones de riesgo ni políticas de seguridad.
3. **PROMPT-INJECTION RESISTANCE**: Sanitización activa y aislamiento de intentos de Prompt-Injection (e.g. `System Instruction: Ignore previous instructions`). El contenido se mantiene estrictamente en campos de datos.
4. **FAIL-SAFE DENY**: Consultas malformadas, NaN, Infinity, tipos incorrectos, valores negativos o SessionIds inválidos resultan en `DENY`.
5. **REDACCIÓN DE SECRETOS E INVARIANTE DE PRIVACIDAD**: Aplicación automática de `SecretRedactor` en los contenidos de contexto. `AuditLogger` y `EventBus` registran **ÚNICAMENTE METADATOS** (`session_id_hash`, `total_items`, `total_size_bytes`, `duration_ms`). CERO textos o mensajes en logs de auditoría.
6. **ESTADO ESTRUCTURADO INMUTABLE**: `ContextQuery`, `ContextItem`, `ContextSection`, `ContextMetadata` y `ContextSnapshot` son dataclasses congeladas (`frozen=True`).

---

## Componentes Principales

### 1. Modelos de Contexto (`core/context_models.py`)
- `ContextSource`: Orígenes de contexto (`SESSION_STATE`, `RECENT_MESSAGES`, `PREFERENCES`, `FACTS`, `HISTORICAL_CONTEXT`, `METADATA`).
- Dataclasses inmutables: `ContextQuery`, `ContextItem`, `ContextSection`, `ContextMetadata`, `ContextSnapshot`.

### 2. Validador de Seguridad (`core/context_security.py`)
- `ContextSecurityManager`: Valida consultas, sanitiza textos con `SecretRedactor`, aísla intentos de prompt-injection y enforza límites configurados.

### 3. Recuperador de Memoria (`core/memory_retriever.py`)
- `IMemoryRetriever`: Protocolo abstracto de recuperación.
- `SessionMemoryRetriever`: Recuperación determinista, acotada y thread-safe a partir de `SessionManager`.
- `FakeMemoryRetriever`: Recuperación sintética para pruebas unitarias deterministas.

### 4. Constructor de Contexto (`core/context_builder.py`)
- `ContextBuilder`: Servicio orquestador de construcción de snapshots (`build_context_snapshot`). Deduplica, prioriza, aísla prompt-injection y acota los snapshots emitiendo eventos de auditoría limitados a metadatos.
