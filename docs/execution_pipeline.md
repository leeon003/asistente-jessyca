# Orquestador del Pipeline de Ejecución Segura — Jessyca Windows MCP (Subetapa 05.2)

## Visión General

El **Secure Execution Pipeline** de **Jessyca Windows MCP** actúa como el orquestador central que conecta la infraestructura del servidor MCP (`JessycaMCPServer` - Subetapa 05.1) con todas las capas de interceptación de seguridad (Subetapas 04.1–04.7).

Garantiza un flujo de evaluación determinista de **10 pasos exactos** en el cual **ninguna etapa de seguridad puede ser omitida ni evadida**, produciendo evidencia de autorización criptográficamente vinculada (`AuthorizationEvidence`) antes de alcanzar la frontera de ejecución (`SecureExecutionBoundary`).

---

## Flujo de Autorización en 10 Pasos Exactos

```text
MCP Client Payload (untrusted)
       ↓
RequestContext (Aislamiento de Entradas No Confiables - FORBIDDEN_CLIENT_OVERRIDE_KEYS)
       ↓
ExecutionRequest (Inmutable)
       ↓
SecureExecutionPipeline (Orquestador Central)
       ├─ [Paso 1] AuditLogger: REQUEST_RECEIVED
       ├─ [Paso 2] RiskEngine: RISK_EVALUATED
       ├─ [Paso 3] SecurityPolicyEvaluator: POLICY_EVALUATED
       ├─ [Paso 4] PermissionManager: PERMISSION_EVALUATED
       ├─ [Paso 5] SecurityDecisionAggregator -> AggregatedSecurityDecision (DENY / ALLOW / CONFIRM)
       ├─ [Paso 6] ConfirmationManager: CONFIRMATION_REQUESTED -> APPROVED / REJECTED (si requiere confirmación)
       ├─ [Paso 7] Generator: AuthorizationEvidence (SHA-256 Action Fingerprint Binding)
       ├─ [Paso 8] AuditLogger: EXECUTION_STARTED & EventBus: execution:started
       ├─ [Paso 9] SecureExecutionBoundary: Verificación de Evidencia & Delegación a IToolExecutor
       └─ [Paso 10] AuditLogger: EXECUTION_DISABLED (o EXECUTION_SUCCEEDED / EXECUTION_FAILED / EXECUTION_DENIED)
       ↓
EventBus: execution:completed / execution:denied
```

---

## Distinción de Estados de Ejecución y Auditoría

Para evitar ambigüedades arquitectónicas:
- **`EXECUTION_SUCCEEDED`**: Se registra **únicamente** cuando una herramienta real fue ejecutada por el sistema operativo y reportó éxito.
- **`EXECUTION_DISABLED`**: Se registra cuando la ejecución real se encuentra deshabilitada (ej. en la Subetapa 05.2 con `DisabledToolExecutor`).
- **`EXECUTION_FAILED`**: Se registra cuando la ejecución sufrió un error técnico durante el proceso.
- **`EXECUTION_DENIED`**: Se registra cuando cualquier capa de seguridad o confirmación denegó la operación.

---

## Componentes Clave

### 1. `ExecutionRequest` (`server/execution_request.py`)
Modelo de datos inmutable que representa formalmente la solicitud procesada internamente. Desestima explícitamente cualquier parámetro de seguridad inyectado en el payload por un cliente MCP no confiable.

### 2. `SecurityDecisionAggregator` (`server/aggregator.py`)
Combina las decisiones de las 4 capas de seguridad de acuerdo con las invariantes estrictas de Jessyca:
- Operaciones `CRITICAL` -> Jamás `ALLOW` directo.
- Operaciones `UNKNOWN` -> `DENY` por Fail-Safe.
- `requires_elevation=True` -> Exige `REQUIRE_ELEVATED_AUTHORIZATION`.
- Regla DENY Overriding -> `DENY` prevalece siempre.

### 3. `AuthorizationEvidence` (`server/evidence.py`)
Evidencia de autorización inmutable generada exclusivamente por el sistema. Incluye un binding criptográfico (`action_fingerprint` SHA-256) que vincula estrictamente:
$$\text{action\_fingerprint} = \text{SHA256}(\text{tool\_name} + \text{operation} + \text{parameters\_canonicos} + \text{request\_id})$$

Si los parámetros, la herramienta, la operación o el `request_id` cambian post-autorización, `validate_integrity()` devuelve `False` e invalida la evidencia.

### 4. `SecureExecutionBoundary` (`server/boundary.py`)
Exige y valida la presencia e integridad de `AuthorizationEvidence` antes de delegar cualquier solicitud al ejecutor.

### 5. `DisabledToolExecutor` (`server/executor.py`)
Implementación del contrato `IToolExecutor` para la Subetapa 05.2.
**Garantía de Seguridad Absoluta**: Devuelve una respuesta determinista `EXECUTION_DISABLED_IN_05_2` con estado `EXECUTION_DISABLED` sin invocar `subprocess`, `PowerShell`, `CMD`, `ctypes` ni ejecuciones mutables en Windows.
