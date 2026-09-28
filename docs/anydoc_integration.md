# GUÍA DE INTEGRACIÓN Y ESPECIFICACIÓN: ANYDOC

**Sistema:** JESSYCA PC  
**Módulo:** Integración AnyDoc (Firecrawl AnyDoc)  
**Fase:** Fase 3 — Certificación Final y Activación en Producción  
**Estado:** `ACTIVE / PRODUCTION CERTIFIED`  
**Autoridad:** JESSYCA Decision Engine (JDE)  
**Fecha:** Septiembre 2026  

---

## 1. Overview y Propósito

Este documento define la arquitectura, contratos formales y directrices operativas de **Firecrawl AnyDoc** en JESSYCA PC como motor de procesamiento y conversión documental a GitHub-Flavored Markdown (GFM).

AnyDoc resuelve de manera nativa y con altísimo rendimiento la lectura e inspección de documentos ofimáticos (`.doc`, `.docx`, `.xls`, `.xlsx`, `.ppt`, `.pptx`, `.odt`, `.ods`, `.odp`, `.rtf`, `.epub`, `.csv`, `.pdf`) sin requerir suites ofimáticas pesadas (como LibreOffice) ni microservicios externos.

---

## 2. Arquitectura de Integración Gobernada

```text
USER
  ↓
JESSYCA CORE
  ↓
JDE (Autoridad Única)
  ↓
RISK ENGINE
  ↓
PERMISSION MANAGER
  ↓
IDEMPOTENCY GUARD
  ↓
ANYDOC ADAPTER
  ↓
ANYDOC ENGINE (Rust Core Offline)
  ↓
OUTPUT SANDBOX (data/anydoc/)
  ↓
EXECUTION VERIFIER
  ↓
JDE RECEIPT
  ↓
JESSYCA
```

El LLM jamás puede eludir esta cadena de gobernanza.

---

## 3. Capacidades Certificadas para Producción

Bajo gobernanza del JDE, las siguientes 5 capacidades documentales son las ÚNICAS autorizadas:
1. `document_processing.convert`: Conversión local y offline de documentos a Markdown dentro del sandbox.
2. `document_processing.inspect`: Inspección no invasiva de metadatos, bloques, notas y assets.
3. `document_processing.extract_structure`: Extracción estructurada de encabezados, párrafos, tablas y listas.
4. `document_processing.extract_assets`: Extracción y confinamiento seguro de medios a `output/assets/`.
5. `document_processing.detect_format`: Identificación binaria de formato mediante cabeceras deterministas.

### Capacidades Prohibidas y Deshabilitadas Categóricamente:
* `document_processing.ocr_external` -> **DISABLED / STRICTLY FORBIDDEN**
* `document_processing.external_upload` -> **DISABLED / STRICTLY FORBIDDEN**
* `document_processing.document_write` -> **DISABLED / STRICTLY FORBIDDEN**
* `document_processing.arbitrary` -> **DISABLED / STRICTLY FORBIDDEN**
* Capacidades genéricas, administrativas, shells o de red externa -> **BLOCKED**

---

## 4. Control de Modos y Seguridad

* **Modos Soportados:** `OFF`, `LAB`, `SHADOW`, `CONTROLLED`, `ACTIVE`.
* **Modo Productivo Certificado:** `ACTIVE` (habilitado formalmente tras superar la suite de certificación con 0 fallas y 0 regresiones).
* **Sandbox Confinado:** `data/anydoc/{input,output,cache,quarantine}`.
* **Política de Red:** `NETWORK = DENY` (forzado en `ocr="reject"`; 0 llamadas remotas).
* **Integridad de Entrada:** Inmutabilidad verificada mediante `SHA256(input BEFORE) == SHA256(input AFTER)`.
* **Idempotencia:** Huella canónica SHA-256 (`input_hash`, `operation`, `allowed_actions`, `version`, `config`).
* **Verificación Física:** Distinción taxativa entre `CLAIMED_SUCCESS`, `VERIFIED_SUCCESS` y `VERIFICATION_FAILED` mediante `ExecutionVerifier`.
* **Mecanismo de Rollback:** En caliente vía `adapter.set_mode(AnyDocMode.CONTROLLED)` o `adapter.kill_switch()`.
