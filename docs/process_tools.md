# Herramientas de Gestión de Procesos Segura — Jessyca Windows MCP (Subetapa 06.3)

## Visión General

La **Subetapa 06.3** implementa la inspección y administración segura de procesos de Windows bajo el dominio `windows.process`.

Proporciona inspección acotada (`list_processes`, `get_process`, `get_process_by_pid`) y terminación de procesos estrictamente controlada (`terminate_process`), interceptada en su totalidad por el **SecureExecutionPipeline** (04.1–06.2).

---

## Garantía Absoluta de Cero Shell Execution

Toda interacción con procesos de Windows se realiza exclusivamente mediante la biblioteca `psutil`.

**NO** se utiliza:
- `subprocess`
- `os.system`
- `cmd.exe`
- `powershell.exe`
- `shell=True`
- `ctypes`
- `os.popen`

---

## Flujo de Seguridad e Interceptación

```text
MCP Client Payload
    ↓
RequestContext (Aislamiento de Entradas No Confiables)
    ↓
ExecutionRequest (Inmutable)
    ↓
CapabilityResolver (06.1 - windows.process)
    ↓
[PROCESS_QUERY_STARTED / PROCESS_TERMINATION_REQUESTED Audit Event]
    ↓
SecureExecutionPipeline (Orquestador Central)
    ├─ RiskEngine (04.2)
    ├─ SecurityPolicyEvaluator (04.5)
    ├─ PermissionManager (04.3)
    ├─ SecurityDecisionAggregator (Decision = most_restrictive)
    └─ ConfirmationManager (04.4 - Exigido para terminate_process)
    ↓
AuthorizationEvidence (Binding Criptográfico SHA-256 de tool_name + operation + pid + process_name + creation_time + request_id)
    ↓
SecureExecutionBoundary (05.2 - Validador de Evidence & Action Fingerprint)
    ↓
WindowsProcessToolExecutor (tools/process/executor.py)
    ├─ Verificación de Procesos Protegidos del Sistema
    ├─ Verificación de Protección contra Reutilización de PID (PID Reuse Protection)
    └─ ProcessService Execution (psutil)
    ↓
[PROCESS_TERMINATION_SUCCEEDED / FAILED Audit Event]
    ↓
EventBus: process:termination_completed / process:failed
```

---

## Operaciones Soportadas y Niveles de Riesgo

| Operación | Riesgo Declarado | Decisión por Defecto | Requiere Confirmación | Límites & Protecciones |
|---|---|---|---|---|
| `list_processes` | `SAFE` | `ALLOW` | No | Máx. 1000 entradas (`PROCESS_MAX_LIST_ENTRIES`), Timeout 5.0s |
| `get_process` | `SAFE` | `ALLOW` | No | Validación de PID positivo |
| `get_process_by_pid` | `SAFE` | `ALLOW` | No | Validación de PID positivo |
| `terminate_process` | `DANGEROUS` | `REQUIRE_CONFIRMATION` | Sí | **Protected Process Check** + **PID Reuse Protection** |

---

## Mecanismos Antifraude y Anti-Tampering

1. **Protección de Procesos del Sistema Protegidos (`PROCESS_PROTECTED_NAMES`)**:
   Deniega categóricamente cualquier intento de terminación de procesos del sistema como `System`, `csrss.exe`, `lsass.exe`, `services.exe`, `winlogon.exe`, `svchost.exe`, `explorer.exe`.
2. **Protección contra Reutilización de PID (`PID Reuse Protection`)**:
   Windows recicla PIDs. La evidencia de autorización vincula el `pid` junto con `process_name` y `creation_time`. Si el proceso original finaliza y otro proceso diferente hereda el mismo PID, la frontera detecta la discrepancia (`PIDReuseError`) y deniega la terminación.
