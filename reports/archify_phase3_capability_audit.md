# REPORTE DE AUDITORÍA CRÍTICA DEL CAPABILITY REGISTRY — ARCHIFY FASE 3

**Sistema:** JESSYCA PC  
**Módulo:** Capability Registry & JDE Governance  
**Fase:** Fase 3 — Production Certification  
**Fecha:** 2026-09-27  
**Autoridad:** JESSYCA Decision Engine (JDE)  

---

## 1. RESUMEN EJECUTIVO DE AUDITORÍA

En cumplimiento estricto de la regla de la Sección 2 ("Auditoría Crítica del Capability Registry"), se auditó exhaustivamente el catálogo central de capacidades de JDE (`core/jde/capabilities.py`) respecto a los servicios provistos por Archify (`diagram_generation.*`).

Se constató que durante la Fase 2 se declararon formalmente certificadas cinco (5) capacidades de diagramación especializada (`architecture`, `workflow`, `sequence`, `dataflow`, `lifecycle`), las cuales poseen implementaciones completas, esquemas validados y pruebas reproducibles de renderizado interactivo en HTML/SVG.

Por el contrario, las entradas `diagram_generation.generic` y `diagram_generation.skill` que habían sido incorporadas en el catálogo de Fase 2:
1. **NO** poseen respaldo en los tipos canónicos admitidos por el adaptador (`ArchifyDiagramType`).
2. **NO** disponen de validadores estructurales diferenciados ni plantillas deterministas dedicadas.
3. Si un usuario o subagente invocaba `render_diagram(spec, diagram_type="generic")`, el motor rechazaba la operación por tipo no soportado.
4. `diagram_generation.skill` constituía un envoltorio genérico sobre la habilidad que carecía de tipado estricto e inducía riesgo de invocación no tipada.

### Decisión de Gobernanza JDE (Fase 3)
Conforme a la regla mandataria:
> *"Si generic o skill no tienen una certificación formal equivalente a las otras capacidades: NO deben quedar como ENABLED en producción. Deben pasar a DISABLED."*

Se modificó `core/jde/capabilities.py` para establecer incondicionalmente:
* `diagram_generation.generic`: **DISABLED** (`enabled=False`).
* `diagram_generation.skill`: **DISABLED** (`enabled=False`).

Únicamente las cinco capacidades certificadas con evidencia física demostrada permanecen **ENABLED** en producción.

---

## 2. MATRIZ DE CERTIFICACIÓN FORMAL DE CAPACIDADES

| Capability | Certificada | Production Enabled | Risk | Authority | Verification | Estado Operacional |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **architecture** | **SÍ** | **ENABLED** | LOW | LIMITED | ExecutionVerifier (HTML+SVG) | **PRODUCCIÓN** |
| **workflow** | **SÍ** | **ENABLED** | LOW | LIMITED | ExecutionVerifier (HTML+SVG) | **PRODUCCIÓN** |
| **sequence** | **SÍ** | **ENABLED** | LOW | LIMITED | ExecutionVerifier (HTML+SVG) | **PRODUCCIÓN** |
| **dataflow** | **SÍ** | **ENABLED** | LOW | LIMITED | ExecutionVerifier (HTML+SVG) | **PRODUCCIÓN** |
| **lifecycle** | **SÍ** | **ENABLED** | LOW | LIMITED | ExecutionVerifier (HTML+SVG) | **PRODUCCIÓN** |
| **generic** | **NO** | **DISABLED** | LOW | LIMITED | None (No certificada) | **BLOQUEADA** |
| **skill** | **NO** | **DISABLED** | LOW | LIMITED | None (No certificada) | **BLOQUEADA** |

---

## 3. DETALLE TÉCNICO DE CAPACIDADES CERTIFICADAS

### 3.1. `diagram_generation.architecture`
* **Acción canónica:** `render_architecture_diagram`
* **Herramienta:** `archify`
* **Propósito:** Genera topologías de arquitectura de software, microservicios, capas de infraestructura y dependencias de módulos.
* **Validación de IR:** Exige `nodes` con identificadores únicos y etiquetas legibles. Admite conexiones direccionales sin ciclos obligatorios.
* **Render:** Grid determinista de 3 columnas con espaciado uniforme y tema adaptativo.

### 3.2. `diagram_generation.workflow`
* **Acción canónica:** `render_workflow_diagram`
* **Herramienta:** `archify`
* **Propósito:** Modela pipelines de datos, procesos de negocio secuenciales, pasos de ejecución y flujos de aprobación.
* **Validación de IR:** Exige continuidad entre pasos con aristas ordenadas.

### 3.3. `diagram_generation.sequence`
* **Acción canónica:** `render_sequence_diagram`
* **Herramienta:** `archify`
* **Propósito:** Representa la interacción temporal entre actores y subsistemas (ej. Usuario → Core → JDE → Verifier).
* **Validación de IR:** Identifica participantes únicos y mensajes ordenados cronológicamente.
* **Fallback:** Mapeo 1:1 automático a `sequenceDiagram` de Mermaid ante degradación.

### 3.4. `diagram_generation.dataflow`
* **Acción canónica:** `render_dataflow_diagram`
* **Herramienta:** `archify`
* **Propósito:** Visualiza canales de datos, orígenes, transformaciones, colas y destinos.
* **Validación de IR:** Exige mapeo explícito de fuentes y sumideros.

### 3.5. `diagram_generation.lifecycle`
* **Acción canónica:** `render_lifecycle_diagram`
* **Herramienta:** `archify`
* **Propósito:** Modela diagramas de transición de estados y ciclos de vida de entidades del sistema (ej. estados de decisión JDE).
* **Validación de IR:** Exige estados válidos y transiciones consistentes.

---

## 4. ANÁLISIS DE EXCLUSIÓN: `generic` Y `skill`

1. **Inconsistencia de Esquema:** Archify es un motor determinista que calcula posiciones espaciales y semántica según el tipo de diagrama. No existe un layout "generic" óptimo; intentar forzar un diagrama genérico degradaba la calidad visual o fallaba silenciosamente.
2. **Principio de Mínimo Privilegio:** Exponer `tools.archify:render` de forma genérica permitía potenciales intentos de saltarse la clasificación de intención de JDE.
3. **Acción Tomada:** Ambas capacidades fueron registradas con `enabled=False`. La compuerta `JDEAuthorityGate` en modo `LIMITED` rechaza incondicionalmente cualquier solicitud dirigida a estas capacidades con el dictamen:
   ```text
   DENIED: Capacidad 'diagram_generation.<cap>' está deshabilitada en CapabilityRegistry.
   ```
4. **Verificación de Bloqueo:** Testeado en `tests/archify/test_archify_phase2_controlled.py::test_04_jde_capability_registry_integration` y `tests/archify/test_archify_phase3_certification.py::test_p3_17_production_denial_tests_active_mode`.

---

## 5. CONCLUSIÓN DEL AUDITOR
El Capability Registry de JDE ha sido purgado y blindado. Queda formalmente prohibida la activación de capacidades de diagramación no certificadas en producción.
