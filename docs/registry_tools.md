# Herramientas de Inspección Segura del Registro de Windows — Jessyca Windows MCP (Subetapa 06.4)

## Visión General

La **Subetapa 06.4** implementa herramientas reales, seguras y **exclusivamente de lectura** para la inspección del Registro de Windows bajo el dominio `windows.registry`.

Todas las operaciones de consulta (`list_registry_subkeys`, `get_registry_key`, `list_registry_values`, `get_registry_value`) operan bajo estricta validación de **RegistryPathSecurityManager**, filtrado de **Allowed Hives** (`HKEY_CURRENT_USER`, `HKEY_LOCAL_MACHINE`) y total interceptación determinista por el **SecureExecutionPipeline** (04.1–06.3).

---

## GARANTÍA ABSOLUTA: READ-ONLY Y CERO SHELL EXECUTION

1. **ESTRICTAMENTE READ-ONLY**: No se permite ninguna operación de escritura, modificación, eliminación, creación ni renombrado de claves o valores del Registro.
2. **CERO SHELL EXECUTION**:
   - **NO** se ejecuta `reg.exe`
   - **NO** se utiliza `subprocess`
   - **NO** se utiliza `os.system`
   - **NO** se utiliza `PowerShell`
   - **NO** se utiliza `CMD`
   - **NO** se utiliza `shell=True`

Las consultas al Registro en Windows se realizan exclusivamente mediante la API nativa del módulo `winreg` de Python a través de la abstracción `WindowsWinregBackend` (con soporte para `FakeRegistryBackend` en pruebas y entornos fuera de Windows).

---

## Flujo de Seguridad e Interceptación

```text
MCP Client Payload
    ↓
RequestContext (Aislamiento de Entradas No Confiables)
    ↓
ExecutionRequest (Inmutable)
    ↓
CapabilityResolver (06.1 - windows.registry)
    ↓
[REGISTRY_QUERY_STARTED Audit Event]
    ↓
RegistryPathSecurityManager (tools/registry/path_security.py)
    ├─ Verificación de Hive Autorizado (HKCU / HKLM)
    ├─ Normalización de Ruta y Filtro de Caracteres Nulos (\x00)
    └─ Verificación de Profundidad Máxima (REGISTRY_MAX_DEPTH = 10)
    ↓
[REGISTRY_PATH_VALIDATED Audit Event]
    ↓
SecureExecutionPipeline (Orquestador Central)
    ├─ RiskEngine (04.2)
    ├─ SecurityPolicyEvaluator (04.5)
    ├─ PermissionManager (04.3)
    └─ SecurityDecisionAggregator (Decision = most_restrictive)
    ↓
AuthorizationEvidence (Binding Criptográfico SHA-256)
    ↓
SecureExecutionBoundary (05.2)
    ↓
WindowsRegistryToolExecutor (tools/registry/executor.py)
    └─ RegistryService (tools/registry/registry_service.py -> IRegistryBackend)
    ↓
[REGISTRY_QUERY_SUCCEEDED / FAILED Audit Event]
    ↓
EventBus: registry:query_completed / registry:failed
```

---

## Operaciones Soportadas y Niveles de Riesgo

| Operación | Tipo | Riesgo Declarado | Decisión por Defecto | Límites & Controles |
|---|---|---|---|---|
| `list_registry_subkeys` | READ | `SAFE` | `ALLOW` | Máx. 1000 subclaves (`REGISTRY_MAX_SUBKEYS`) |
| `get_registry_key` | READ | `SAFE` | `ALLOW` | Metadatos de la clave |
| `list_registry_values` | READ | `SAFE` | `ALLOW` | Máx. 1000 valores (`REGISTRY_MAX_VALUES`) |
| `get_registry_value` | READ | `SAFE` | `ALLOW` | Máx. 1 MB por valor binario (`REGISTRY_MAX_VALUE_SIZE`) |
