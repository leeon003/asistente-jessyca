# Herramientas de Sistema de Archivos Seguro — Jessyca Windows MCP (Subetapa 06.2)

## Visión General

La **Subetapa 06.2** introduce la primera implementación real de herramientas de Windows en Jessyca: el dominio `windows.files`.

Todas las operaciones de archivo (`list_directory`, `read_file`, `write_file`, `create_directory`, `delete_file`) operan obligatoriamente bajo aislamiento estricto de **Sandbox** (`FILESYSTEM_SANDBOX_ROOT`), validación exhaustiva de **Path Security Layer** y total interceptación determinista por parte del **SecureExecutionPipeline** (04.1–06.1).

---

## Flujo Completo de Seguridad e Interceptación

```text
MCP Client Payload
    ↓
RequestContext (Aislamiento de Entradas No Confiables - FORBIDDEN_CLIENT_OVERRIDE_KEYS)
    ↓
ExecutionRequest (Inmutable)
    ↓
CapabilityResolver (06.1 - Valida capability declarada windows.files)
    ↓
[CAPABILITY_RESOLVED Audit Event]
    ↓
PathSecurityManager (tools/filesystem/path_security.py)
    ├─ Verificación de Descendencia del Sandbox (os.path.commonpath)
    ├─ Canonicalización realpath (os.path.realpath)
    ├─ Bloqueo de Traversal (../, ..\, %2e%2e, null bytes)
    ├─ Bloqueo de Rutas UNC (\\server) y Extendidas (\\?\, \\.\)
    └─ Verificación de Symlinks / Junctions / Reparse Points a Rutas Externas
    ↓
[FILESYSTEM_PATH_VALIDATED Audit Event]
    ↓
SecureExecutionPipeline (Orquestador Central)
    ├─ RiskEngine (04.2)
    ├─ SecurityPolicyEvaluator (04.5)
    ├─ PermissionManager (04.3)
    ├─ SecurityDecisionAggregator (Decision = most_restrictive)
    └─ ConfirmationManager (04.4 - Exigido para delete_file / write_file)
    ↓
AuthorizationEvidence (Binding Criptográfico SHA-256)
    ↓
SecureExecutionBoundary (05.2 - Validador de Fingerprint e Integridad)
    ↓
WindowsFilesystemToolExecutor (Ejecución Real en Sandbox)
    ↓
[FILESYSTEM_OPERATION_SUCCEEDED / FAILED Audit Event]
    ↓
EventBus: filesystem:completed / filesystem:denied
```

---

## Operaciones Soportadas y Niveles de Riesgo

| Operación | Riesgo Declarado | Decisión por Defecto | Requiere Confirmación | Límites de Seguridad |
|---|---|---|---|---|
| `list_directory` | `SAFE` | `ALLOW` | No | Máx. 1000 entradas (`FILESYSTEM_MAX_LIST_ENTRIES`) |
| `read_file` | `SAFE` | `ALLOW` | No | Máx. 5 MB (`FILESYSTEM_MAX_READ_SIZE`) |
| `create_directory` | `WARNING` | `REQUIRE_CONFIRMATION` | Sí | Restringido al Sandbox |
| `write_file` | `WARNING` | `REQUIRE_CONFIRMATION` | Sí | Escritura atómica (temp + replace), Máx. 10 MB (`FILESYSTEM_MAX_WRITE_SIZE`) |
| `delete_file` | `DANGEROUS` | `REQUIRE_CONFIRMATION` | Sí | **Solo archivos regulares** (no directorios ni enlaces) |

---

## Path Security Layer (`tools/filesystem/path_security.py`)

1. **Tratamiento de Rutas como UNTRUSTED INPUT**: Toda ruta recibida del cliente MCP o LLM es tratada como no confiable.
2. **Canonicalización Obligatoria**: Resuelve rutas reales con `os.path.realpath`.
3. **Pertenencia al Sandbox**: Garantiza `os.path.commonpath([sandbox_root, canonical_target]) == sandbox_root`.
4. **Protección TOCTOU**: Las escrituras se realizan en un archivo temporal dentro del mismo directorio padre antes del reemplazo atómico `os.replace()`.
5. **Sanitización en Audit Logs**: Se registran metadatos de lectura/escritura (`path`, `size`, `encoding`), pero **nunca contenidos ni secretos sensibles**.
