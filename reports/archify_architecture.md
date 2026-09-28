# ARQUITECTURA DE INTEGRACIÓN: JESSYCA ↔ ARCHIFY

**Fecha:** 2026-09-27  
**Autor:** Arquitecto Principal JESSYCA PC  
**Fase:** Fase 1 — Laboratorio y Aislamiento

---

## 1. PRINCIPIO FUNDAMENTAL DE AISLAMIENTO

Archify se incorpora como una **capacidad satélite de visualización técnica**, completamente aislada del Core de JESSYCA.

```text
USER PROMPT ("Explica la arquitectura del proyecto en un diagrama interactivo")
   ↓
JESSYCA LOCAL AGENT (Analiza el código y propone JSON de arquitectura)
   ↓
JDE DECISION ENGINE (Autoridad de Decisión: autoriza generación de artefacto)
   ↓
RISK ENGINE (Clasifica como SAFE: solo lectura de código y escritura de HTML en sandbox)
   ↓
PERMISSION MANAGER (Verifica permiso 'tools:archify')
   ↓
IDEMPOTENCY GUARD (Previene recompilaciones innecesarias del mismo diagrama)
   ↓
JESSYCA ARCHIFY ADAPTER (`core/archify/adapter.py`)
   ↓
ARCHIFY RENDERER / VALIDATOR ENGINE
   ↓
GENERATED ARTIFACT (`data/archify/diagram_<id>.html`)
   ↓
EXECUTION VERIFIER (Comprueba creación efectiva, tamaño y formato HTML válido)
   ↓
JDE RECEIPT & AUDIT TRAIL
   ↓
USER RESPONSE (Enlace interactivo o visualización en navegador)
```

---

## 2. MODOS DE OPERACIÓN DEL ADAPTER

El `JessycaArchifyAdapter` implementa 3 modos estrictos de operación controlados por configuración:

1. `OFF`: El adaptador está completamente deshabilitado. Cualquier petición retorna `UNSUPPORTED`.
2. `SHADOW` (**Modo por defecto de Fase 1**):
   * Valida la especificación JSON del diagrama.
   * Compara la propuesta de Archify contra la salida estándar de JESSYCA (ej. Mermaid o descripciones de texto).
   * Registra métricas de viabilidad, sintaxis y colisiones.
   * **NO** abre navegadores ni sustituye la respuesta de producción.
3. `ACTIVE` (Reservado para fases posteriores):
   * Compila el HTML y lo guarda en la ruta autorizada del usuario/proyecto.

---

## 3. ESPECIFICACIÓN DEL ADAPTER (`core/archify/adapter.py`)

El adaptador ofrece los siguientes métodos estándar:
* `health_check() -> dict[str, Any]`: Comprueba disponibilidad de Node.js, entorno de ejecución y schemas.
* `get_capabilities() -> list[str]`: Retorna los tipos de diagramas soportados (`architecture`, `workflow`, `sequence`, `dataflow`, `lifecycle`).
* `validate_spec(spec: dict[str, Any], diagram_type: str) -> tuple[bool, str, dict[str, Any]]`: Valida la estructura y coherencia del diagrama.
* `render_diagram(spec: dict[str, Any], diagram_type: str, output_path: str) -> tuple[bool, str]`: Genera el archivo HTML autocontenido de forma determinista.
* `observe_shadow(user_intent: str, proposed_spec: dict[str, Any]) -> dict[str, Any]`: Ejecuta la evaluación en Shadow Mode.

---

## 4. GOBERNANZA DE RECURSOS Y VRAM

Archify no ejecuta modelos de Machine Learning propios:
* **VRAM Overhead:** **0 MB**. No compite con Ollama ni satura la GPU RTX 3060.
* **CPU Overhead:** Compilación ligera por lotes (habitualmente < 200ms por diagrama).
* **Concurrencia:** Bloqueo de concurrencia en escritura de archivos para evitar condiciones de carrera.
