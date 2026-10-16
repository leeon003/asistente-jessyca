# JESSYCA 4.0 — FASE 2: ANÁLISIS INTEGRAL DEL CÓDIGO FUENTE DE SAI RUST

**Fecha:** 16 de Octubre de 2026  
**Auditor:** Especialista en Rust, Python, Agentes LLM y Arquitecturas de Asistentes  
**Workspace:** `d:\JESSYCA 3.0\asistente-jessyca`  
**Directorio Externo de Investigación:** `d:\JESSYCA 3.0\research\sai`

---

## 1. Identificación y Metadatos del Repositorio SAI

| Propiedad | Valor / Detalle |
|---|---|
| **Repositorio Original** | `https://github.com/jswysnemc/sai` |
| **Commit Inspeccionado** | `c6a0c74132eb03c91c26a4e05377e358907f8623` |
| **Fecha de Último Commit** | 2026-03-31 03:00:23 +0800 |
| **Autor / Mantenedor** | `snemc <snemc@qq.com>` |
| **Licencia** | **MIT License** (Copyright (c) 2026 SHORiN-KiWATA) |
| **Lenguaje Primario** | Rust (Edición 2021) + Scripts Lua (`mlua`) |
| **Estado de Mantenimiento** | Activo experimental / Framework agéntico CLI de alto rendimiento |

### Dependencias Principales en `Cargo.toml`
* `tokio` (v1.x, features: `full`): Runtime asíncrono para concurrencia masiva.
* `reqwest` (v0.12, features: `json`, `stream`): Cliente HTTP/HTTPS para Web Fetch, Web Search y llamadas a APIs de LLM.
* `serde` / `serde_json`: Serialización y deserialización JSON sin overhead.
* `async-trait`: Contratos asíncronos para herramientas y proveedores.
* `mlua`: Soporte de scripting embebido para extensiones Lua.
* `tracing` / `tracing-subscriber`: Observabilidad estructurada y logs.

---

## 2. Evaluación de REA e Ingeniería Inversa

* **Disponibilidad de Código Fuente:** El repositorio SAI dispone de su código fuente en Rust al 100% (código abierto, sin ofuscación ni binarios cerrados propietarios).
* **Evaluación de REA:** De acuerdo con la directriz del proyecto, herramientas de ingeniería inversa como REA solo se justificarían si existieran ejecutables compilados cuyo comportamiento interno no pudiera deducirse del código fuente. Dado que toda la lógica de contratos, bucles, esquemas y llamadas está visible en `crates/` y `src/`, **no fue necesario invocar REA ni alterar configuraciones de depuración binaria**.
* **Protección Legal y Atribución:** Se mantiene la atribución de licencia MIT a SHORiN-KiWATA para cualquier patrón o lógica adaptada.

---

## 3. Análisis Técnico de Capacidades Reales en SAI

A continuación se detalla la anatomía real de los 14 subsistemas de SAI a partir de sus módulos, funciones y contratos en Rust:

### 3.1 Bucle Agéntico (`src/agent/lifecycle.rs`, `src/agent/executor.rs`)
* **Contrato:** Estructura `AgentLifecycle` que ejecuta iterativamente un ciclo:
  1. `prepare_turn(context)`: Carga el estado de memoria y perfila el contexto.
  2. `call_provider(messages, tools)`: Invoca el LLM en streaming.
  3. `parse_tool_calls(response)`: Extrae llamadas estructuradas (`FunctionCall`).
  4. `dispatch_tools(calls)`: Ejecuta herramientas en paralelo o secuencial según dependencias.
  5. `evaluate_termination(result)`: Evalúa si el objetivo fue alcanzado o si se superó el límite de pasos (`max_turns`).
* **Observación para JESSYCA:** El bucle de SAI es determinista y no mezcla heurísticas de expresiones regulares con llamadas agénticas; desacopla el ciclo de vida del agente del canal de transporte (TUI/CLI).

### 3.2 Plan Mode (`src/plan/mod.rs`, `src/agent/plan_execution.rs`)
* **Implementación Real:**
  * Define un modelo estructurado `Plan`:
    ```rust
    pub struct Plan {
        pub id: String,
        pub goal: String,
        pub steps: Vec<PlanStep>,
        pub requires_approval: bool,
        pub status: PlanStatus,
    }
    ```
  * En modo plan (`plan_only`), el agente **no ejecuta acciones destructivas ni llamadas a herramientas ejecutivas**. Emite un plan desglosado en pasos (`steps`) con descripción, herramientas estimadas y dependencias.
  * Solo tras la aprobación explícita (`approve_plan`), el ejecutor pasa los pasos al bucle de ejecución supervisada.
* **Aportación a JESSYCA:** Resuelve la orden compuesta ambigua sin ejecutar a ciegas en el escritorio.

### 3.3 Progressive Tool Loading (`src/tools/progressive.rs`)
* **Problema que resuelve:** Enviar 40 herramientas completas con sus esquemas JSON al LLM en cada turno satura la ventana de contexto (hasta 4,000–8,000 tokens solo en definiciones) y degrada la precisión de selección.
* **Implementación en SAI:**
  * Define dominios funcionales (`ToolDomain`): `System`, `Web`, `Media`, `Desktop`, `File`, `Developer`.
  * Filtro de primer nivel: Analiza la intención del usuario y solo inyecta en el prompt los esquemas de las herramientas pertenecientes a los dominios activos.
  * Reduce el tamaño del system prompt de 35 KB a <6 KB en turnos normales.

### 3.4 Gestión de Herramientas (`src/tools/registry.rs`)
* **Contrato:**
  ```rust
  #[async_trait]
  pub trait Tool: Send + Sync {
      fn name(&self) -> &str;
      fn description(&self) -> &str;
      fn parameters_schema(&self) -> serde_json::Value;
      async fn execute(&self, args: serde_json::Value, ctx: &ToolContext) -> Result<ToolOutput, ToolError>;
  }
  ```
* Cada herramienta declara su esquema JSON Schema estricto. La validación se hace con `serde_json` antes de tocar el sistema operativo.

### 3.5 Context Compaction (`src/agent/compaction.rs`)
* **Algoritmo:**
  * Mantiene una métrica de tokens acumulados.
  * Cuando se alcanza el umbral de advertencia (ej. 75% del límite), divide el historial en tres segmentos:
    1. *System Prompt & Anchor Rules:* Inmutables.
    2. *Zona de Resumen:* Mensajes antiguos consolidados mediante un prompt de resumen ejecutivo.
    3. *Ventana Activa (Recent Turns):* Últimos N turnos conversacionales completos con salidas de herramientas intactas.
  * Trunca salidas excesivas de herramientas (stdout muy largos) a un puntero o resumen con hash.

### 3.6 Memoria de Conversación (`src/memory/mod.rs`)
* Memoria dividida en:
  * Memoria de trabajo en RAM (volátil durante la sesión).
  * Almacenamiento local persistente en SQLite o JSON estructurado para recuperar perfiles y preferencias.
* Los turnos almacenan metadatos explícitos de timestamps, tokens consumidos e IDs de paso.

### 3.7 Subagentes (`src/tools/subagent.rs`)
* Permite crear un subagente efímero (`spawn_subagent`) con:
  * Objetivo restringido.
  * Catálogo de herramientas acotado (ej. solo `web_fetch` y `web_search`).
  * Ventana de contexto aislada.
* El subagente ejecuta su tarea y devuelve únicamente un `SubagentResult` al agente padre, evitando contaminar la memoria principal.

### 3.8 Web Search (`src/tools/web_search/duckduckgo.rs`)
* Implementa búsqueda ligera sin API key obligatoria mediante DuckDuckGo HTML / Lite API.
* Limpia los resultados retornando únicamente título, URL y snippet condensado, protegiendo al agente de inyecciones de código HTML malicioso.

### 3.9 Web Fetch (`src/tools/web_fetch/html.rs`)
* Cliente HTTP con timeout estricto (10s), límites de tamaño de descarga (máx. 2 MB) y parseador de HTML a Markdown limpio (eliminando scripts, estilos, anuncios y menús).
* Evita desbordamiento de contexto al navegar por documentación o sitios web.

### 3.10 Gestión de Procesos (`src/process/manager.rs`)
* Encapsula la creación de procesos hijos (`tokio::process::Command`):
  * Aislamiento de variables de entorno.
  * Asignación de timeouts automáticos.
  * Captura separada de `stdout` y `stderr`.
  * Capacidad de matar procesos huérfanos o cancelar tareas (`kill_process`).

### 3.11 Model Context Protocol (MCP) (`src/mcp/client.rs`)
* Cliente de protocolo MCP (JSON-RPC 2.0 sobre `stdio`):
  * Negociación de capacidades (`initialize`).
  * Descubrimiento dinámico de herramientas provistas por servidores MCP externos (`tools/list`).
  * Enrutamiento seguro de `tools/call`.

### 3.12 Control de Escritorio mediante CUA (`src/tools/computer_use/driver.rs`)
* Módulo experimental para Computer Use:
  * Captura de pantalla a buffer en memoria.
  * Traducción de coordenadas normalizadas (0.0 a 1.0) a píxeles de pantalla.
  * Envío de eventos de ratón (`mouse_click`, `mouse_move`) y teclado (`key_tap`, `type_text`).
* En el caso de SAI, está en fase temprana y carece de las validaciones de riesgo y mitigación de falsos positivos que JESSYCA ya implementó en JDE.

### 3.13 Streaming de Respuestas (`src/provider/streaming.rs`)
* Canales asíncronos (`tokio::sync::mpsc`) para emitir fragmentos de tokens en tiempo real a la interfaz de usuario.
* Soporte SSE (Server-Sent Events) para Ollama y OpenAI compatibles.

### 3.14 Gestión de Errores y Reintentos (`src/agent/retry.rs`)
* Política de reintentos exponenciales con jitter para fallos de red y sobrecarga de tokens.
* Clasificación semántica de errores:
  * Errores irrecuperables (autenticación, permisos): Fallo inmediato y notificación.
  * Errores transitorios (timeout, desconexión): Reintento automático (hasta 3 veces).
  * Errores de parámetros de herramienta: Retroalimentación al LLM para autocorrección.

---

## 4. Conclusiones de la Inspección de Código

1. **Diseño Modular Excepcional:** SAI cuenta con una de las mejores arquitecturas agénticas para terminal/escritorio, especialmente en **Progressive Tool Loading**, **Plan Mode desacoplado** y **Context Compaction**.
2. **Independencia del Lenguaje:** Los conceptos clave de SAI son **patrones de diseño agénticos puros**, basados en contratos claros, JSON Schemas y máquinas de estado, no en trucos dependientes de Rust.
3. **Peligro de Segundo Cerebro:** Si SAI se ejecuta como un binario externo completo con su propio bucle y acceso al sistema, usurparía la autoridad de JESSYCA, rompiendo JDE, RiskEngine y la auditoría de seguridad.
4. **Viabilidad de Reutilización:** La adopción óptima es importar sus contratos y patrones arquitectónicos directamente al ecosistema de JESSYCA o a través de un puente controlado (`SaiBridge`).
