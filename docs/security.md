# Arquitectura de Seguridad - Jessyca Windows MCP (Etapa 04)

## Propósito

El subsistema de seguridad de **Jessyca Windows MCP** está diseñado siguiendo **Clean Architecture**, **SOLID** y el principio de **Seguridad por Diseño** (Security by Design).

Su objetivo es actuar como una capa de inspección e interceptación previa a la ejecución de cualquier herramienta MCP solicitada por el usuario o modelos de lenguaje (LLM).

---

## Componentes y Modelos de Dominio (Subetapas 04.1, 04.2 y 04.3)

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

### 3. Orígenes de Autorización (`PermissionSource`)
Enum que documenta la fuente de la regla de permiso:
- **`DEFAULT`**: Regla base por defecto del sistema.
- **`TOOL`**: Regla basada en la especificación de la herramienta.
- **`OPERATION`**: Regla basada en el tipo de operación.
- **`SESSION`**: Permiso temporal activo en la sesión.
- **`USER`**: Consentimiento directo del usuario.
- **`SYSTEM`**: Regla de seguridad del sistema.

### 4. Subetapa 04.2 — Risk Engine (`RiskEngine` & `IRiskEvaluator`)
Motor de evaluación de riesgo **independiente, determinista, extensible y desacoplado**.
Responde exclusivamente a la pregunta:  
`"¿Qué nivel de riesgo representa esta operación?"` -> Produce un `RiskAssessment`.

### 5. Subetapa 04.3 — Permission Manager (`PermissionManager` & `IPermissionManager`)
Componente desacoplado responsable exclusivamente de responder:  
`"¿Esta operación está autorizada?"`

> [!IMPORTANT]
> El `PermissionManager` **NO** ejecuta herramientas y **NO** interactúa con el usuario (no abre ventanas, ni diálogos, ni usa `input()`, ni TTS/STT). Si determina `REQUIRE_CONFIRMATION`, devuelve dicho resultado de forma pasiva para que un futuro `ConfirmationManager` gestione la interacción.

#### Estrategia Fail-Safe / Default Deny
Ante solicitudes con contexto incompleto, metadatos nulos o niveles de riesgo ambiguos/críticos sin permisos elevados previa elevación, el `PermissionManager` devuelve explícitamente `PermissionDecision.DENY` indicando un motivo detallado (`reason`).

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
[04.4 Confirmation Manager - Futuro]
      ↓
Tool Execution
      ↓
[04.6 Audit Logger - Futuro]
```

---

## Extensiones en Subetapas Posteriores

- **04.4 — Confirmation Manager**: Solicitudes interactivas estructuradas de confirmación.
- **04.5 — Security Policy**: Políticas configurables multi-dimensión y persistencia.
- **04.6 — Audit Logger**: Registro inmutable de auditoría.
- **04.7 — Security Tests**: Suite completa de pruebas de seguridad end-to-end.
