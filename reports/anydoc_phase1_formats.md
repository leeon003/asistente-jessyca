# JESSYCA PC — ANYDOC FASE 1 FORMATS & CONVERSION MATRIX

## RESULTADOS DE CONVERSIÓN EN FIXTURES REALES

| Formato | Fixture Evaluada | Tamaño Entrada | Salida Markdown | Detección Contenido | Estado |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **CSV** | `simple.csv` | 210 bytes | 294 caracteres | N/A (por extensión) | **SUCCESS** |
| **DOCX** | `simple.docx` | 10,159 bytes | 1,291 caracteres | **PASS** (PK ZIP marker) | **SUCCESS** |
| **XLSX** | `simple.xlsx` | 7,106 bytes | 396 caracteres | **PASS** (PK ZIP marker) | **SUCCESS** |
| **PPTX** | `simple.pptx` | 15,734 bytes | 273 caracteres | **PASS** (PK ZIP marker) | **SUCCESS** |
| **PDF** | `simple.pdf` | 90,060 bytes | 1,070 caracteres | **PASS** (`%PDF-` marker) | **SUCCESS** |
| **RTF** | `simple.rtf` | 20,136 bytes | 1,296 caracteres | **PASS** (`{\rtf` marker) | **SUCCESS** |
| **ODT** | `simple.odt` | 25,489 bytes | 1,297 caracteres | **PASS** (PK mimetype) | **SUCCESS** |
| **EPUB** | `simple.epub` | 6,167 bytes | 757 caracteres | **PASS** (PK container) | **SUCCESS** |

---

## CONVERSIÓN CON EXTENSIÓN ALTERADA (CONTENT DETECTION)
* Archivo `simple.docx` renombrado como `disguised_docx.pdf`:
  * `format_from_bytes(data)`: detectó `docx`.
  * Conversión exitosa de 1,291 caracteres Markdown sin errores.
* Archivo `simple.pdf` renombrado como `disguised_pdf.docx`:
  * `format_from_bytes(data)`: detectó `pdf`.
  * Conversión exitosa de 1,070 caracteres Markdown sin errores.
