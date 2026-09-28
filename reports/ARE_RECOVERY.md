# Reporte de Diagnóstico y Recuperación de Fallos: ARE Recovery Engine

**Fecha:** 2026-09-27  
**Fase:** Fase 7 — Integración de Diagnóstico y Recuperación de Fallos  
**Estado:** GOBERNADO POR JDE / ANTI-BUCLE INFINITO IMPLEMENTADO / ZERO DIRECT RETRY  

---

## 1. Principios del Ciclo de Recuperación

En la arquitectura de JESSYCA PC, el proceso de diagnóstico y recuperación ante fallos de ejecución está estrictamente gobernado:
- **ARE no ejecuta reintentos físicos:** ARE únicamente formula diagnósticos estructurados (`AREDiagnosis`) y propuestas de recuperación (`ARERecoveryProposal`).
- **JDE mantiene la autoridad decisional:** Toda propuesta de recuperación o reintento de paso debe ser aprobada explícitamente por JDE antes de someterse a las capas de seguridad y despacho.
- **Prevención de bucles infinitos:** Se define un límite rígido de `MAX_RECOVERY_ATTEMPTS = 2` por tarea compleja. Al superar este umbral, el sistema cancela la ejecución y emite una alerta auditada.

---

## 2. Flujo de Ejecución y Recuperación

```
User Request
  ↓
JessycaLocalAgent
  ↓
JDE Runtime Binding (evaluate_intent)
  ↓
ARE (decompose_task & evaluate_plan)
  ↓
JDE Authority (evaluate_proposal & evaluate_step)
  ↓
Security Layers (RiskEngine, PermissionManager, IdempotencyGuard)
  ↓
Execution Boundary & Adapter
  ↓
ExecutionVerifier (Detecta Failure)
  ↓
ARERuntime.diagnose_failure (Analiza error, categoría, severidad y recuperabilidad)
  ↓
ARERuntime.recover_plan (Genera ARERecoveryProposal con steps alternativos o mitigación)
  ↓
JDE Authority (Evalúa nueva propuesta de recuperación)
  ↓
Security Layers
  ↓
Re-ejecución Gobernada (o Rollback seguro si no es recuperable)
```

---

## 3. Capacidades Específicas de ARE

### 3.1 `are.diagnose_failure`
- **Entrada:** `step_id`, `action`, `error_message`, `context`, `traceback`.
- **Salida (`AREDiagnosis`):**
  - `category`: `TRANSIENT`, `RESOURCE_EXHAUSTED`, `PERMISSION_DENIED`, `DEPENDENCY_MISSING`, `INVALID_ARGUMENT`, o `UNKNOWN`.
  - `severity`: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
  - `recoverable`: Booleano determinando si el fallo admite mitigación algorítmica.
  - `root_cause`: Explicación concisa de la causa raíz.

### 3.2 `are.recover_plan`
- **Entrada:** `failed_step`, `plan`, `diagnosis`, `attempt_number`.
- **Salida (`ARERecoveryProposal`):**
  - `strategy`: `RETRY_STEP`, `FALLBACK_STEP`, `SKIP_STEP`, o `ABORT_AND_ROLLBACK`.
  - `recovery_steps`: Lista de nuevos `AREStepProposal` para sustituir o mitigar el fallo.
  - `confidence`: Nivel de confianza numérico en la recuperación.
  - `integrity_hash`: Hash SHA-256 de la propuesta para garantizar inmutabilidad.

---

## 4. Controles y Protecciones Antifallos

1. **Idempotencia:** Cada intento de recuperación se registra en `IdempotencyGuard` con su respectivo identificador y número de intento, evitando ejecuciones duplicadas no deseadas.
2. **Límite de Reintentos:**
   ```python
   MAX_RECOVERY_ATTEMPTS = 2
   if attempt > MAX_RECOVERY_ATTEMPTS:
       # Cancelación segura, bloqueo de reintentos adicionales
   ```
3. **Bloqueo de Side Effects:** Si JDE emite `DENY` sobre una propuesta de recuperación, el sistema termina inmediatamente con cero efectos secundarios.

---

## 5. Resultados de Pruebas

- `test_are_recovery.py::test_are_diagnose_failure_transient`: **PASS** (Identificación de fallos transitorios y recomendación de reintento).
- `test_are_recovery.py::test_are_recover_plan_max_attempts_exhaustion`: **PASS** (Bloqueo exitoso de bucle infinito tras 2 intentos).
- `test_are_e2e.py::test_e2e_case_e_failure_recovery`: **PASS** (Ciclo E2E completo: Falla -> Diagnóstico -> Recuperación aprobada por JDE -> Éxito).
