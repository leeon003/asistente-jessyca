# Arquitectura de Seguridad - Jessyca Windows MCP (Subetapa 04.1)

## Propósito

El subsistema de seguridad de **Jessyca Windows MCP** está diseñado desde cero siguiendo **Clean Architecture**, **SOLID** y el principio de **Seguridad por Diseño** (Security by Design).

Su objetivo es actuar como una capa de inspección e interceptación previa a la ejecución de cualquier herramienta MCP solicitada por el usuario o modelos de lenguaje (LLM).

---

## Componentes y Modelos de Dominio (Subetapa 04.1)

En la Subetapa 04.1 se han construido los contratos, enums y modelos de dominio tipados centrales:

### 1. Niveles de Seguridad (`SecurityLevel`)
Enum tipado para clasificar el nivel de riesgo de las herramientas:
- **`SAFE`**: Operaciones seguras sin efectos secundarios graves (ej. lectura de información de sistema).
- **`WARNING`**: Operaciones de modificación moderada que requieren precaución.
- **`DANGEROUS`**: Operaciones de alto impacto que requieren confirmación interactiva del usuario.
- **`CRITICAL`**: Operaciones de riesgo crítico que exigen elevación de privilegios UAC/Admin en Windows.

### 2. Decisiones de Autorización (`SecurityDecisionType`)
Enum tipado con los tipos formales de resolución:
- **`ALLOW`**: Autorizado para ejecución inmediata.
- **`DENY`**: Rechazado / Bloqueado.
- **`REQUIRE_CONFIRMATION`**: Requiere confirmación previa del usuario.
- **`REQUIRE_ELEVATED_AUTHORIZATION`**: Requiere elevación de privilegios de Administrador en Windows.

### 3. Modelos de Estructura de Datos
- **`SecurityContext`**: Transporta los metadatos de sesión y entorno (`user`, `tool_name`, `parameters`, `session_id`, `correlation_id`, `timestamp`, `environment`).
- **`ToolSecurityMetadata`**: Especificación declarativa del perfil de seguridad de una herramienta (`tool_name`, `category`, `risk_level`, `requires_confirmation`, `requires_elevation`, `allowed_operations`).
- **`SecurityRequest`**: Solicitud de evaluación que agrupa `context`, `metadata` y la `action` requerida.
- **`SecurityDecision`**: Decisión detallada resultante con el `decision_type`, `reason` y banderas explicativas.
- **`SecurityResult`**: Resultado consolidado devuelto por el evaluador (`is_allowed`, `decision`, `request_id`, `evaluated_at`).

### 4. Protocolo e Interfaz (`ISecurityEvaluator`)
Contrato abstracto basado en Inversión de Dependencias (DIP):
```python
class ISecurityEvaluator(Protocol):
    def evaluate(self, request: SecurityRequest) -> SecurityResult:
        ...
```

---

## Flujo Futuro de Autorización (Etapa 04)

```text
Usuario / LLM
      ↓
Task / Tool Request
      ↓
Security Manager (ISecurityEvaluator)
      ↓
Risk Analysis (04.2 Risk Engine)
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

- **04.2 — Risk Engine**: Inspección dinámica de riesgo basada en parámetros.
- **04.3 — Permission Manager**: Control de permisos jerárquicos y comodines.
- **04.4 — Confirmation Manager**: Solicitudes interactivas estructuradas.
- **04.5 — Security Policy**: Políticas configurables multi-dimensión.
- **04.6 — Audit Logger**: Registro inmutable de auditoría.
- **04.7 — Security Tests**: Suite completa de pruebas de seguridad end-to-end.
