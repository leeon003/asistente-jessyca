# Sanitización, Redacción de Secretos y Seguridad de Salida de Comandos — Jessyca Windows MCP (Subetapa 07.5)

## Visión General

La **Subetapa 07.5** implementa la capa de sanitización y redacción determinista de secretos de consola (`CommandOutputSanitizer`, `SecretRedactor`, `SanitizedCommandOutput`) para procesar `stdout` y `stderr` antes de ser expuestos externamente.

---

## GARANTÍA ABSOLUTA DE SEGURIDAD

```text
RAW COMMAND OUTPUT
        ↓
CommandOutputSanitizer (Normalización UTF-8 & Stripping ANSI)
        ↓
SecretRedactor (Redacción Determinista de Secretos)
        ↓
Output Size Limiter & Truncamiento Seguro
        ↓
SanitizedCommandOutput
        ↓
MCP / Audit / EventBus (EL OUTPUT CRUDO NUNCA ABANDONA LA FRONTERA INTERNA)
```

Las superficies externas (MCP Client, Tool Result, AuditLogger, EventBus, logs, memoria de sesión) reciben exclusivamente datos sanitizados o metadatos acotados.

---

## Patrones de Secretos Redactados

| Tipo de Secreto | Ejemplo de Entrada | Resultado Redactado |
|---|---|---|
| Contraseñas | `password=secret123` | `password=[REDACTED]` |
| API Keys | `api_key=sk_live_999` | `api_key=[REDACTED]` |
| Bearer Tokens | `Authorization: Bearer xyz123` | `Authorization: Bearer [REDACTED_BEARER_TOKEN]` |
| JWT Tokens | `eyJhbGciOi...` | `[REDACTED_JWT_TOKEN]` |
| Client Secrets | `client_secret=topsecret` | `client_secret=[REDACTED]` |
| Private Keys | `-----BEGIN PRIVATE KEY----- ...` | `[REDACTED_PRIVATE_KEY]` |
| Connection Strings | `Server=...;Password=secret;` | `Server=...;Password=[REDACTED];` |
| Windows Secrets | `Credential`, `AccessToken`, etc. | `Credential=[REDACTED]` |

---

## Componentes Principales

### 1. `SecretRedactor`
- Expresiones regulares compiladas, sin backtracking catastrófico, deterministas y thread-safe.
- Redacción case-insensitive de contraseñas, tokens, llaves privadas y URLs de bases de datos.
- Fail-Safe: En caso de excepción no controlada, devuelve `("[OUTPUT_REDACTION_FAILED]", 1)`.

### 2. `CommandOutputSanitizer`
- Eliminación de secuencias de escape ANSI (`\x1b[...]`).
- Normalización de codificación UTF-8 para bytes corruptos o caracteres de control.
- Sanitización independiente de `stdout` y `stderr`.
- Enforzamiento de límites de tamaño (`COMMAND_MAX_STDOUT_SIZE`, `COMMAND_MAX_STDERR_SIZE`).

### 3. `SanitizedCommandOutput` (`dataclass(frozen=True)`)
Modelo inmutable que almacena la salida sanitizada y metadatos operationales (`stdout_truncated`, `stderr_truncated`, `stdout_original_size`, `stderr_original_size`, `redactions_count`, `total_output_size`).
