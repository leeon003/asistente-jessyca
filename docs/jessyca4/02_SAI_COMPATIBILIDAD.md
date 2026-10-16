# JESSYCA 4.0 — FASE 2: MATRIZ DE COMPATIBILIDAD E INTEGRACIÓN ARQUITECTÓNICA

**Fecha:** 16 de Octubre de 2026  
**Proyecto:** JESSYCA Asistente Personal  
**Componente Evaluado:** SAI (Rust) vs. Núcleo JESSYCA (JDE, RiskEngine, PermissionManager, ExecutionVerifier)

---

## 1. Principio Fundamental de Autoridad y Gobernanza

En JESSYCA 4.0 rige una regla estricta:
> **La autoridad de ejecución debe residir única y exclusivamente en JESSYCA mediante JDE, RiskEngine y PermissionManager.**  
> Ningún componente externo, puente agéntico o runtime auxiliar (incluyendo SAI Rust) debe convertirse en un "segundo cerebro" con control directo o no supervisado del sistema operativo Windows.

Cualquier arquitectura que delegue en un binario externo la facultad de ejecutar scripts, llamadas al sistema o pulsaciones de teclado sin pasar por la cadena de auditoría de JDE representa una vulnerabilidad crítica que invalida los avances de seguridad logrados en la Fase 1.

---

## 2. Matriz de Compatibilidad entre Capacidades de SAI y JESSYCA

| Capacidad SAI | Estado en SAI Rust | Compatibilidad con JESSYCA | Estrategia de Integración Recomendada | Riesgo de Segundo Cerebro |
|---|---|---|---|---|
| **Bucle Agéntico** | Tokio async loop rígido | **Incompatible directamente**: SAI asume control total del bucle y de la TUI/CLI. | **Adaptar patrón en Python**: Mantener el orquestador y ciclo de vida en JESSYCA, adoptando la máquina de estados de SAI. | **ALTO** si corre como binario independiente. |
| **Plan Mode** | Genera `Plan` estructurado sin ejecutar | **100% Compatible conceptualmente**: Enlaza directamente con la necesidad de desarmar órdenes compuestas. | **Implementar vía `SaiBridge`**: El plan se genera como propuesta de datos estructurados, pero la aprobación y ejecución la gobierna JDE. | **NULO**: Modo plan es de solo lectura y planificación. |
| **Progressive Tool Loading** | Filtrado por `ToolDomain` antes del prompt | **100% Compatible y Crítico**: Resuelve la sobrecarga de tokens en modelos locales (Llama 3.2 3B). | **Integración Nativa**: `ProgressiveToolCatalog` preselecciona dominios (`system`, `browser`, `media`, `files`, `documents`) reduciendo el prompt de 35KB a <6KB. | **NULO**: Optimización pura de contexto. |
| **Gestión de Herramientas** | Traits Rust (`Tool`) con `serde_json` | **Parcialmente Compatible**: JESSYCA utiliza `@skill` decorados en Python con `inspect`. | **Normalizar Esquemas**: Exponer contratos JSON Schema idénticos para que cualquier planificador los entienda de forma unificada. | **MEDIO** si la herramienta ejecuta sin token JDE. |
| **Context Compaction** | Sliding window + resumen ejecutivo | **100% Compatible**: JESSYCA carecía de compactación inteligente estructurada, saturando ventanas de 8K. | **Adaptar algoritmo en Python**: Implementado en `SaiBridge.compact_context`, preserva reglas ancla, resume turnos intermedios y mantiene últimos N turnos. | **NULO**: Manejo de memoria en memoria. |
| **Memoria de Conversación** | In-memory + SQLite | **Compatible**: JESSYCA ya cuenta con `core/memory/` pero requería etiquetado de tokens y pasos. | **Enriquecer metadatos**: Unificar metadatos de turnos con los formatos de SAI. | **BAJO** |
| **Subagentes** | Contextos aislados en Tokio | **Compatible como concepto**: Permite investigaciones web sin contaminar el contexto principal. | **Subagentes supervisados en JDE**: Tareas de exploración web o lectura de documentos se delegan a un subagente efímero sin permisos de escritorio. | **MEDIO** si el subagente intenta ejecutar comandos. |
| **Web Search & Fetch** | DuckDuckGo HTTP + Parser HTML a MD | **100% Compatible**: Reemplaza scrapers pesados o dependencias frágiles de Selenium con llamadas ligeras limpias. | **Módulo Python Nativo**: `requests` / `httpx` + `html2text` respetando timeouts de 10s y límites de 2MB. | **BAJO** |
| **Gestión de Procesos** | `tokio::process::Command` | **Incompatible con modelo actual**: JESSYCA requiere auditoría por `RiskEngine` antes de `subprocess.Popen`. | **Delegación estricta**: Los procesos deben instanciarse a través del gestor de permisos de JESSYCA (`core/security/`). | **ALTO** |
| **Model Context Protocol (MCP)** | JSON-RPC 2.0 sobre `stdio` | **Altamente Deseable**: Permite extender herramientas sin tocar el núcleo. | **Adoptar cliente MCP estándar**: Adaptador Python asíncrono para servidores MCP. | **MEDIO**: Requiere autenticación de servidores MCP. |
| **Computer Use (CUA)** | Screenshots + mouse/keyboard events | **Incompatible directamente**: SAI carece de visión por computadora avanzada, verificación visual post-clic y parada de emergencia. | **Mantener CUA de JESSYCA / Agent-S**: JESSYCA cuenta con `ExecutionVerifier`, validación de coordenadas y `emergency_stop`. | **CRÍTICO** si SAI toma el control del cursor. |
| **Streaming & Retry** | Tokio mpsc + Exponential backoff | **100% Compatible**: Mejora la experiencia en UI y la resiliencia ante caídas de Ollama. | **Incorporar en el cliente Ollama de JESSYCA**. | **NULO** |

---

## 3. Modelo de Seguridad y Cadena de Mando (JDE First)

Para garantizar que el componente SAI nunca vulnere el sistema, se define la siguiente cadena de mando unidireccional:

```
[ Usuario (Voz / Texto / GUI) ]
              │
              ▼
[ JESSYCA Core / Main Assistant ]
              │
              ├──► ¿Orden Compleja / Planificación? ──► [ SaiBridge (Advisory & Planning) ]
              │                                                │
              │                                         (Retorna Plan Propuesto)
              │                                                │
              ▼                                                ▼
     [ RiskEngine & PermissionManager ] ◄──────────────────────┘
              │  (Evalúa Riesgo de cada Paso)
              ▼
    ¿Requiere Confirmación?
        ├── SI ──► [ Solicita Aprobación al Usuario ]
        └── NO ──► [ Token de Autorización JDE Emitido ]
                         │
                         ▼
             [ JDE Execution Dispatcher ]
                         │
                         ├──► Skill Nativa (Audio, Apps, Browser)
                         ├──► Computer Use (CUA con Anti-False Success)
                         └──► Tarea en Background Supervisada
                                 │
                                 ▼
                     [ ExecutionVerifier ] ──► (Valida Estado Real en Windows)
```

### Reglas de Bloqueo Innegociables:
1. **Ninguna ejecución directa desde SAI:** `SaiBridge` nunca invoca `subprocess`, `os.system` ni llamadas Win32 directamente. Solo produce estructuras de datos validadas (`Plan`, `ToolSelection`, `ContextSummary`).
2. **Tokens de Autorización JDE:** Cada paso de un plan originado en SAI debe canjearse por un token de autorización emitido por `RiskEngine`. Si el usuario rechaza o el riesgo es crítico, el paso se aborta inmediatamente.
3. **Emergency Stop Primario:** Si se activa el botón de pánico (`emergency_stop`), se interrumpe de inmediato tanto la ejecución en JDE como cualquier trabajo registrado en `SaiBridge`.
4. **Verificación Anti-Falso Éxito:** Ningún paso de planificación se marca como completado solo porque el proceso terminó con código 0; requiere confirmación por `ExecutionVerifier` (ej. ventana visible, cambio de volumen, archivo verificado).

---

## 4. Conclusión de Compatibilidad

* La **Alternativa A (Adaptación Nativa de Patrones SAI a Python con `SaiBridge`)** ofrece **100% de compatibilidad**, cero fricción de compilación en Windows, máxima observabilidad y pleno respeto a la cadena de custodia de seguridad.
* La **Alternativa B (Ejecución de Binario Rust)** introduce una barrera operativa crítica en este entorno (falta de toolchain Rust/Cargo), latencia IPC innecesaria y el peligro latente de crear un segundo cerebro incontrolable.
