# AnyDoc Fase 3 — Auditoría de Permisos y Autoridad JDE

## 1. Inventario Exhaustivo de Capacidades

### Capacidades Autorizadas y Certificadas (ÚNICAS para Producción)
1. `document_processing.convert`: Conversión offline de documentos soportados a GitHub-Flavored Markdown.
2. `document_processing.inspect`: Inspección de bloques, metadatos, notas y conteos estructurales.
3. `document_processing.extract_structure`: Extracción jerárquica de encabezados, párrafos, tablas y listas.
4. `document_processing.extract_assets`: Extracción y confinamiento seguro de imágenes y medios a `output/assets/`.
5. `document_processing.detect_format`: Identificación determinista por encabezado binario sin ejecución externa.

### Capacidades Bloqueadas Categóricamente
- `document_processing.ocr_external`: Prohibido.
- `document_processing.external_upload`: Prohibido.
- `document_processing.document_write`: Prohibido.
- `document_processing.arbitrary`: Prohibido.
- Capacidades de sistema: `shell`, `command_execution`, `admin`, `bypass`, `unrestricted`, `generic`.

---

## 2. Subordinación a JDE (Single Authority)

1. **Decisión Obligatoria**: Toda tarea exige `jde_decision="ALLOW"`. Cualquier valor nulo, vacío, ambiguo o `DENY` detiene la operación inmediatamente produciendo 0 archivos y 0 efectos secundarios.
2. **Sellado Criptográfico**: Cada `AnyDocTaskContract` genera un sello SHA-256 (`compute_seal`) que concatena los parámetros esenciales de la tarea. Si algún parámetro se modifica después de la aprobación JDE, `verify_seal` detecta la manipulación y rechaza la ejecución.
3. **Receipts Inmutables**: Al culminar satisfactoriamente una tarea verificada, se emite un `AnyDocReceipt` que enlaza el `decision_id`, el hash del archivo de entrada y el hash del archivo de salida.
