# Arquitectura de Seguridad - Jessyca Windows MCP (Etapa 04)

## Propósito

El subsistema de seguridad de **Jessyca Windows MCP** está diseñado siguiendo **Clean Architecture**, **SOLID** y el principio de **Seguridad por Diseño** (Security by Design).

Su objetivo es actuar como una capa de inspección e interceptación previa a la ejecución de cualquier herramienta MCP solicitada por el usuario o modelos de lenguaje (LLM).

---

## Componentes y Modelos de Dominio (Subetapas 04.1 a 04.4)

### 1. Niveles de Seguridad (`SecurityLevel`)
Enum tipado para clasificar el nivel de riesgo de las herramientas:
- **`SAFE`**: Operaciones seguras sin efectos secundarios graves (ej. lectura de información de sistema).
- **`WARNING`**: Operaciones de modificación moderada que requieren precaución (ej. modificar archivos de usuario, iniciar procesos).
- **`DANGEROUS`**: Operaciones de alto impacto que requieren confirmación interactiva del usuario (ej. eliminar archivos, finalizar procesos, operaciones recursivas).
- **`CRITICAL`**: Operaciones de riesgo crítico que exigen elevación de privilegios UAC/Admin en Windows o modifican el Registro de Windows (`HKLM`) o rutas de sistema (`C:\Windows\System32`).

### 2. Decisiones de Autorización (`PermissionDecision`)
Enum tipado con los tipos formales de resolución de permisos (Subetapa 04.3):
- **`ALLOW`**: Autorizado para ejecución inmediata.
- **`DENY`**: Rechazado / Denegado explícitamente con un motivo explicativo (`reason`).
- **`REQUIRE_CONFIRMATION`**: Requiere confirmación previa antes de ejecutar.
- **`ALLOW_ONCE`**: Concedido temporalmente únicamente para un único uso.
- **`ALWAYS_ALLOW`**: Autorizado permanentemente.

### 3. Estados de Confirmación (`ConfirmationStatus`)
Enum tipado del ciclo de vida de una confirmación de usuario (Subetapa 04.4):
- **`PENDING`**: Esperando respuesta.
- **`APPROVED`**: El usuario aprobó la solicitud.
- **`REJECTED`**: El usuario rechazó la solicitud.
- **`CANCELLED`**: La solicitud fue cancelada formalmente.
- **`EXPIRED`**: No hubo respuesta dentro del tiempo límite (TTL / Expiración).

### 4. Subetapa 04.2 — Risk Engine (`RiskEngine` & `IRiskEvaluator`)
Motor de evaluación de riesgo **independiente, determinista, extensible y desacoplado**.
Responde exclusivamente a: `"¿Qué nivel de riesgo representa esta operación?"` -> Produce un `RiskAssessment`.

### 5. Subetapa 04.3 — Permission Manager (`PermissionManager` & `IPermissionManager`)
Componente desacoplado de autorización.
Responde exclusivamente a: `"¿Esta operación está autorizada?"` -> Produce un `PermissionResult` (`ALLOW`, `DENY`, `REQUIRE_CONFIRMATION`, `ALLOW_ONCE`, `ALWAYS_ALLOW`).

### 6. Subetapa 04.4 — Confirmation Manager (`ConfirmationManager` & `IConfirmationManager`)
Administra y valida las solicitudes de confirmación para operaciones que requieren aprobación explícita del usuario.
Responde exclusivamente a: `"¿Esta solicitud de confirmación fue aceptada, rechazada, cancelada o expiró?"`

> [!IMPORTANT]
> El `ConfirmationManager` **NO** ejecuta herramientas, **NO** modifica el sistema Windows y **NO** ejecuta comandos.

#### Binding de Acción mediante Action Fingerprint (SHA-256)
Cada confirmación está matemáticamente vinculada a un hash determinista:
$$\text{ActionFingerprint} = \text{SHA256}(\text{tool\_name} + \text{operation} + \text{canonical\_parameters})$$
Una confirmación otorgada para la Solicitud A jamás puede ser reutilizada para ejecutar una Solicitud B distinta.

#### Protección contra Replay Attacks & Consumo Único
Toda confirmación aprobada consumida queda bloqueada inmutablemente. Intentos de reutilización o Replay Attacks son rechazados. Incluye cerrojo de hilos (`threading.Lock`) para proteger contra condiciones de carrera.

#### Sanitización de Parámetros Sensibles
Campos sensibles (`password`, `token`, `api_key`, `secret`, `credential`) se representan como `"[REDACTED]"` en vistas de diagnóstico sin alterar el cálculo determinista del fingerprint real.

#### Proveedor de Confirmación Abstraído (`IConfirmationProvider`)
Protocolo desacoplado con implementación `MockConfirmationProvider` para simulación de respuestas en pruebas unitarias (`APPROVED`, `REJECTED`, `CANCELLED`, `TIMEOUT`).

---

## Flujo de Autorización (Etapa 04)

```text
Usuario / LLM
      ↓
Task / Tool Request (SecurityRequest)
      ↓
Security Manager (ISecurityEvaluator)
      ↓
Risk Engine (04.2 IRiskEvaluator -> RiskAssessment)
      ↓
Permission Manager (04.3 IPermissionManager -> PermissionResult)
      ↓
Confirmation Manager (04.4 IConfirmationManager -> ConfirmationResult)
      ↓
Tool Execution
      ↓
[04.6 Audit Logger - Futuro]
```

---

## Extensiones en Subetapas Posteriores

- **04.5 — Security Policy**: Políticas configurables multi-dimensión y persistencia.
- **04.6 — Audit Logger**: Registro inmutable de auditoría.
- **04.7 — Security Tests**: Suite completa de pruebas de seguridad end-to-end.
