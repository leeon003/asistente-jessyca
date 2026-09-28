# JESSYCA PC — ANYDOC FASE 1 AUDIT REPORT

## 1. IDENTIFICACIÓN FORMAL DEL PROYECTO
* **Nombre Oficial:** Firecrawl AnyDoc
* **Repositorio Oficial:** `https://github.com/firecrawl/anydoc`
* **Licencia:** MIT (Copyright (c) 2026 Sideguide Technologies Inc.)
* **Lenguaje Principal:** Rust (Rust 2024 edition, rust-version = 1.88)
* **Arquitectura:** Núcleo Rust con bindings compilados mediante Maturin/PyO3 (`abi3-py310`) para Python y `@napi-rs/cli` para Node.js.
* **Versión Evaluada:** `0.2.4`
* **Paquete PyPI:** `firecrawl-anydoc` (0.2.4)
* **Paquete npm:** `@firecrawl/anydoc` (0.2.4)
* **Agent Skill:** `skills/convert-documents-to-markdown/SKILL.md`

---

## 2. FORMATOS DOCUMENTALES CUBIERTOS
AnyDoc procesa 18 extensiones mapeadas a los siguientes formatos principales:
* **Procesadores de Texto:** `.doc`, `.docx`, `.docm`, `.odt`, `.rtf`, `.epub`.
* **Hojas de Cálculo:** `.xls`, `.xlsx`, `.xlsm`, `.xlsb`, `.ods`, `.csv`.
* **Presentaciones:** `.ppt`, `.pptx`, `.pps`, `.ppsx`, `.odp`.
* **Documentos Portables:** `.pdf`.

---

## 3. ARQUITECTURA TÉCNICA Y FLUJO DE DATOS
```text
DOCUMENT BYTES
      ↓
FORMAT DETECTION (content markers binarios)
      ↓
FORMAT PARSER (cfb, quick-xml, zip, csv, encoding_rs, pdf-inspector)
      ↓
SHARED DOCUMENT MODEL (blocks, inlines, tables, footnotes, assets)
      ↓
GFM SERIALIZER (GitHub-Flavored Markdown)
      ↓
MARKDOWN (UTF-8)
```

---

## 4. INTEGRACIÓN Y RESTRICCIONES EN JESSYCA PC
* **Modo Actual:** `ANYDOC_MODE=LAB`.
* **Gobernanza:** Subordinación total al JESSYCA Decision Engine (JDE).
* **Consumo de VRAM:** 0 MB (100% CPU en Rust/C-ABI, preservando GPU RTX 3060).
* **Llamadas a Red en Modo Local:** 0 llamadas.
* **Procesos No Autorizados:** 0 procesos.
