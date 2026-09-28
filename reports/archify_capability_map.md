# MAPA DE CAPACIDADES: JESSYCA ↔ ARCHIFY

**Fecha:** 2026-09-27  
**Autor:** Arquitecto Principal JESSYCA PC  
**Objetivo:** Contrastar cada capacidad de Archify contra el ecosistema actual de JESSYCA para categorizar aportes, evitar duplicaciones y definir la gobernanza de JDE y Verification.

---

## 1. CLASIFICACIÓN DE CAPACIDADES DE ARCHIFY

| Capacidad de Archify | ¿Aporta valor nuevo a JESSYCA? | Clasificación | Relación con JESSYCA | ¿Requiere JDE? | ¿Requiere Verifier? |
|---|---|---|---|---|---|
| **Compilación de Diagramas HTML Interactivos** | Sí. JESSYCA solo producía texto, markdown o llamadas MCP/Browser. No generaba artefactos HTML interactivos con SVG embebido, zoom, pan y trazado de rutas. | `USEFUL` | Complementa la suite de visualización y documentación. | **SÍ** (Autoriza generación y destino) | **SÍ** (Verifica archivo HTML generado y válido) |
| **Validación de Layout Estructural (Anti-Overlap)** | Sí. Verifica determinísticamente colisiones de nodos, cruce de líneas y calidad de representación. | `COMPLEMENTARY` | Mejora la fidelidad técnica frente a diagramas Mermaid básicos generados por LLM. | **NO** (Es interna de Archify) | **SÍ** (Comprueba receipt de validación JSON) |
| **Exportación a PNG/SVG/WebM** | Sí. Genera formatos exportables directamente para compartir. | `COMPLEMENTARY` | Amplía las herramientas de exportación de documentos. | **SÍ** | **SÍ** |
| **Inspección / Análisis de Código Fuente** | No. JESSYCA ya tiene herramientas avanzadas de filesystem (`files.search`, `files.read`, ripgrep, AST parsing). | `DUPLICATE` | JESSYCA Core/LLM realiza el análisis; Archify solo recibe el JSON resultante. | **SÍ** | **SÍ** |
| **Toma de Decisiones o Ejecución de Acciones en el Host** | No. Archify carece de agentes, control de SO y ejecución de comandos. | `NOT_RELEVANT` | JDE y Skills existentes mantienen la exclusividad de ejecución y decisión. | N/A | N/A |
| **Almacenamiento / Base de Datos Propia** | No. Archify es stateless. | `NOT_RELEVANT` | JESSYCA preserva su propia memoria y base de datos SQLite. | N/A | N/A |

---

## 2. MATRIZ DE INTEGRACIÓN JESSYCA ↔ ARCHIFY

```text
Archify Capability: Generación de Diagramas de Arquitectura / Workflow / Secuencia
        ↓
JESSYCA Component: `ArchifySkill` / `JessycaArchifyAdapter`
        ↓
Integration Method: Subprocess seguro / Template Renderer local / CLI JSON Bridge
        ↓
Security Layer: RiskEngine (SAFE/LOW) + PermissionManager (`tools.archify`) + IdempotencyGuard
        ↓
Verification Method: ExecutionVerifier comprobando existencia física de HTML, integridad y tamaño > 0
        ↓
Priority: Media-Alta (Potente acelerador visual sin riesgo operativo)
```

---

## 3. ANÁLISIS DE NO DUPLICACIÓN

1. **Memoria y Contexto:** Archify no gestionará memoria. Los datos residen en la base de datos de sesiones y memoria de JESSYCA (`data/sessions.db`).
2. **Razonamiento:** El LLM local (Ollama / Gemma / Llama) es el que analiza el código del usuario y produce la especificación intermedia JSON. Archify actúa exclusivamente como **compilador determinista de visualización**.
3. **Control del Sistema:** Toda interacción con el disco (escribir el HTML en la carpeta de reportes o artefactos) es gobernada por el `JessycaArchifyAdapter` y verificada por el `ExecutionVerifier`.
