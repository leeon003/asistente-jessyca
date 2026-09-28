# INFORME DE SEGURIDAD — JDE RUNTIME BINDING (FASE 1)
**Sistema:** JESSYCA PC  
**Módulo:** JDE Runtime Binding Security Architecture  
**Fase:** Fase 1 — Conexión al Punto Real de Ejecución  
**Fecha:** 2026-09-27  
**Estado:** `SECURITY CERTIFIED — CONTROLLED`  

---

## 1. PRINCIPIO DE SEGURIDAD Y DEFENSA EN PROFUNDIDAD

El enlace en tiempo de ejecución del JDE (`JDERuntimeBinding`) implementa un esquema estricto de **defensa en profundidad**, donde el JDE actúa como primer evaluador de gobernanza, pero **bajo ninguna circunstancia anula o debilita** los controles de seguridad preexistentes.

### Cadena Inviolable de Evaluación:
```text
1. EMERGENCY STOP (EmergencyStopManager)
2. CANCELLATION TOKEN (CancellationToken)
3. MODEL ROUTER SAFETY (ExperimentalModelRouter)
4. JDE RUNTIME BINDING (Gobernanza de Autoridad)
5. RISK ENGINE (Análisis de Riesgo Estático/Dinámico)
6. PERMISSION MANAGER (Privilegios L0..L3)
7. IDEMPOTENCY GUARD (Control de Concurrencia y Doble Dispatch)
8. EXECUTION BOUNDARY (Aislamiento de la Invocación)
9. TOOL / SKILL / ADAPTER (Ejecución Física del Comando)
10. EXECUTION VERIFIER (Comprobación de Evidencia Física en el SO)
11. RECEIPT SIGNING (Firma e Inmutabilidad Forense SHA-256)
```

---

## 2. AUDITORÍA DE LOS 14 VECTORES ADVERSARIALES

Se diseñó e implementó una suite adversarial exhaustiva (`tests/jde/test_jde_adversarial.py`) para validar que cualquier intento de elusión, ataque o corrupción sea neutralizado de forma determinista y segura (Fail-Safe):

| Vector | Descripción del Intento de Ataque | Mecanismo de Defensa | Resultado |
|---|---|---|---|
| **V1: Saltar JDE** | Forzar interacción sin pasar por la evaluación de `JDERuntimeBinding`. | Integrado directamente en Paso 5.5 de `JessycaLocalAgent.interact()`; veredicto `DENY` detiene la ejecución antes del despacho de herramientas. | **BLOQUEADO (PASS)** |
| **V2: Saltar RiskEngine** | Veredicto `ALLOW` en JDE pretende omitir la validación de `RiskEngine`. | `_evaluate_action_security` se ejecuta después del JDE. Si detecta `CRITICAL`, el agente transiciona a `AWAITING_CONFIRMATION` sin despachar. | **BLOQUEADO (PASS)** |
| **V3: Saltar PermissionManager** | Acción de privilegio administrativo (`format_c` en `windows.disk`) sin permisos. | JDE en modo `CONTROLLED` detecta nivel de riesgo crítico/destructivo y emite `DENY` inmediato. | **BLOQUEADO (PASS)** |
| **V4: Saltar IdempotencyGuard** | Repetición idéntica de solicitud para forzar doble efecto secundario. | `ExecutionIdempotencyGuard.acquire_execution()` detecta huella SHA-256 idéntica y bloquea el segundo despacho físico (`call_count == 1`). | **BLOQUEADO (PASS)** |
| **V5: Ejecución tras DENY** | Intentar continuar el despacho físico cuando el JDE emitió `DENY`. | El agente valida `not verdict.can_proceed_to_execution` y aborta inmediatamente retornando `exito=False`. Cero efectos secundarios. | **BLOQUEADO (PASS)** |
| **V6: Ejecución tras REQUIRE_REVIEW** | Intentar despachar una acción de alto riesgo sin confirmación del usuario. | JDE emite `REQUIRE_REVIEW` y marca `is_blocked=True`; el agente suspende la tarea en `AWAITING_CONFIRMATION` sin tocar ejecutores. | **BLOQUEADO (PASS)** |
| **V7: Duplicación Concurrente** | Dos hilos intentan registrar simultáneamente la misma operación. | `ExecutionIdempotencyGuard._mutex` serializa la adquisición; solo un hilo adquiere el derecho de ejecución. | **BLOQUEADO (PASS)** |
| **V8: Forzar Reintento (Forced Retry)** | Forzar retry de un request ya ejecutado y verificado. | El estado `SUCCEEDED` en el registro de huella impide cualquier adquisición subsecuente para el mismo `request_id`. | **BLOQUEADO (PASS)** |
| **V9: Timeout y Cancelación** | Cancelar la operación mediante `CancellationToken` en pleno ciclo. | El agente comprueba `token.is_cancelled` antes de llegar a los efectos secundarios y transiciona a `INTERRUPTED`. | **BLOQUEADO (PASS)** |
| **V10: Manipulación de Decisión** | Intentar mutar los atributos de `DecisionContract` post-evaluación. | `DecisionContract` está configurado con `ConfigDict(frozen=True)`; cualquier intento de reasignación eleva `ValidationError`. | **BLOQUEADO (PASS)** |
| **V11: Manipulación de Recibo** | Intentar alterar campos de auditoría en `ActionReceipt` (e.g. `policy_verdict`). | `ActionReceipt` está protegido con `ConfigDict(frozen=True)`; cualquier mutación eleva `ValidationError`. | **BLOQUEADO (PASS)** |
| **V12: Falso Éxito (False Success)** | Herramienta devuelve `exito=True`, pero no hay evidencia física en el SO. | `ExecutionVerifier` detecta `is_verified=False` y degrada el resultado final a `exito=False` (`VERIFICATION_FAILED`). | **BLOQUEADO (PASS)** |
| **V13: Activación Accidental de ACTIVE** | Intento de instanciar o configurar `JDERuntimeMode.ACTIVE`. | `_resolve_runtime_mode()` detecta la restricción estricta de Fase 1, emite alerta crítica en logs y degrada a `CONTROLLED`. | **BLOQUEADO (PASS)** |
| **V14: Despacho Directo de Skill** | Petición dirigida a saltarse el planificador y llamar directamente a una skill. | El agente evalúa toda acción en Paso 5.5 sin importar la vía de entrada; veredicto `DENY` bloquea la skill. | **BLOQUEADO (PASS)** |

---

## 3. INTEGRIDAD Y CONTROL DEL KILL SWITCH

El JDE Runtime Binding está integrado de forma síncrona con el **Emergency Kill Switch** existente (`core/jde/authority.py` y `core/emergency_stop/`):
1. **Detección Inmediata:** Si `authority_gate.is_kill_switch_active` es `True` (o la variable de entorno `JDE_KILL_SWITCH=true` está presente), `JDERuntimeBinding.evaluate()` genera instantáneamente un veredicto `DENY`.
2. **Generación de Evidencia:** Se crea un `DecisionContract` con estado `DecisionState.BLOCKED` y un `ActionReceipt` con `policy_verdict="KILL_SWITCH_ACTIVE"`.
3. **Cero Tolerancia:** Ninguna acción pasa a ejecución mientras el Kill Switch esté accionado.

---

## 4. EVIDENCIA DE AISLAMIENTO: ACTIVE PERMANECE BLOQUEADO

Para garantizar la seguridad de producción y dar cumplimiento a los requerimientos de la Fase 1:
1. En `config/settings.py`:
   ```python
   @field_validator("JDE_RUNTIME_MODE", mode="before")
   def validate_jde_runtime_mode(cls, v: str) -> str:
       # Si se detecta "ACTIVE", se rechaza y degrada a "CONTROLLED"
   ```
2. En `core/jde/runtime_binding.py`:
   ```python
   PHASE1_ALLOW_ACTIVE: bool = False
   ```
   Cualquier invocación a `set_mode(JDERuntimeMode.ACTIVE)` devuelve `(False, "ACTIVE no está permitido en Fase 1")` y preserva el modo `CONTROLLED`.
