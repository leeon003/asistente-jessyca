# Arquitectura de Seguridad - Jessyca Windows MCP (Etapa 04)

## Propósito

El subsistema de seguridad de **Jessyca Windows MCP** está diseñado siguiendo **Clean Architecture**, **SOLID** y el principio de **Seguridad por Diseño** (Security by Design).

Su objetivo es actuar como una capa de inspección e interceptación previa a la ejecución de cualquier herramienta MCP solicitada por el usuario o modelos de lenguaje (LLM).

---

## Componentes y Modelos de Dominio (Subetapas 04.1 y 04.2)

### 1. Niveles de Seguridad (`SecurityLevel`)
Enum tipado para clasificar el nivel de riesgo de las herramientas:
- **`SAFE`**: Operaciones seguras sin efectos secundarios graves (ej. lectura de información de sistema).
- **`WARNING`**: Operaciones de modificación moderada que requieren precaución (ej. modificar archivos de usuario, iniciar procesos).
- **`DANGEROUS`**: Operaciones de alto impacto que requieren confirmación interactiva del usuario (ej. eliminar archivos, finalizar procesos, operaciones recursivas).
- **`CRITICAL`**: Operaciones de riesgo crítico que exigen elevación de privilegios UAC/Admin en Windows o modifican el Registro de Windows (`HKLM`) o rutas de sistema (`C:\Windows\System32`).

### 2. Decisiones de Autorización (`SecurityDecisionType`)
Enum tipado con los tipos formales de resolución:
- **`ALLOW`**: Autorizado para ejecución inmediata.
- **`DENY`**: Rechazado / Bloqueado.
- **`REQUIRE_CONFIRMATION`**: Requiere confirmación previa del usuario.
- **`REQUIRE_ELEVATED_AUTHORIZATION`**: Requiere elevación de privilegios de Administrador en Windows.

### 3. Subetapa 04.2 — Risk Engine (`RiskEngine` & `IRiskEvaluator`)
Motor de evaluación de riesgo **independiente, determinista, extensible y desacoplado**.

#### Responsabilidad Única
Responde exclusivamente a la pregunta:  
`"¿Qué nivel de riesgo representa esta operación?"`

> [!IMPORTANT]
> El `RiskEngine` **NO** ejecuta herramientas, **NO** permite/deniega permisos (`ALLOW`/`DENY`/`ASK`), **NO** solicita confirmaciones, **NO** muestra diálogos, **NO** modifica el sistema ni registra auditorías. Se limita a producir un `RiskAssessment` puro.

#### Factores de Riesgo (`RiskFactor`)
Enum estructurado con los factores que influyen en el análisis:
- `DESTRUCTIVE_OPERATION`
- `SYSTEM_CONFIGURATION`
- `ELEVATED_PRIVILEGES`
- `PROCESS_CONTROL`
- `FILE_MODIFICATION`
- `NETWORK_OPERATION`
- `CREDENTIAL_ACCESS`
- `REGISTRY_MODIFICATION`
- `BULK_OPERATION`
- `UNKNOWN_OPERATION`

#### Reglas Modulares de Riesgo (`IRiskRule`)
- **`StaticMetadataRiskRule`**: Evalúa metadatos declarados por la herramienta.
- **`PrivilegeRiskRule`**: Evalúa requerimientos UAC de administración.
- **`SystemPathRiskRule`**: Inspecciona rutas críticas (`C:\Windows`, `System32`, `HKLM`).
- **`FileOperationRiskRule`**: Clasifica lectura (`SAFE`), escritura (`WARNING`) y eliminación (`DANGEROUS`).
- **`ProcessControlRiskRule`**: Clasifica inicio de proceso (`WARNING`) y terminación forzada (`DANGEROUS`).
- **`BulkOperationRiskRule`**: Detecta operaciones recursivas/masivas (`DANGEROUS`).
- **`UnknownOperationRiskRule`**: Estrategia Fail-Safe para acciones desconocidas o metadatos incompletos (`WARNING` + `UNKNOWN_OPERATION`).

#### Agregación de Riesgo Máximo
El `RiskEngine` combina todas las reglas modulares y calcula el **nivel de riesgo máximo**:
$$\text{SAFE (1)} < \text{WARNING (2)} < \text{DANGEROUS (3)} < \text{CRITICAL (4)}$$

---

## Flujo Futuro de Autorización (Etapa 04)

```text
Usuario / LLM
      ↓
Task / Tool Request
      ↓
Security Manager (ISecurityEvaluator)
      ↓
Risk Engine (04.2 IRiskEvaluator -> RiskAssessment)
      ↓
Permission Check (04.3 Permission Manager)
      ↓
Confirmation (04.4 Confirmation Manager)
      ↓
Tool Execution
      ↓
Audit Log (04.6 Audit Logger)
```

---

## Extensiones en Subetapas Posteriores

- **04.3 — Permission Manager**: Control de permisos jerárquicos y comodines.
- **04.4 — Confirmation Manager**: Solicitudes interactivas estructuradas.
- **04.5 — Security Policy**: Políticas configurables multi-dimensión.
- **04.6 — Audit Logger**: Registro inmutable de auditoría.
- **04.7 — Security Tests**: Suite completa de pruebas de seguridad end-to-end.
