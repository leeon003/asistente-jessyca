# JESSYCA PC — ORCA + ADE FASE 3 EXECUTION VERIFIER & REVIEW GATE REPORT

## VERIFICACIÓN DE EJECUCIÓN Y PUERTA DE REVISIÓN

### 1. Estados Formales del Verificador de Ejecución
El `ExecutionVerifier` protege al sistema contra éxitos ficticios (*false-success*) mediante la comprobación estricta de evidencia física:
1. `CLAIMED_SUCCESS`: El agente concluye su trabajo y propone un parche o cambio de código, pero aún no cuenta con verificación física completa o aprobación formal.
2. `VERIFIED_SUCCESS`: La evidencia física (staged diff, exit code de tests en disco, integridad de archivos) ha sido corroborada fehacientemente y aprobada por la autoridad competente.
3. `VERIFICATION_FAILED`: El agente proclama haber terminado, pero la evidencia física está ausente, corrupta o los tests reportan error. El veredicto del agente ("Done") es explícitamente ignorado.

### 2. Puerta de Revisión (Review Gate)
* Los agentes tienen **estrictamente prohibido auto-aprobarse** (`self-approval prohibited`).
* Toda tarea marcada con `requires_review=True` ingresa al estado `WAITING_REVIEW`.
* La transición a `COMPLETED` y `VERIFIED_SUCCESS` requiere una invocación explícita de `approve_review(task_id)` ejecutada por el operador o por el JDE como autoridad superior.
* Si el revisor rechaza la propuesta (`reject_review`), el estado final se marca como `DENIED` y los cambios se descartan de forma segura.
