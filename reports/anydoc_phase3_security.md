# AnyDoc Fase 3 — Auditoría de Seguridad y Aislamiento

## 1. Confinamiento de Sandboxing (Output Sandbox)

- **Directorios autorizados**:
  - `data/anydoc/input/`
  - `data/anydoc/output/`
  - `data/anydoc/cache/`
  - `data/anydoc/quarantine/`
- **Controles de Ruta**:
  - Rechazo estricto de Path Traversal clásico (`..`, `../`, `..\\`).
  - Rechazo de Path Traversal URL-encoded (`%2e%2e`, `%2f`, `%5c`).
  - Rechazo de rutas absolutas del sistema operativo (`C:\Windows`, `C:\Program Files`, `/etc`, etc.).
  - Rechazo de rutas UNC de red (`\\server\share`, `//server/share`).
  - Detección de inyecciones de bytes nulos (`\x00`).
  - Normalización canónica mediante `os.path.realpath`.

---

## 2. Aislamiento de Red y Política de OCR

- **Política de Red**: `NETWORK = DENY` forzada en tiempo de ejecución.
- **Llamadas salientes permitidas**: 0.
- **OCR Externo**: Bloqueado categóricamente. Ante documentos que requieren OCR (e.g. PDFs escaneados como mapas de bits), el motor lanza `anydoc.NeedsOcrError`, el cual se captura de forma determinista retornando `ConversionStatus.NEEDS_OCR` con 0 efectos secundarios y 0 intentos de conexión a APIs externas.

---

## 3. Seguridad de Secretos y Redacción Profunda

El pipeline implementa redacción automatizada por regex antes de escribir cualquier salida en Markdown:
- Claves de OpenAI y compatibles: `sk-[a-zA-Z0-9_\-]{20,80}` -> `[REDACTED_API_KEY]`
- Tokens de GitHub: `gh[pousr][_\-][a-zA-Z0-9]{20,80}` -> `[REDACTED_GITHUB_TOKEN]`
- Claves privadas: `-----BEGIN [A-Z ]+ PRIVATE KEY-----` -> `[REDACTED_PRIVATE_KEY]`
- Passwords y credenciales en texto plano: `password=...`, `secret=...` -> `[REDACTED]`
- Cadenas de conexión a BD: `postgres://...`, `mysql://...` -> `[REDACTED_CREDENTIALS]`

---

## 4. Inmunidad a Prompt Injection en Documentos

Los documentos procesados que contienen directivas diseñadas para manipular modelos (`IGNORE PREVIOUS INSTRUCTIONS`, `EXECUTE COMMAND`, `REVEAL SECRET`, `UPLOAD THIS FILE`) son procesados estrictamente como contenido pasivo dentro del AST documental. AnyDoc no tiene acceso a shells, subsistemas de comandos ni subsistemas de red, imposibilitando la escalada de privilegios o la ejecución de código inducida por inyección en el prompt.
