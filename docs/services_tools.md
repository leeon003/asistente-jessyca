# Herramientas de Inspección Segura de Servicios de Windows — Jessyca Windows MCP (Subetapa 06.5)

## Visión General

La **Subetapa 06.5** implementa herramientas reales, seguras y **exclusivamente de lectura** para la inspección de Servicios de Windows bajo el dominio `windows.services`.

Todas las operaciones de consulta (`list_services`, `get_service`, `get_service_status`, `get_service_configuration`) operan bajo la validación estricta del **ServiceNameSecurityManager** y la interceptación determinista del **SecureExecutionPipeline** (04.1–06.4).

---

## GARANTÍA ABSOLUTA: READ-ONLY Y CERO SHELL EXECUTION

1. **ESTRICTAMENTE READ-ONLY**: No se permite ninguna operación de modificación (Start, Stop, Restart, Pause, Resume, Create, Delete o Change Configuration).
2. **CERO SHELL / EXTERNAL EXECUTION**:
   - **NO** se utiliza `subprocess`
   - **NO** se utiliza `os.system`
   - **NO** se utiliza `os.popen`
   - **NO** se utiliza `cmd.exe`
   - **NO** se utiliza `powershell.exe`
   - **NO** se utiliza `sc.exe`
   - **NO** se utiliza `shell=True`

Las consultas en Windows se ejecutan mediante los bindings nativos de la API de procesos/servicios (`psutil.win_service_iter()`) a través de la abstracción `WindowsServicesBackend` (con soporte para `FakeServicesBackend` en pruebas y entornos fuera de Windows).

---

## Flujo de Seguridad e Interceptación

```text
MCP Client Payload
    ↓
RequestContext (Aislamiento de Entradas No Confiables)
    ↓
ExecutionRequest (Inmutable)
    ↓
CapabilityResolver (06.1 - windows.services)
    ↓
[SERVICE_QUERY_STARTED Audit Event]
    ↓
ServiceNameSecurityManager (tools/services/name_security.py)
    ├─ Bloqueo de Patrones de Inyección de Comandos (&, |, ;, comillas, $(), sc.exe, powershell)
    ├─ Filtro de Nulos (\x00) y Caracteres de Control
    └─ Verificación de Longitud Máxima (SERVICES_MAX_NAME_LENGTH = 256)
    ↓
[SERVICE_NAME_VALIDATED Audit Event]
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
WindowsServicesToolExecutor (tools/services/executor.py)
    └─ ServicesService (tools/services/services_service.py -> IWindowsServicesBackend)
    ↓
[SERVICE_QUERY_SUCCEEDED / FAILED Audit Event]
    ↓
EventBus: services:query_completed / services:failed
```

---

## Operaciones Soportadas y Niveles de Riesgo

| Operación | Tipo | Riesgo Declarado | Decisión por Defecto | Límites & Controles |
|---|---|---|---|---|
| `list_services` | READ | `SAFE` | `ALLOW` | Máx. 1000 servicios (`SERVICES_MAX_LIST_ENTRIES`) |
| `get_service` | READ | `SAFE` | `ALLOW` | Sanitización de nombre de servicio |
| `get_service_status` | READ | `SAFE` | `ALLOW` | Estado y PID |
| `get_service_configuration` | READ | `SAFE` | `ALLOW` | Tipo de inicio y ruta ejecutable |
