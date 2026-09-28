# JESSYCA PC — ANYDOC FASE 1 SECURITY AUDIT

## 1. POSTURA DE SEGURIDAD Y CONFINAMIENTO
* **Confinamiento de Rutas (Path Traversal):** El adapter `AnyDocAdapter` aplica saneamiento mediante `os.path.realpath`, rechaza bytes nulos (`\x00`), secuencias `..` y `%2e%2e`, y bloquea explícitamente rutas del sistema operativo (`\windows\`, `\system32\`, `\etc\`).
* **Seguridad de Memoria:** Al ejecutarse el parser dentro de Rust, se eliminan vulnerabilidades de corrupción de memoria comunes en parsers C/C++ tradicionales (como Buffer Overflows o Use-After-Free).
* **Protección contra DoS / Bombas de Descompresión:**
  * `zipbomb.docx` fue contenido inmediatamente con `ResourceLimitError` (`word/document.xml declares 201326759 decompressed bytes`).
  * `deepxml.docx` fue contenido con `ResourceLimitError` (`element nesting exceeds 256`).

---

## 2. POLÍTICA DE RED (OFFLINE FIRST)
* En la ejecución estándar local, AnyDoc realiza **cero llamadas a red**.
* **Alerta sobre Hosted OCR:** La bandera `--ocr hosted` en la CLI o `ocr="hosted"` en la biblioteca despacha el documento completo vía HTTP POST a `https://api.firecrawl.dev/v2/parse`.
  * **Regla en JESSYCA:** En Fase 1 y en el runtime local, esta bandera está **terminantemente prohibida** y configurada en `ocr="reject"`. El uso de servicios OCR externos requerirá gobernanza expresa de JDE en fases futuras.

---

## 3. PROTECCIÓN CONTRA PROMPT INJECTIONS EN DOCUMENTOS
* Se validó que documentos que contienen texto imperativo hostil (ej. `"IGNORE JESSYCA SECURITY"`, `"RUN POWERSHELL"`) son tratados como **datos pasivos**.
* AnyDoc los serializa como celdas de tabla o cadenas literales Markdown sin evaluarlos ni pasarlos a subshell.
