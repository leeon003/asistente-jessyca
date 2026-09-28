# JESSYCA PC — ANYDOC FASE 2
# REPORTE DE EXTRACCIÓN Y SANEAMIENTO DE ASSETS

**Módulo:** AnyDoc Asset Extraction & Media Confinement  
**Fase:** Fase 2 — Controlled Integration  
**Fecha:** 2026-09-27  

---

## 1. PRINCIPIOS DE EXTRACCIÓN DE ASSETS

Para documentos contenedores (como DOCX, PPTX u ODT), AnyDoc soporta la extracción selectiva de medios embebidos (imágenes y recursos). Esta capacidad (`document_processing.extract_assets`) está sujeta a rigurosas reglas de seguridad:

1. **Destino Exclusivo:** Los assets solo pueden escribirse dentro de `data/anydoc/output/<operation_id>/assets/`.
2. **Saneamiento Anti-Traversal:** Se elimina cualquier carácter que pueda provocar saltos de directorio (`..`, `/`, `\`). Los nombres se normalizan mediante regex `[^a-zA-Z0-9_\-\.]` reemplazando caracteres no seguros por `_`.
3. **Protección contra Archivos Ocultos / Dotfiles:** Archivos con nombres maliciosos como `.env` o `.git` son renombrados automáticamente con prefijo seguro `sanitized_`.
4. **Allowlist de Extensiones:** Solo se admiten extensiones multimedia seguras (`.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.svg`, `.webp`, `.bin`). Cualquier extensión no autorizada o ejecutable (`.exe`, `.ps1`, `.bat`) se neutraliza transformándola a `.bin`.
5. **Verificación de Confinamiento:** El `realpath` del asset generado debe encontrarse estrictamente dentro del subdirectorio `assets/` correspondiente. Si el archivo escapa, se omite.
6. **Hashes Individuales:** Cada asset extraído cuenta con su propio SHA-256 y tamaño exacto en bytes registrado en los metadatos del resultado.

---

## 2. RESULTADOS DE LA CERTIFICACIÓN

* **Extracción de DOCX (`simple.docx`):** Extracción exitosa de `image1.png` (70 bytes, SHA-256 verificado, confinado en su carpeta de salida).
* **Prueba con Nombres Maliciosos (`../../evil.exe`, `.env`):** Sanitizados adecuadamente sin escape del sandbox y sin sobrescritura de archivos del sistema.
* **Cero Riesgo de Inyección:** La extracción de assets no compromete la inmutabilidad del sistema de archivos.
