# JESSYCA PC — ANYDOC FASE 2
# REPORTE DE PERMISOS Y GOBERNANZA JDE

**Módulo:** AnyDoc Permission & Authority Verification  
**Fase:** Fase 2 — Controlled Integration  
**Fecha:** 2026-09-27  

---

## 1. PRINCIPIO DE AUTORIDAD ÚNICA (JDE = FULL AUTHORITY)

AnyDoc carece de cualquier autonomía de ejecución:
* Toda solicitud debe estar respaldada por una decisión formal del JDE (`DecisionResult`).
* Decisión `ALLOW`: Procede la conversión dentro del sandbox con validación previa de contrato sellado.
* Decisión `DENY`: La operación aborta inmediatamente con estado `DENIED`. No se produce lectura documental, no se crea output alguno, no se generan subprocesos y el contador de `side_effects` permanece en 0.

---

## 2. MATRIZ DE CAPACIDADES Y NIVELES DE RIESGO

| Capacidad | Riesgo | Permisos Requeridos | Puerta de Revisión | Decisión Default |
|---|---|---|---|---|
| `document_processing.convert` | `SAFE` | `fs:read`, `fs:write` | Verificación Automática | ALLOW |
| `document_processing.inspect` | `READ_ONLY` | `fs:read` | Verificación Automática | ALLOW |
| `document_processing.extract_structure` | `READ_ONLY` | `fs:read` | Verificación Automática | ALLOW |
| `document_processing.extract_assets` | `SAFE` | `fs:read`, `fs:write` | Evaluación de Riesgo | ALLOW (confinado) |
| `document_processing.detect_format` | `READ_ONLY` | `fs:read` | Verificación Automática | ALLOW |
| `document_processing.ocr_external` | `CRITICAL` | `net:outbound` | Prohibido | **DENY** |
| `document_processing.external_upload` | `CRITICAL` | `net:outbound` | Prohibido | **DENY** |
| `document_processing.document_write` | `HIGH` | `fs:write_arbitrary` | Prohibido | **DENY** |
| `document_processing.arbitrary` | `CRITICAL` | `os:exec` | Prohibido | **DENY** |

---

## 3. RECIBOS FORMALES DEL JDE (JDE RECEIPTS)

Cada tarea completada con éxito emite un recibo inmutable `AnyDocReceipt` que contiene:
* `receipt_id`: Identificador único del recibo.
* `decision_id`: Vínculo a la decisión formal del JDE.
* `operation_id`: Identificador de la operación AnyDoc.
* `task_id`: Identificador de la tarea de usuario.
* `input_hash`: SHA-256 del documento original.
* `output_hash`: SHA-256 del artefacto generado en el sandbox.
* `capability`: Capacidad ejecutada.
* `risk_level`: Nivel de riesgo evaluado.
* `verified`: Confirmación física del `ExecutionVerifier`.
* `status`: Estado final (`VERIFIED_SUCCESS`).
* `timestamp`: Marca de tiempo UNIX canónica.

Los recibos excluyen contenido sensible y sirven como bitácora forense de auditoría inmutable.
