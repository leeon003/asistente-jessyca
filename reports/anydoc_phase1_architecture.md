# JESSYCA PC — ANYDOC FASE 1 ARCHITECTURE & ERROR MODEL

## 1. PIPELINE DE CONVERSIÓN
AnyDoc se estructura como una canalización determinista:
1. **Format Detection:** Marcadores mágicos en encabezados binarios (PDF `%PDF-`, RTF `{\rtf`, OLE Compound Document Header `0xD0CF11E0A1B11AE1`, ZIP/OOXML `PK\x03\x04`).
2. **Format Parser:** Parsers modulares dedicados por tipo documental.
3. **Shared Document Model:** Estructura unificada en memoria compuesta por `blocks`, `inlines`, `tables`, `notes` y `assets`.
4. **GFM Serializer:** Serializador a Markdown GitHub-Flavored con saneamiento automático de saltos de línea y tablas.
5. **PDF Direct Pipeline:** Para PDFs nativos de texto, se emplea `pdf-inspector` para extraer Markdown estructurado directamente.

---

## 2. MODELO FORMAL DE ERRORES Y MAPEO JESSYCA
El núcleo de Rust expone variantes de `ConvertError`, mapeadas en Python a excepciones tipadas y en JESSYCA a `ConversionStatus`:

| Error AnyDoc | Causa Subyacente | Mapeo en JESSYCA |
| :--- | :--- | :--- |
| `UnsupportedError` | Formato desconocido o no soportado | `ConversionStatus.UNSUPPORTED` |
| `NeedsOcrError` | PDF escaneado o páginas basadas en imágenes | `ConversionStatus.NEEDS_OCR` |
| `MalformedError` | Archivo corrupto o sin estructura ZIP/OLE válida | `ConversionStatus.MALFORMED` |
| `EncryptedError` | Documento protegido por contraseña / cifrado | `ConversionStatus.ENCRYPTED` |
| `ResourceLimitError`| Exceso de profundidad XML (>256) o Zip Bomb | `ConversionStatus.RESOURCE_LIMIT` |
| `MissingPartError` | Falta una parte requerida para el documento | `ConversionStatus.MISSING_PART` |
| `Io` / `OSError` | Error de lectura física en disco | `ConversionStatus.IO_ERROR` |

---

## 3. SHARED DOCUMENT MODEL PARA CAPACIDADES FUTURAS (RAG / SEARCH)
La API expone `to_document(bytes, format)` que devuelve un objeto `Document` con:
* `blocks`: Párrafos, encabezados, tablas y listas tipadas.
* `notes`: Pies de página y notas al margen.
* `assets`: Metadatos de imágenes incrustadas.
Esto permitirá a JESSYCA en fases posteriores realizar indexación RAG con conocimiento estructural sin necesidad de re-parsear el Markdown.
